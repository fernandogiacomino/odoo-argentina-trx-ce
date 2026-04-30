# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Helpers de formatting para los TXT del Libro IVA Digital RG 5616.

Spec resumida (de la doc oficial AFIP + repo de referencia
`nimarosa/afip_libro_iva`):

- **Encoding**: ISO-8859-1 (Latin-1). Sin acentos en denominación.
- **Separador de líneas**: ``\\r\\n``.
- **Importes**: longitud fija, 2 decimales **implícitos sin coma ni punto**
  (ej. 1234.56 con length=15 → ``"000000000123456"``). Padding ceros a la
  izquierda. Negativos con signo dentro del padding (``-`` ocupa 1 char).
- **Cotización**: longitud 10, 6 decimales implícitos.
- **Alícuota IVA**: longitud 4, 2 decimales implícitos (21% → ``"2100"``).
- **Fechas**: ``YYYYMMDD``.
- **Texto**: alfanumérico, padding **espacios a la derecha**, truncado a la
  longitud declarada.

Estas funciones son puras (sin Odoo) — testeables aislado.
"""
from decimal import Decimal, ROUND_HALF_UP


def fmt_int(value, length):
    """Entero con padding de ceros a la izquierda."""
    if value is None:
        value = 0
    return str(int(value)).rjust(length, "0")


def fmt_amount(value, length=15, decimals=2):
    """Importe con N decimales implícitos, sin separador, padding ceros izq.

    >>> fmt_amount(1234.56, length=15, decimals=2)
    '000000000123456'
    >>> fmt_amount(-100.5, length=15, decimals=2)
    '-00000000010050'
    >>> fmt_amount(0, length=15, decimals=2)
    '000000000000000'
    >>> fmt_amount(1.234567, length=10, decimals=6)
    '0001234567'
    """
    if value is None:
        value = 0
    # Decimal con redondeo predecible (HALF_UP que es el de AFIP).
    factor = Decimal(10) ** decimals
    quantized = (Decimal(str(value)) * factor).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    n = int(quantized)
    if n < 0:
        # signo `-` consume 1 char del padding total.
        return "-" + str(-n).rjust(length - 1, "0")
    return str(n).rjust(length, "0")


def fmt_alicuota(percent, length=4, decimals=2):
    """Alícuota IVA: 21% → '2100', 10.5% → '1050', 0% → '0000'."""
    return fmt_amount(percent, length=length, decimals=decimals)


def fmt_cotizacion(rate, length=10, decimals=6):
    """Cotización 1 USD = 1399.5 ARS → '0001399500000'.

    >>> fmt_cotizacion(1399.5)
    '1399500000'
    >>> fmt_cotizacion(1.0)
    '0001000000'
    """
    return fmt_amount(rate, length=length, decimals=decimals)


def fmt_date(d):
    """Fecha YYYYMMDD. Acepta ``date`` o ``str``. Devuelve ``'00000000'`` si
    el valor no es válido — AFIP acepta ese sentinel para "sin fecha"."""
    if d is None:
        return "00000000"
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d).replace("-", "").replace("/", "")
    if len(s) == 8 and s.isdigit():
        return s
    return "00000000"


def fmt_text(value, length, fill=" ", side="right"):
    """Texto con padding a la derecha (espacios) y truncado.

    Encoding ISO-8859-1: las funciones trabajan con str de Python; la
    encodeación a bytes la hace `compose_record()`. Aquí solo limpiamos
    los chars que Latin-1 no soporta (ej. emojis) reemplazándolos por '?'.

    >>> fmt_text("PROVEEDOR S.A.", 30)
    'PROVEEDOR S.A.                '
    >>> fmt_text("MUY LARGO " * 10, 20)
    'MUY LARGO MUY LARGO '
    """
    if value is None:
        value = ""
    s = str(value)
    # Reemplazo no-latin1 por '?' antes de truncar.
    try:
        s.encode("latin-1")
    except UnicodeEncodeError:
        s = s.encode("latin-1", "replace").decode("latin-1")
    if side == "right":
        return s.ljust(length, fill)[:length]
    return s.rjust(length, fill)[:length]


def fmt_cuit(value, length=20):
    """CUIT/CUIL/DNI: solo dígitos, padding ceros izq, truncado a length.

    Útil para campos como `nro_doc` (20 chars) y `cuit_emisor_corredor` (11).

    >>> fmt_cuit("20-21946410-0", length=11)
    '20219464100'
    >>> fmt_cuit("", length=20)
    '00000000000000000000'
    """
    if value is None:
        value = ""
    digits = "".join(c for c in str(value) if c.isdigit())
    return digits.rjust(length, "0")[:length]


def compose_record(fields, encoding="latin-1"):
    """Concatena una lista de strings ya formateados y devuelve bytes.

    `fields` debe ser una lista en el orden de la spec. Cada elemento
    ya viene con su longitud fija. Esta función:
    1. Concatena.
    2. Encodea a Latin-1 (con replace para chars no soportados).

    No agrega ``\\r\\n`` — eso lo hace el caller cuando junta líneas.
    """
    return "".join(fields).encode(encoding, errors="replace")


def join_records(records, line_separator=b"\r\n"):
    """Une registros (bytes) con CRLF y agrega CRLF al final.

    AFIP acepta ambas variantes (con/sin trailing CRLF). Por convención
    de los TXT existentes (gem nimarosa, fixtures enterprise) cerramos
    con CRLF.
    """
    return line_separator.join(records) + (line_separator if records else b"")
