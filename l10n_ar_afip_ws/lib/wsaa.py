# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Cliente WSAA (Web Service de Autenticación y Autorización) de AFIP.

El flujo de autenticación de AFIP es distinto al de un OAuth típico:

1. El cliente arma un XML `LoginTicketRequest` con una `uniqueId` (número
   aleatorio único por segundo) y un par (`generationTime`, `expirationTime`)
   que define la ventana en la que el TA va a ser válido.
2. El cliente firma ese XML con CMS/PKCS#7 usando su certificado X.509 y
   su private key correspondiente. El CMS se arma en modo *signed*, con el
   contenido embebido.
3. Se envía el CMS codificado en base64 al método `loginCms(in0)` del WSAA.
4. AFIP devuelve un `LoginTicketResponse` con:
       - <token>...</token>
       - <sign>...</sign>
       - <generationTime>, <expirationTime>.
   Esos 2 valores (token, sign) se mandan en el header SOAP `<Auth>` de cada
   llamada a los WS de negocio (wsfe, wsfex, etc.) hasta que expire el TA.

El TA expira 12 hs después de su generationTime. En la práctica cacheamos
uno por (empresa, ws, environment) y lo refrescamos cuando falta < 10 min
para expirar.

Este módulo implementa SOLO la lógica pura: construir el LoginTicketRequest,
ejecutar `loginCms`, parsear la respuesta. La firma CMS se delega a un
callable que el caller provee (porque depende de `cryptography` y del
certificate.record de Odoo — lo inyectamos como dependencia para mantener
la capa `lib/` sin acople).
"""
import logging
from datetime import datetime, timedelta, timezone

from lxml import etree

from . import errors, urls

_logger = logging.getLogger(__name__)


def _afip_local_dt(offset_minutes=0):
    """Devuelve un datetime con timezone Argentina (UTC-3) + offset.

    AFIP quiere los timestamps en ISO 8601 con timezone. Si mandás naïve
    UTC AFIP a veces rechaza el ticket con "request.expired".
    """
    tz_ar = timezone(timedelta(hours=-3))
    return datetime.now(tz_ar) + timedelta(minutes=offset_minutes)


def build_login_ticket_request(service_name, ttl_minutes=60):
    """Arma el XML `LoginTicketRequest` para un servicio.

    :param service_name: 'wsfe', 'wsfex', etc. — lo que espera AFIP en <service>.
    :param ttl_minutes: ventana entre generationTime y expirationTime.
                        AFIP rechaza si > 24h; por seguridad usamos 60m por
                        default (suficiente para un TA que igual dura 12h
                        reales una vez autenticado).
    :return: bytes con el XML serializado (sin declaración, UTF-8), listo
             para firmar con CMS.
    """
    now = _afip_local_dt()
    exp = _afip_local_dt(offset_minutes=ttl_minutes)
    # uniqueId: AFIP lo declara `xsd:unsignedInt` (32 bits, máximo
    # 4.294.967.295). Un epoch en segundos (≈1.7e9 a 2026) cabe; si
    # multiplicás por 1000 para darle resolución de ms desbordás uint32
    # y el server rechaza el request con "XML contra SCHEMA".
    #
    # La unicidad *por segundo* queda cubierta por el cache de
    # `l10n_ar.afip.ws.connection`: sólo pedimos un TA nuevo si el
    # vigente expiró, nunca dos en el mismo segundo.
    unique_id = int(now.timestamp())

    def _iso(dt):
        # `strftime('%z')` devuelve `-0300` sin los dos puntos, y el
        # fromisoformat de Python <3.11 no lo parsea. Normalizamos a
        # `-03:00` — formato RFC 3339 que acepta todo Python y AFIP.
        base = dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        if len(base) >= 5 and base[-5] in ("+", "-"):
            base = base[:-2] + ":" + base[-2:]
        return base

    root = etree.Element("loginTicketRequest", version="1.0")
    header = etree.SubElement(root, "header")
    etree.SubElement(header, "uniqueId").text = str(unique_id)
    etree.SubElement(header, "generationTime").text = _iso(now)
    etree.SubElement(header, "expirationTime").text = _iso(exp)
    etree.SubElement(root, "service").text = service_name
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def parse_login_ticket_response(xml_bytes):
    """Parsea el `LoginTicketResponse` de AFIP.

    :param xml_bytes: bytes del XML devuelto por WSAA.
    :return: dict con keys:
        - token (str): el Base64 del TA.
        - sign (str): la firma Base64 del TA.
        - generation_time (datetime): UTC naïve.
        - expiration_time (datetime): UTC naïve.
        - source_cuit (str): CUIT del emisor del TA (viene en <source>).
    :raises WsaaError: si el XML no tiene la estructura esperada.
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        raise errors.WsaaError(
            code="parse.invalid",
            message="WSAA devolvió XML inválido: %s" % e,
        )

    def _text(xpath):
        found = root.find(xpath)
        if found is None or found.text is None:
            raise errors.WsaaError(
                code="parse.missing",
                message="Falta el elemento %r en LoginTicketResponse" % xpath,
            )
        return found.text.strip()

    # los timestamps vienen como "2026-04-23T10:00:00.000-03:00"
    def _parse_dt(value):
        # fromisoformat en 3.11+ parsea con timezone. Normalizamos a UTC
        # naïve porque ORM de Odoo guarda sin tz.
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    return {
        "token": _text("credentials/token"),
        "sign": _text("credentials/sign"),
        "generation_time": _parse_dt(_text("header/generationTime")),
        "expiration_time": _parse_dt(_text("header/expirationTime")),
        "source_cuit": _text("header/source") if root.find("header/source") is not None else None,
    }


def login_cms(cms_bytes, environment, transport):
    """Llama al método `loginCms` del WSAA.

    :param cms_bytes: la firma PKCS#7 DER del LoginTicketRequest.
    :param environment: 'testing' o 'production'.
    :param transport: una instancia de `zeep.transports.Transport`
                      (preferentemente `CapturingTransport`).
    :return: el XML crudo del LoginTicketResponse (bytes).
    :raises WsaaError: si WSAA devuelve un SOAP Fault conocido.
    :raises TransportError: si hay un error de red/SSL antes del fault.
    """
    import base64

    import zeep
    from zeep.exceptions import Fault, TransportError as ZeepTransportError

    wsdl = urls.get_wsdl_url("wsaa", environment)
    try:
        client = zeep.Client(wsdl=wsdl, transport=transport)
    except ZeepTransportError as e:
        raise errors.TransportError(
            message="No pude traer el WSDL de WSAA (%s): %s" % (wsdl, e),
            hint="Verificá conectividad y que la URL sea la del entorno correcto.",
        )

    cms_b64 = base64.b64encode(cms_bytes).decode("ascii")
    try:
        response = client.service.loginCms(in0=cms_b64)
    except Fault as fault:
        # AFIP mapea los errores funcionales a SOAP Fault con strings como
        # "coe.alreadyAuthenticated", "signature.invalid", etc.
        code = fault.message.split(":")[0].strip() if fault.message else "unknown"
        desc, hint = errors.get_wsaa_hint(code)
        raise errors.WsaaError(
            code=code,
            message=fault.message or str(fault),
            hint=hint,
        )
    except ZeepTransportError as e:
        raise errors.TransportError(
            message="Error de transporte contra WSAA: %s" % e,
        )

    # `response` es el XML del LoginTicketResponse — zeep puede devolverlo
    # como str o como bytes dependiendo de la versión. Normalizamos.
    if isinstance(response, str):
        return response.encode("utf-8")
    return response


def get_ticket(service_name, environment, sign_cms, transport):
    """Flujo completo: arma LTR, lo firma, llama a WSAA, parsea la respuesta.

    :param service_name: el WS al que voy a autenticar contra ('wsfe', etc.)
    :param environment: 'testing' o 'production'.
    :param sign_cms: callable ``(xml_bytes) -> cms_der_bytes`` que firma con
                     el cert correspondiente. Se inyecta para no acoplar esta
                     capa a Odoo / al módulo `certificate`.
    :param transport: transport SOAP (ver `transport.CapturingTransport`).
    :return: dict igual al de `parse_login_ticket_response` + 'service'.
    """
    ltr_xml = build_login_ticket_request(service_name)
    _logger.debug("LoginTicketRequest para %s:\n%s", service_name, ltr_xml.decode())
    cms = sign_cms(ltr_xml)
    response_xml = login_cms(cms, environment, transport)
    parsed = parse_login_ticket_response(response_xml)
    parsed["service"] = service_name
    return parsed
