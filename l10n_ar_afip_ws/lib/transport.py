# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Transport HTTP/SOAP para los WS de AFIP.

Cuatro piezas:

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

3. **Caché de WSDL en disco** (incidente real en producción, 11/08/2026):
   zeep baja el WSDL (y sus XSD) en *cada* construcción de `zeep.Client`.
   Con AFIP degradado eso fue un `ReadTimeout` de 60 s **antes** de siquiera
   intentar el `FECAESolicitar`, y después un `503` del propio WSDL. Como el
   worker HTTP de Odoo se muere a los `limit_time_real` segundos, esa espera
   se comió el presupuesto y el worker murió *después* de que AFIP ya había
   otorgado el CAE → rollback, CAE huérfano y numeración trabada.

   Los WSDL de AFIP no cambian de un día para el otro: cachearlos saca la
   descarga del camino crítico de la facturación. Usamos `zeep.cache.SqliteCache`,
   que guarda por URL con TTL y es seguro entre workers (sqlite maneja el
   locking). Si AFIP no responde pero el WSDL está en caché, **se factura igual**.

4. **Timeouts separados**: `load_timeout` para bajar WSDL/XSD y
   `operation_timeout` para la llamada SOAP. Antes era un solo valor y el
   peor caso era 2x. Ahora el techo de una emisión es acotado y predecible.

No tiene imports de Odoo — es código puro para poder testear sin server.
"""
import logging
import os
import tempfile
import threading

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

try:
    from zeep.cache import SqliteCache
except ImportError:  # pragma: no cover - zeep siempre trae cache
    SqliteCache = None

_logger = logging.getLogger(__name__)

#: Ciphers que funcionan con AFIP. Explícitamente excluye suites DH que
#: rompen el handshake contra los servers viejos de AFIP.
AFIP_CIPHERS = "DEFAULT:!DH"

#: Segundos para bajar el WSDL/XSD. Con caché tibia esto no se usa nunca;
#: solo pega en el primer arranque o cuando vence el TTL.
DEFAULT_LOAD_TIMEOUT = 15

#: Segundos para la operación SOAP en sí (FECAESolicitar y amigos).
DEFAULT_OPERATION_TIMEOUT = 60

#: TTL de la caché de WSDL. Una semana: los WSDL de AFIP son estables y si
#: cambian, el refresco lo fuerza el cron de warmup o un restart.
DEFAULT_WSDL_CACHE_TTL = 7 * 24 * 3600

#: Nombre del archivo sqlite de caché dentro del data dir.
WSDL_CACHE_FILENAME = "afip_wsdl_cache.db"

_cache_lock = threading.Lock()
_shared_cache = None
_shared_cache_path = None


def get_wsdl_cache_path(data_dir=None):
    """Devuelve la ruta del sqlite de caché de WSDL.

    `data_dir` lo pasa la capa Odoo (`odoo.tools.config['data_dir']`). Si no
    viene, caemos al tempdir — sigue sirviendo dentro de la vida del
    contenedor, que es lo que importa para el camino crítico.
    """
    base = data_dir or os.environ.get("ODOO_DATA_DIR")
    if not base:
        # Sin esto caiamos al tempdir y cada contexto (worker, cron, shell,
        # wizard) abria SU PROPIA cache: el camino de emision cacheaba bien
        # porque le pasan el data_dir, y el resto salia a la red igual.
        try:
            from odoo.tools import config as _odoo_config

            base = _odoo_config.get("data_dir")
        except Exception:  # noqa: BLE001 - la lib tiene que poder usarse sin Odoo
            base = None
    if not base:
        base = tempfile.gettempdir()
    return os.path.join(base, WSDL_CACHE_FILENAME)


def get_wsdl_cache(data_dir=None, ttl=DEFAULT_WSDL_CACHE_TTL):
    """Caché de WSDL compartida por proceso (una por worker de Odoo).

    Devuelve `None` si zeep no expone `SqliteCache` o si no podemos escribir
    el archivo — en ese caso el comportamiento es el de antes (bajar el WSDL
    en cada llamada), degradado pero funcional. Nunca levanta.
    """
    global _shared_cache, _shared_cache_path
    if SqliteCache is None:
        return None
    path = get_wsdl_cache_path(data_dir)
    with _cache_lock:
        if _shared_cache is not None and _shared_cache_path == path:
            return _shared_cache
        try:
            cache = SqliteCache(path=path, timeout=ttl)
        except Exception as e:  # pragma: no cover - defensivo
            _logger.warning(
                "AFIP: no pude abrir la cache de WSDL en %s (%s) — "
                "sigo sin cache, cada llamada va a bajar el WSDL.", path, e,
            )
            return None
        _shared_cache = cache
        _shared_cache_path = path
        _logger.info("AFIP: cache de WSDL en %s (ttl %ss)", path, ttl)
        return cache


def build_afip_session():
    """Crea un `requests.Session` con el adapter de AFIP montado en https://."""
    session = Session()
    session.mount("https://", AfipHTTPAdapter())
    return session


def build_transport(load_timeout=None, operation_timeout=None,
                    data_dir=None, cache_ttl=DEFAULT_WSDL_CACHE_TTL,
                    use_cache=True):
    """Constructor único de `CapturingTransport` para todos los WS de AFIP.

    Es el punto por el que pasa toda la facturación electrónica: si hay que
    tocar timeouts o caché, se toca acá y no en cada llamador.
    """
    cache = get_wsdl_cache(data_dir=data_dir, ttl=cache_ttl) if use_cache else None
    return CapturingTransport(
        session=build_afip_session(),
        cache=cache,
        timeout=load_timeout or DEFAULT_LOAD_TIMEOUT,
        operation_timeout=operation_timeout or DEFAULT_OPERATION_TIMEOUT,
    )


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


class CapturingTransport(Transport if Transport else object):
    """Transport de zeep que captura el último request/response en crudo.

    Uso típico (preferí `build_transport()` en vez de instanciar a mano):
        t = build_transport()
        client = zeep.Client(wsdl=url, transport=t)
        result = client.service.FECAESolicitar(...)
        # luego:
        xml_request = t.last_request
        xml_response = t.last_response

    No es thread-safe: cada hilo/company debería instanciar su propio
    transport. En la práctica vamos a crear uno por llamada al WS. La caché
    de WSDL sí es compartida y eso está bien: es de solo lectura para el
    camino de emisión.
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
