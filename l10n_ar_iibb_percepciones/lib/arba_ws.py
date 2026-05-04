# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Cliente del web service ARBA — descarga del padrón de regímenes
generales por sujeto.

Spec: https://www.arba.gov.ar (DFE — Domicilio Fiscal Electrónico)
Endpoints:

  prod: https://dfe.arba.gov.ar/DomicilioElectronico/SeguridadCliente/dfeServicioDescargaPadron.do
  test: https://dfe.test.arba.gov.ar/DomicilioElectronico/SeguridadCliente/dfeServicioDescargaPadron.do

Flujo:
  1. Build XML `<DESCARGA-PADRON>` con `fechaDesde` y `fechaHasta`
     (formato AAAAMMDD, encoding ISO-8859-1).
  2. Calcular MD5 del XML → genera el filename
     `DFEServicioDescargaPadron_<md5>.xml`.
  3. POST multipart/form-data al endpoint con campos
     ``user`` + ``password`` + ``file``.
  4. Si la transacción es exitosa, ARBA devuelve un ZIP con el padrón.
     Si falla, devuelve un XML `<ERROR>` con tipo + código + mensaje.

Errores ARBA (RG documentados):
  01: Inesperado (RETRY)
  02: User/password inválidos (FATAL)
  03: Usuario no habilitado (FATAL)
  04: Usuario bloqueado (FATAL)
  05: Falta user o password (FATAL — bug nuestro)
  06: Nombre archivo incorrecto (FATAL — bug nuestro)
  07: Formato XML inválido (FATAL — bug nuestro)
  08: fechaDesde inválido (FATAL — bug nuestro)
  09: fechaHasta inválido (FATAL — bug nuestro)
  10: Falta el parámetro file (FATAL — bug nuestro)
  11: Canal inseguro (FATAL — usar HTTPS)
  12: Multipart incorrecto (FATAL — bug nuestro)
  13: Extensión inválida (FATAL — bug nuestro)
  14: Error de integridad (FATAL — MD5 no matchea)

Lib pura — no importa ``odoo.``. Recibe credenciales + fechas, devuelve
bytes del ZIP. Levanta excepciones tipadas.
"""
import hashlib
import logging
from io import BytesIO
from xml.etree import ElementTree as ET

_logger = logging.getLogger(__name__)

URL_PROD = "https://dfe.arba.gov.ar/DomicilioElectronico/SeguridadCliente/dfeServicioDescargaPadron.do"
URL_TEST = "https://dfe.test.arba.gov.ar/DomicilioElectronico/SeguridadCliente/dfeServicioDescargaPadron.do"

# Códigos de error que requieren intervención humana (NO reintentar).
FATAL_CODES = {"02", "03", "04", "05", "06", "07", "08", "09", "10",
               "11", "12", "13", "14"}


class ArbaWsError(Exception):
    """Error reportado por ARBA en el XML de respuesta.

    Atributos:
      code: str con el código (01-14).
      tipo: 'DATO' o 'INESPERADO'.
      message: mensaje descriptivo de ARBA.
      is_fatal: True si NO se debe reintentar.
    """
    def __init__(self, code, tipo, message):
        self.code = str(code or "")
        self.tipo = (tipo or "").upper()
        self.message = message or ""
        self.is_fatal = self.code in FATAL_CODES
        super().__init__("ARBA [%s] %s: %s" % (self.code, self.tipo, self.message))


class ArbaWsTransportError(Exception):
    """Error de transporte (red, DNS, timeout, HTTP no-200).

    Es siempre RETRY-able — el siguiente cron lo reintenta.
    """
    pass


def build_request_xml(fecha_desde, fecha_hasta):
    """Arma el XML de request en formato ISO-8859-1.

    :param fecha_desde: str AAAAMMDD o objeto date.
    :param fecha_hasta: str AAAAMMDD o objeto date.
    :return: bytes del XML codificado en ISO-8859-1.
    """
    fd = _format_date(fecha_desde)
    fh = _format_date(fecha_hasta)
    body = (
        '<?xml version="1.0" encoding="ISO-8859-1" ?>\n'
        '<DESCARGA-PADRON>\n'
        '\t<fechaDesde>%s</fechaDesde>\n'
        '\t<fechaHasta>%s</fechaHasta>\n'
        '</DESCARGA-PADRON>\n'
    ) % (fd, fh)
    return body.encode("iso-8859-1")


def make_filename(xml_bytes):
    """Calcula el filename con hash MD5 del contenido."""
    md5 = hashlib.md5(xml_bytes).hexdigest()
    return "DFEServicioDescargaPadron_%s.xml" % md5


def download_padron(user, password, fecha_desde, fecha_hasta,
                    environment="production", timeout=45):
    """Descarga el padrón ARBA para un rango de fechas.

    :param user: usuario ARBA del DFE.
    :param password: password.
    :param fecha_desde: str AAAAMMDD o date.
    :param fecha_hasta: str AAAAMMDD o date.
    :param environment: 'production' o 'testing'.
    :param timeout: segundos.
    :return: dict {
        'success': True,
        'zip_bytes': bytes del ZIP,
        'filename': nombre devuelto por ARBA,
        'request_xml': bytes del XML enviado (para log),
    }
    :raises ArbaWsError: si ARBA devuelve XML de error.
    :raises ArbaWsTransportError: si hay problema de red/HTTP.
    """
    try:
        import requests
    except ImportError as e:
        raise ArbaWsTransportError("requests no instalado: %s" % e)

    url = URL_PROD if environment == "production" else URL_TEST
    xml_body = build_request_xml(fecha_desde, fecha_hasta)
    filename = make_filename(xml_body)

    files = {"file": (filename, xml_body, "text/xml")}
    data = {"user": user or "", "password": password or ""}

    try:
        r = requests.post(url, files=files, data=data, timeout=timeout, verify=True)
    except requests.exceptions.RequestException as e:
        raise ArbaWsTransportError("HTTP request falló: %s" % e)

    if r.status_code != 200:
        raise ArbaWsTransportError(
            "HTTP %s — body[:200]: %r" % (r.status_code, r.content[:200])
        )

    body = r.content
    # Detectar respuesta: ZIP empieza con b'PK\x03\x04', XML con b'<?xml' o b'<ERROR'.
    if body[:4] == b"PK\x03\x04":
        # Éxito — ZIP. Filename viene en Content-Disposition (opcional).
        cd = r.headers.get("Content-Disposition", "")
        zip_filename = "padron_arba.zip"
        if "filename=" in cd:
            zip_filename = cd.split("filename=")[-1].strip().strip('"').strip("'")
        return {
            "success": True,
            "zip_bytes": body,
            "filename": zip_filename,
            "request_xml": xml_body,
        }

    # No es ZIP → asumimos XML de error.
    error = _parse_error_xml(body)
    if error:
        raise ArbaWsError(
            code=error.get("codigoError"),
            tipo=error.get("tipoError"),
            message=error.get("mensajeError"),
        )
    # No es ZIP ni XML reconocible.
    raise ArbaWsTransportError(
        "Respuesta no esperada (no es ZIP ni XML <ERROR>): %r" % body[:200]
    )


def _parse_error_xml(body):
    """Parsea ``<ERROR>`` o ``<DFEError>`` → dict.

    Notar: la spec PDF de ARBA dice ``<ERROR>`` pero el server real
    en prod responde ``<DFEError>`` (verificado 2026-05-04). Aceptamos
    ambos para robustez.

    Devuelve None si el XML no es un error reconocible.
    """
    try:
        # ARBA puede responder en ISO-8859-1 o UTF-8.
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = body.decode("iso-8859-1", errors="replace")
        root = ET.fromstring(text)
        # Aceptar tag ERROR, DFEError, o cualquiera que termine en "Error".
        tag_upper = root.tag.upper()
        if not (tag_upper == "ERROR" or tag_upper.endswith("ERROR")):
            return None
        return {
            "tipoError": (root.findtext("tipoError") or "").strip(),
            "codigoError": (root.findtext("codigoError") or "").strip(),
            "mensajeError": (root.findtext("mensajeError") or "").strip(),
        }
    except (ET.ParseError, UnicodeDecodeError):
        return None


def _format_date(d):
    """date / datetime / 'AAAAMMDD' / 'YYYY-MM-DD' → 'AAAAMMDD'."""
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return s
    if len(s) == 10 and s[4] == "-":
        return s[:4] + s[5:7] + s[8:10]
    raise ValueError("Formato de fecha no reconocido: %r" % d)
