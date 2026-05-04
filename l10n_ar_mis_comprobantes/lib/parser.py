# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Parser del XLS / CSV de "Mis Comprobantes" del portal ARCA.

Lib pura — no importa ``odoo.``. Recibe bytes del archivo, devuelve lista
de dicts normalizados.

Formato del export del portal ARCA (verificado 2026-04 sobre el portal
real):

    Fila 1: nombre del reporte / título
    Fila 2: cabecera con nombres de columna
    Fila 3+: datos

Las columnas varían según sea "Comprobantes Emitidos" o
"Comprobantes Recibidos" — la diferencia clave es Receptor vs Emisor.

Columnas relevantes (matcheamos por substring case-insensitive porque el
portal cambia tildes/abreviaturas entre versiones):

    Fecha               → fecha YYYY-MM-DD
    Tipo                → tipo cbte ('1 - Factura A' → 1)
    Punto de Venta      → int
    Número Desde        → int
    Cód. Autorización   → CAE 14 dígitos
    Doc. Receptor/Emisor (Tipo + Nro)  → tupla (80/96/etc, '20219464100')
    Imp. Neto Gravado   → decimal
    IVA                 → decimal
    Imp. Total          → decimal
    Moneda              → 'PES' / 'DOL'
    Tipo Cambio         → decimal
"""
import io
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_logger = logging.getLogger(__name__)


# Map de palabras clave (lowercase, sin tildes) → key normalizada.
# **Las hints son patrones EXACTOS de match — cuanto más específico,
# antes**. El parser busca por igualdad primero y por substring después.
# Esto es importante porque "iva" como substring matchea "IVA 21%",
# "IVA 27%", "Total IVA"... necesitamos que `imp_iva` agarre "Total IVA"
# (la columna agregada de todas las alícuotas), no la primera.
#
# Para `imp_neto_gravado` queremos "Neto Gravado Total" (suma) no
# "Neto Grav. IVA 21%" (alícuota individual).
COLUMN_HINTS = {
    "fecha_emision": ("fecha de emision", "fecha de emisión", "fecha emision", "fecha"),
    "tipo": ("tipo de comprobante", "tipo comprobante", "tipo"),
    "pto_vta": ("punto de venta", "pto. de venta", "pto venta"),
    "nro_desde": ("numero desde", "número desde", "nro desde", "comprobante desde"),
    "nro_hasta": ("numero hasta", "número hasta", "nro hasta", "comprobante hasta"),
    "cae": ("cod. autorizacion", "cod. autorización", "cod autorizacion", "codigo autorizacion", "código autorización", "cae"),
    # Las hints de partner se reescriben en runtime según `kind` —
    # para batches de Recibidos el partner es el Emisor (proveedor);
    # para Emitidos es el Receptor (cliente). Acá ponemos las dos formas
    # como fallback si el `kind` no resuelve. Las hints específicas por
    # kind se inyectan en `parse_xlsx`.
    "doc_tipo_partner": ("tipo doc. emisor", "tipo doc emisor", "tipo doc. receptor", "tipo doc receptor"),
    "doc_nro_partner": ("nro. doc. emisor", "nro doc emisor", "nro. doc. receptor", "nro doc receptor",
                        "numero doc. emisor", "numero doc. receptor"),
    "denom_partner": ("denominacion emisor", "denominación emisor", "denominacion receptor", "denominación receptor"),
    "moneda": ("moneda",),
    "tipo_cambio": ("tipo cambio", "tipo de cambio", "cotizacion", "cotización"),
    # ----- Per-alícuota IVA (cada par neto_X / iva_X) -----
    # IVA 0% solo tiene "Neto Grav." (no hay columna "IVA 0%" porque
    # siempre es 0). Lo dejamos como bucket pero con iva fijo en 0.
    "neto_iva_0":   ("neto grav. iva 0%", "neto grav iva 0", "neto gravado iva 0%"),
    "neto_iva_2_5": ("neto grav. iva 2,5%", "neto grav iva 2,5", "neto grav. iva 2.5%"),
    "iva_2_5":      ("iva 2,5%", "iva 2.5%"),
    "neto_iva_5":   ("neto grav. iva 5%", "neto grav iva 5%"),
    "iva_5":        ("iva 5%",),
    "neto_iva_10_5":("neto grav. iva 10,5%", "neto grav iva 10,5", "neto grav. iva 10.5%"),
    "iva_10_5":     ("iva 10,5%", "iva 10.5%"),
    "neto_iva_21":  ("neto grav. iva 21%", "neto grav iva 21"),
    "iva_21":       ("iva 21%",),
    "neto_iva_27":  ("neto grav. iva 27%", "neto grav iva 27"),
    "iva_27":       ("iva 27%",),
    # ----- Totales (specific antes que generic) -----
    "imp_neto_gravado":  ("neto gravado total", "imp. neto gravado", "importe neto gravado"),
    "imp_neto_no_gravado": ("neto no gravado", "imp. neto no gravado"),
    "imp_op_exentas":    ("op. exentas", "operaciones exentas", "imp. op. exentas", "imp. exentas"),
    "imp_otros_tributos":("otros tributos", "imp. otros tributos"),
    "imp_iva":           ("total iva", "imp. iva"),
    "imp_total":         ("imp. total", "importe total", "imp total"),
}


def _normalize(s):
    """lower + strip + sin tildes (para matchear headers)."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    repl = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def _build_header_index(headers, kind="emitted"):
    """Devuelve dict {key normalizada: índice de columna}.

    Estrategia: para cada key, prueba los hints **en orden**. Para cada
    hint, busca exactamente esa string como cabecera (igualdad). Si no
    encuentra match exacto, cae a substring. Esto evita que
    "iva" matchee "IVA 21%" antes que "Total IVA".

    Marca las columnas ya asignadas para que un hint posterior no las
    re-use (un mismo dato no puede mapearse a 2 keys).

    `kind`: para batches "received" el partner es el Emisor (proveedor),
    para "emitted" es el Receptor (cliente). Reescribimos las hints de
    partner en consecuencia.
    """
    norm = [_normalize(h) for h in headers]
    idx = {}
    used_cols = set()
    # Override per-kind para los campos de partner.
    hints_by_key = dict(COLUMN_HINTS)
    if kind == "emitted":
        hints_by_key["doc_tipo_partner"] = ("tipo doc. receptor", "tipo doc receptor")
        hints_by_key["doc_nro_partner"] = ("nro. doc. receptor", "nro doc receptor",
                                           "numero doc. receptor")
        hints_by_key["denom_partner"] = ("denominacion receptor", "denominación receptor")
    else:
        # received → partner = emisor.
        hints_by_key["doc_tipo_partner"] = ("tipo doc. emisor", "tipo doc emisor")
        hints_by_key["doc_nro_partner"] = ("nro. doc. emisor", "nro doc emisor",
                                           "numero doc. emisor")
        hints_by_key["denom_partner"] = ("denominacion emisor", "denominación emisor")
    # Primera pasada: igualdad exacta (case insensitive, sin tildes).
    for key, hints in hints_by_key.items():
        if key in idx:
            continue
        for hint in hints:
            for col_idx, col_name in enumerate(norm):
                if col_idx in used_cols or not col_name:
                    continue
                if col_name == hint:
                    idx[key] = col_idx
                    used_cols.add(col_idx)
                    break
            if key in idx:
                break
    # Segunda pasada: substring (más permisiva).
    for key, hints in hints_by_key.items():
        if key in idx:
            continue
        for hint in hints:
            for col_idx, col_name in enumerate(norm):
                if col_idx in used_cols or not col_name:
                    continue
                if hint in col_name:
                    idx[key] = col_idx
                    used_cols.add(col_idx)
                    break
            if key in idx:
                break
    return idx


def _to_dec(v):
    """Convierte a Decimal con 2 decimales; '' / None → 0."""
    if v is None or v == "":
        return Decimal("0.00")
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    s = str(v).strip().replace(".", "").replace(",", ".")
    # AFIP usa coma decimal y punto miles; al revés que un sane locale.
    # Si el string ya viene con punto decimal y sin coma, no rompemos:
    if s.count(".") > 1:
        # demasiados puntos — había miles. el último es decimal.
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _to_int(v):
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[^\d-]", "", str(v))
    return int(s) if s else 0


def _parse_tipo(v):
    """De '1 - Factura A' → 1."""
    if v is None or v == "":
        return 0
    s = str(v).strip()
    m = re.match(r"^\s*(\d+)", s)
    return int(m.group(1)) if m else 0


def _parse_doc_tipo(v):
    """De '80 - CUIT' → '80'."""
    if v is None or v == "":
        return ""
    s = str(v).strip()
    m = re.match(r"^\s*(\d+)", s)
    return m.group(1) if m else s


def _parse_date(v):
    """A objeto date. Acepta DD/MM/YYYY, YYYY-MM-DD, datetime."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def parse_xlsx(content, kind="emitted"):
    """Parsea bytes XLSX y devuelve lista de dicts.

    :param content: bytes del archivo.
    :param kind: 'emitted' o 'received' — solo informativo (las columnas
        las detectamos por keywords igual).
    :return: lista de dicts con keys normalizadas (las de COLUMN_HINTS),
        más ``kind`` por conveniencia.
    """
    try:
        import openpyxl
    except ImportError as e:
        raise RuntimeError(
            "openpyxl no está instalado. pip install openpyxl"
        ) from e
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Buscar la fila de cabecera. Suele ser la primera fila con varias
    # de las palabras clave de COLUMN_HINTS.
    header_row_idx = None
    header_idx_map = None
    for i, row in enumerate(rows[:8]):
        # solo miramos las primeras 8 filas; si más allá, está mal el archivo
        idx_map = _build_header_index(row, kind=kind)
        # consideramos válida la fila si encontramos al menos 5 keys clave
        critical = {"fecha_emision", "tipo", "pto_vta", "nro_desde", "imp_total"}
        if len(set(idx_map) & critical) >= 4:
            header_row_idx = i
            header_idx_map = idx_map
            break

    if header_row_idx is None or not header_idx_map:
        raise ValueError(
            "No pude encontrar la fila de cabecera en el XLS. "
            "Asegurate que sea un export de Mis Comprobantes de ARCA."
        )

    out = []
    for row in rows[header_row_idx + 1:]:
        if row is None or all(c is None or c == "" for c in row):
            continue

        def get(key):
            i = header_idx_map.get(key)
            if i is None or i >= len(row):
                return None
            return row[i]

        rec = {
            "kind": kind,
            "fecha_emision": _parse_date(get("fecha_emision")),
            "tipo_cbte": _parse_tipo(get("tipo")),
            "pto_vta": _to_int(get("pto_vta")),
            "nro_desde": _to_int(get("nro_desde")),
            "nro_hasta": _to_int(get("nro_hasta")) or _to_int(get("nro_desde")),
            "cae": (str(get("cae") or "").strip() or False),
            "doc_tipo_partner": _parse_doc_tipo(get("doc_tipo_partner")),
            "doc_nro_partner": (re.sub(r"[^\d]", "", str(get("doc_nro_partner") or "")) or False),
            "denom_partner": (str(get("denom_partner") or "").strip() or False),
            "moneda": (str(get("moneda") or "PES").strip()[:3] or "PES"),
            "tipo_cambio": _to_dec(get("tipo_cambio")) or Decimal("1.00"),
            # Buckets per alícuota.
            "neto_iva_0":    _to_dec(get("neto_iva_0")),
            "neto_iva_2_5":  _to_dec(get("neto_iva_2_5")),
            "iva_2_5":       _to_dec(get("iva_2_5")),
            "neto_iva_5":    _to_dec(get("neto_iva_5")),
            "iva_5":         _to_dec(get("iva_5")),
            "neto_iva_10_5": _to_dec(get("neto_iva_10_5")),
            "iva_10_5":      _to_dec(get("iva_10_5")),
            "neto_iva_21":   _to_dec(get("neto_iva_21")),
            "iva_21":        _to_dec(get("iva_21")),
            "neto_iva_27":   _to_dec(get("neto_iva_27")),
            "iva_27":        _to_dec(get("iva_27")),
            "imp_neto_gravado":    _to_dec(get("imp_neto_gravado")),
            "imp_neto_no_gravado": _to_dec(get("imp_neto_no_gravado")),
            "imp_op_exentas":      _to_dec(get("imp_op_exentas")),
            "imp_otros_tributos":  _to_dec(get("imp_otros_tributos")),
            "imp_iva":             _to_dec(get("imp_iva")),
            "imp_total":           _to_dec(get("imp_total")),
        }
        if not rec["fecha_emision"] and not rec["nro_desde"]:
            # fila basura
            continue
        out.append(rec)

    return out
