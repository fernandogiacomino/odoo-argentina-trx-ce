# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Parser del padrón mensual de IIBB ARBA (Buenos Aires).

ARBA publica mensualmente un ZIP con el padrón de alícuotas. El portal
oficial es:

    https://lpd.arba.gov.ar/PadronesWeb/PadronContribuyentesIIBB/Descarga.aspx

El ZIP contiene un archivo TXT plano de longitud fija, un registro por
contribuyente. Layout vigente (ARBA RG 64/2010 y modificatorias):

    posición  longitud  campo
    --------  --------  ----------------------------------
    1-8       8         Fecha publicación (AAAAMMDD)
    9-16      8         Vigencia desde (AAAAMMDD)
    17-24     8         Vigencia hasta (AAAAMMDD)
    25-35     11        CUIT (sin guiones, padding ceros)
    36        1         Tipo (0=Bajo riesgo, 1=Alto riesgo)
    37        1         Marca alta/baja (A=alta, B=baja, S=sin cambios)
    38-42     5         Alícuota percepción × 100 (3.00% → "00300")
    43-47     5         Alícuota retención × 100
    48        1         Grupo percepción
    49        1         Grupo retención

Total: **49 chars** por registro. Encoding ASCII / Latin-1, separador
``\\r\\n``. Lib pura (sin Odoo) — testeable aislado.
"""
import io
import zipfile
from datetime import date


RECORD_LENGTH = 49


class PadronArbaParseError(Exception):
    """Error parseando el padrón ARBA — file mal formado o layout cambió."""


def parse_record(line):
    """Parsea una línea del padrón → dict normalizado.

    :param line: str de longitud RECORD_LENGTH (sin CRLF).
    :return: dict con keys cuit, fecha_pub, date_from, date_to,
        tipo, alta_baja, aliquot_perception, aliquot_retention,
        grupo_perception, grupo_retention.
    :raises PadronArbaParseError: si la línea no tiene la longitud esperada.
    """
    if len(line) != RECORD_LENGTH:
        raise PadronArbaParseError(
            "Registro con longitud %d, esperado %d. Línea: %r"
            % (len(line), RECORD_LENGTH, line)
        )

    fecha_pub = _parse_date(line[0:8])
    date_from = _parse_date(line[8:16])
    date_to = _parse_date(line[16:24])
    cuit = line[24:35].strip()
    tipo = line[35:36].strip()
    alta_baja = line[36:37].strip()
    aliquot_perception = _parse_aliquota(line[37:42])
    aliquot_retention = _parse_aliquota(line[42:47])
    grupo_perception = line[47:48].strip()
    grupo_retention = line[48:49].strip()

    return {
        "cuit": cuit,
        "fecha_pub": fecha_pub,
        "date_from": date_from,
        "date_to": date_to,
        "tipo": tipo,
        "alta_baja": alta_baja,
        "aliquot_perception": aliquot_perception,
        "aliquot_retention": aliquot_retention,
        "grupo_perception": grupo_perception,
        "grupo_retention": grupo_retention,
    }


def parse_lines(text):
    """Itera el contenido del TXT y devuelve un generator de dicts.

    :param text: contenido completo del TXT (str). Aceptamos ``\\r\\n``,
        ``\\n`` y ``\\r`` como separadores.
    :yield: dicts del formato de :func:`parse_record`.
    """
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw:
            continue
        yield parse_record(raw)


def parse_zip(zip_bytes):
    """Extrae el TXT del ZIP de ARBA y lo parsea.

    :param zip_bytes: contenido binario del ZIP descargado de ARBA.
    :return: tuple (filename_in_zip, list_of_records).
    :raises PadronArbaParseError: si el ZIP está vacío o tiene >1 archivo
        no-TXT.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise PadronArbaParseError("ZIP inválido: %s" % e)
    txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
    if not txt_names:
        raise PadronArbaParseError(
            "El ZIP no contiene ningún .txt. Archivos: %s" % zf.namelist()
        )
    fname = txt_names[0]
    raw_bytes = zf.read(fname)
    # ARBA usa Latin-1 históricamente; UTF-8 en versiones nuevas. Probamos
    # primero Latin-1 con replace para no fallar.
    try:
        text = raw_bytes.decode("latin-1")
    except UnicodeDecodeError:
        text = raw_bytes.decode("utf-8", errors="replace")
    records = list(parse_lines(text))
    return fname, records


def parse_txt(txt_bytes):
    """Parsea un TXT plano (no ZIP) y devuelve la lista de records.

    Útil cuando el cliente sube el TXT ya descomprimido.
    """
    try:
        text = txt_bytes.decode("latin-1")
    except UnicodeDecodeError:
        text = txt_bytes.decode("utf-8", errors="replace")
    return list(parse_lines(text))


# ----------------------------------------------------------------------
# Helpers internos
# ----------------------------------------------------------------------
def _parse_date(s):
    """'20260401' → date(2026, 4, 1). '00000000' / blanco → None."""
    s = s.strip()
    if not s or s == "00000000" or len(s) != 8:
        return None
    try:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None


def _parse_aliquota(s):
    """'00300' → 3.00 (float).

    Convención ARBA: 5 dígitos con 2 decimales implícitos. ``'00050'``
    es 0.50%, ``'10000'`` es 100% (caso teórico).

    Devuelve 0.0 si la cadena no es numérica (registro de baja).
    """
    s = s.strip()
    if not s or not s.isdigit():
        return 0.0
    return int(s) / 100.0
