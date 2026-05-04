# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Parser del padrón mensual de IIBB AGIP (CABA / Buenos Aires Ciudad).

AGIP publica el padrón mensual en su portal:

    https://www.agip.gob.ar/agentes/agentes-de-recaudacion/ib-agentes-recaudacion/padrones/

El archivo viene como `.RAR` o `.ZIP` y dentro tiene un `.TXT` con
**campos separados por punto y coma** (no longitud fija como ARBA).

Layout (RG AGIP 296/2019, modificado por RG 352/2022):

    1) Fecha publicación        DDMMAAAA
    2) Vigencia desde           DDMMAAAA
    3) Vigencia hasta           DDMMAAAA
    4) CUIT                     11 dígitos sin guiones
    5) Tipo contribuyente       L = Local · C = Convenio · N = No inscripto
    6) Marca alta/baja/modif    A = Alta · B = Baja · M = Modif · S = Sin cambios
    7) Alícuota percepción      X.XX (con 2 decimales, ej. "3,50")
    8) Alícuota retención       X.XX
    9) Grupo percepción         entero
   10) Grupo retención          entero
   11) Razón social             string

Encoding: UTF-8 (algunos meses Latin-1 — el parser detecta).
Separador: `;`. Línea: `\\r\\n` o `\\n`.

Lib pura — sin imports de Odoo. Recibe bytes, devuelve lista de dicts.
"""
import io
import logging
import zipfile
from datetime import date

_logger = logging.getLogger(__name__)


# Cantidad mínima de columnas que esperamos. AGIP a veces agrega campos
# al final (RG 352/2022 agregó razón social) — toleramos columnas
# adicionales pero validamos que estén las primeras 10.
MIN_COLS = 10


class PadronAgipParseError(Exception):
    """Error parseando el padrón AGIP — file mal formado o layout cambió."""


def parse_record(line):
    """Parsea una línea del padrón → dict normalizado.

    :param line: str con campos separados por `;`.
    :return: dict con keys cuit, fecha_pub, date_from, date_to, tipo,
        alta_baja, aliquot_perception, aliquot_retention, grupo_perception,
        grupo_retention, name.
    :raises PadronAgipParseError: si la línea no tiene la estructura esperada.
    """
    parts = line.rstrip("\r\n").split(";")
    if len(parts) < MIN_COLS:
        raise PadronAgipParseError(
            "Línea con %d columnas, esperadas al menos %d. Línea: %r"
            % (len(parts), MIN_COLS, line)
        )

    fecha_pub = _parse_date(parts[0])
    date_from = _parse_date(parts[1])
    date_to = _parse_date(parts[2])
    cuit = _normalize_cuit(parts[3])
    tipo = (parts[4] or "").strip().upper()[:1]
    alta_baja = (parts[5] or "").strip().upper()[:1]
    alic_perc = _parse_decimal(parts[6])
    alic_ret = _parse_decimal(parts[7])
    grupo_perc = _parse_int(parts[8])
    grupo_ret = _parse_int(parts[9])
    name = (parts[10].strip() if len(parts) > 10 else "")[:200]

    return {
        "cuit": cuit,
        "fecha_pub": fecha_pub,
        "date_from": date_from,
        "date_to": date_to,
        "tipo": tipo,
        "alta_baja": alta_baja,
        "aliquot_perception": alic_perc,
        "aliquot_retention": alic_ret,
        "grupo_perception": grupo_perc,
        "grupo_retention": grupo_ret,
        "name": name,
    }


def parse_bytes(content, file_name=""):
    """Parsea bytes (TXT o ZIP) → lista de dicts.

    :param content: bytes del archivo.
    :param file_name: nombre original (para detección por extensión).
    """
    name = (file_name or "").lower()
    text = None

    # Si es ZIP, extraer el primer TXT.
    if name.endswith(".zip") or content[:4] == b"PK\x03\x04":
        zf = zipfile.ZipFile(io.BytesIO(content))
        txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not txt_names:
            txt_names = zf.namelist()
        if not txt_names:
            raise PadronAgipParseError("ZIP vacío — no contiene archivos.")
        with zf.open(txt_names[0]) as f:
            text = f.read()
    else:
        text = content

    # Detectar encoding (UTF-8 con BOM, UTF-8, Latin-1).
    if text[:3] == b"\xef\xbb\xbf":
        text = text[3:]
        decoded = text.decode("utf-8", errors="replace")
    else:
        try:
            decoded = text.decode("utf-8")
        except UnicodeDecodeError:
            decoded = text.decode("latin-1", errors="replace")

    out = []
    for i, line in enumerate(decoded.splitlines()):
        if not line.strip():
            continue
        try:
            rec = parse_record(line)
        except PadronAgipParseError as e:
            _logger.warning("Línea %d ignorada: %s", i + 1, e)
            continue
        if rec.get("cuit"):
            out.append(rec)
    return out


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _parse_date(s):
    """`DDMMAAAA` → date. Acepta también AAAAMMDD por compat."""
    s = (s or "").strip()
    if not s or len(s) != 8 or not s.isdigit():
        return None
    # Heurística: si los primeros 2 dígitos están entre 19 y 21 → AAAAMMDD.
    if s[:2] in ("19", "20", "21"):
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    # Caso normal AGIP: DDMMAAAA
    try:
        return date(int(s[4:8]), int(s[2:4]), int(s[:2]))
    except ValueError:
        return None


def _parse_decimal(s):
    """'3,50' o '3.50' o '350' → float (3.50). Strip blanks."""
    s = (s or "").strip().replace(",", ".")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_int(s):
    s = (s or "").strip()
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _normalize_cuit(s):
    """11 dígitos sin guiones."""
    if not s:
        return ""
    digits = "".join(c for c in str(s) if c.isdigit())
    return digits[:11].zfill(11) if digits else ""
