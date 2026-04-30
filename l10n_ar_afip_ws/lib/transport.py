# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Transport HTTP/SOAP para los WS de AFIP.

Dos piezas:

1. `AfipHTTPAdapter`: subclase de `requests.adapters.HTTPAdapter` que fuerza
   ciphers sin Diffie-Hellman. AFIP históricamente tuvo un bug de handshake
   TLS cuando el cliente ofrece DH — una OpenSSL moderna con Debian/Ubuntu
   negociaría un cipher DHE que AFIP no maneja bien y el request se cuelga
   o rompe con "dh key too small". Forzando `DEFAULT:!DH` lo evitamos sin
   bajar la seguridad por debajo de TLSv1.2.

2. `CapturingTransport`: wrapper sobre `zeep.transports.Transport` que
   guarda en memoria el último XML request y response. Lo vamos a usar
   para persistir los XML en `account.move` (campos `l10n_ar_afip_xml_*`)
   y así poder auditar y debuggear sin re-ejecutar el WS.

No tiene imports de Odoo — es código puro para poder testear sin server.
"""
import logging

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

try:
    from zeep.transports import Transport
except ImportError:
    # zeep se declara en external_dependencies del manifest; si no está
    # instalado el módulo no carga, pero para tests unitarios de otras
    # piezas del paquete no queremos romper el import.
    Transport = None

_logger = logging.getLogger(__name__)

#: Ciphers que funcionan con AFIP. Explícitamente excluye suites DH que
#: rompen el handshake contra los servers viejos de AFIP.
AFIP_CIPHERS = "DEFAULT:!DH"


class AfipHTTPAdapter(HTTPAdapter):
    """Adapter de requests con ciphers compatibles con AFIP."""

    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=AFIP_CIPHERS)
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=AFIP_CIPHERS)
        kwargs["ssl_context"] = context
        return super().proxy_manager_for(*args, **kwargs)


def build_afip_session():
    """Crea un `requests.Session` con el adapter de AFIP montado en https://."""
    session = Session()
    session.mount("https://", AfipHTTPAdapter())
    return session


class CapturingTransport(Transport if Transport else object):
    """Transport de zeep que captura el último request/response en crudo.

    Uso típico:
        t = CapturingTransport(session=build_afip_session(), timeout=30)
        client = zeep.Client(wsdl=url, transport=t)
        result = client.service.FECAESolicitar(...)
        # luego:
        xml_request = t.last_request
        xml_response = t.last_response

    No es thread-safe: cada hilo/company debería instanciar su propio
    transport. En la práctica vamos a crear uno por llamada al WS.
    """

    def __init__(self, *args, **kwargs):
        if Transport is None:
            raise ImportError(
                "zeep no está instalado — instalá python3-zeep (Debian/Ubuntu) "
                "o `pip install zeep`"
            )
        super().__init__(*args, **kwargs)
        self.last_request = None
        self.last_response = None

    def post(self, address, message, headers):
        self.last_request = message
        response = super().post(address, message, headers)
        try:
            self.last_response = response.content
        except Exception:  # pragma: no cover - defensivo
            self.last_response = None
        return response

    def post_xml(self, address, envelope, headers):
        # zeep 4.x llama a post_xml en lugar de post cuando serializa desde
        # un etree. Capturamos en ambos métodos.
        from lxml import etree

        try:
            self.last_request = etree.tostring(envelope, pretty_print=True)
        except Exception:  # pragma: no cover
            self.last_request = None
        response = super().post_xml(address, envelope, headers)
        try:
            self.last_response = response.content
        except Exception:  # pragma: no cover
            self.last_response = None
        return response
