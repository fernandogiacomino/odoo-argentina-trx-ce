# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Parser del padrón mensual de IIBB API (Santa Fe / PARP).

API = Administración Provincial de Impuestos de Santa Fe. Publica
mensualmente el Padrón de Agentes de Retención y Percepción (PARP).

Portal: https://www.santafe.gov.ar/index.php/tramites/modul1/index?m=descripcion&id=237757

Layout (RG API 14/2025, Anexo I):

    1) Fecha publicación        DDMMAAAA
    2) Vigencia desde           DDMMAAAA
    3) Vigencia hasta           DDMMAAAA
    4) CUIT                     11 dígitos sin guiones
    5) Tipo contribuyente       C = Local · D = Convenio Multilateral
    6) Marca alta/baja          S = Sin cambios · B = Baja
    7) Marca alícuota           S = Mismo grupo · N = Cambió grupo
    8) Alícuota percepción      X.XX
    9) Alícuota retención       X.XX
   10) Grupo percepción         entero (1-23)
   11) Grupo retención          entero (1-23)

Encoding: Latin-1 (ISO-8859-1). Separador: típicamente `;`.
Periodicidad mensual.

Lib pura — sin imports de Odoo.
"""
import io
import logging
import zipfile
from datetime import date

_logger = logging.getLogger(__name__)

MIN_COLS = 10


class PadronSantaFeParseError(Exception):
    pass


def parse_record(line):
    parts = line.rstrip("\r\n").split(";")
    if len(parts) < MIN_COLS:
        raise PadronSantaFeParseError(
            "Línea con %d columnas, esperadas al menos %d. Línea: %r"
            % (len(parts), MIN_COLS, line)
        )

    fecha_pub = _parse_date(parts[0])
    date_from = _parse_date(parts[1])
    date_to = _parse_date(parts[2])
    cuit = _normalize_cuit(parts[3])
    tipo = (parts[4] or "").strip().upper()[:1]
    alta_baja = (parts[5] or "").strip().upper()[:1]
    marca_alic = (parts[6] or "").strip().upper()[:1]
    alic_perc = _parse_decimal(parts[7])
    alic_ret = _parse_decimal(parts[8])
    grupo_perc = _parse_int(parts[9])
    grupo_ret = _parse_int(parts[10]) if len(parts) > 10 else 0

    return {
        "cuit": cuit,
        "fecha_pub": fecha_pub,
        "date_from": date_from,
        "date_to": date_to,
        "tipo": tipo,
        "alta_baja": alta_baja,
        "marca_alic": marca_alic,
        "aliquot_perception": alic_perc,
        "aliquot_retention": alic_ret,
        "grupo_perception": grupo_perc,
        "grupo_retention": grupo_ret,
        "name": "",
    }


def parse_bytes(content, file_name=""):
    name = (file_name or "").lower()
    if name.endswith(".zip") or content[:4] == b"PK\x03\x04":
        zf = zipfile.ZipFile(io.BytesIO(content))
        txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not txt_names:
            txt_names = zf.namelist()
        if not txt_names:
            raise PadronSantaFeParseError("ZIP vacío.")
        with zf.open(txt_names[0]) as f:
            text = f.read()
    else:
        text = content

    if text[:3] == b"\xef\xbb\xbf":
        text = text[3:]
        decoded = text.decode("utf-8", errors="replace")
    else:
        try:
            decoded = text.decode("latin-1")
        except UnicodeDecodeError:
            decoded = text.decode("utf-8", errors="replace")

    out = []
    for i, line in enumerate(decoded.splitlines()):
        if not line.strip():
            continue
        try:
            rec = parse_record(line)
        except PadronSantaFeParseError as e:
            _logger.warning("Línea %d ignorada: %s", i + 1, e)
            continue
        if rec.get("cuit"):
            out.append(rec)
    return out


def _parse_date(s):
    s = (s or "").strip()
    if not s or len(s) != 8 or not s.isdigit():
        return None
    if s[:2] in ("19", "20", "21"):
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    try:
        return date(int(s[4:8]), int(s[2:4]), int(s[:2]))
    except ValueError:
        return None


def _parse_decimal(s):
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
    if not s:
        return ""
    digits = "".join(c for c in str(s) if c.isdigit())
    return digits[:11].zfill(11) if digits else ""
