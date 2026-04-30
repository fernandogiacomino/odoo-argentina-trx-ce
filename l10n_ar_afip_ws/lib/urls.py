# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""URLs de los Web Services de AFIP/ARCA.

Homologación: `*.afip.gov.ar` con subdominio `*homo*` o `*servicios1.afip.gov.ar`.
Producción:   sin el sufijo `homo`.

Mantengo el diccionario separado por entorno para que el error de elegir el
equivocado sea ruidoso (en vez de un "funciona y factura en producción" no
deseado).
"""

# Cada WS tiene dos URLs:
#   'service': el endpoint ?WSDL del servicio (se usa con zeep.Client)
#   'login_service_name': el string que se pone en <service> del LoginTicketRequest
#
# El `login_service_name` es distinto de nuestra clave en el diccionario — por
# ejemplo, lo que nosotros llamamos `wsfe` AFIP lo espera como `wsfe` también,
# pero para `wscdc` y `wsfex` se mantiene la misma literal.
WS_URLS = {
    "testing": {
        "wsaa": {
            "service": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL",
            "login_service_name": None,  # WSAA no se auto-consume
        },
        "wsfe": {
            "service": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL",
            "login_service_name": "wsfe",
        },
        "wsfex": {
            "service": "https://wswhomo.afip.gov.ar/wsfexv1/service.asmx?WSDL",
            "login_service_name": "wsfex",
        },
        "wsbfe": {
            "service": "https://wswhomo.afip.gov.ar/wsbfev1/service.asmx?WSDL",
            "login_service_name": "wsbfe",
        },
        "wscdc": {
            "service": "https://wswhomo.afip.gov.ar/WSCDC/service.asmx?WSDL",
            "login_service_name": "wscdc",
        },
        "wsmtxca": {
            "service": "https://fwshomo.afip.gov.ar/wsmtxca/services/MTXCAService?WSDL",
            "login_service_name": "wsmtxca",
        },
        # Padrón AFIP A13 (consulta de inscripción / constancia).
        #
        # AFIP separa dos trámites delegables que parecen lo mismo pero
        # NO son intercambiables:
        #
        #   - `ws_sr_constancia_inscripcion`: histórico, apunta a otro
        #     endpoint (¿REST?), no sirve para el WSDL A13 en 2026.
        #   - `ws_sr_padron_a13`:           el "moderno", lo que el
        #     WSDL `personaServiceA13` espera en `<service>` del TA.
        #
        # AFIP es explícito en el fault si los confundís:
        # "Token recibido es para el servicio [X], deberia ser para
        # servicio [ws_sr_padron_a13]".
        #
        # → Hay que delegar `ws_sr_padron_a13` al cert en el portal
        # AFIP. NO alcanza con `ws_sr_constancia_inscripcion`.
        # (Refs internas: el repo a2systems/l10n_ar_padron de 2022 usa
        # `ws_sr_constancia_inscripcion`, pero AFIP cambió la
        # validación desde entonces.)
        "ws_sr_padron_a13": {
            "service": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL",
            "login_service_name": "ws_sr_padron_a13",
        },
        # Padrón A5 (rico): trae `categoriaIva`, `impuesto[]`, `actividad[]`.
        # WSDL `personaServiceA5`, método `getPersona_v2`. El `<service>` del
        # LoginTicket es `ws_sr_constancia_inscripcion` (legacy literal).
        # Usamos A5 por defecto en el flujo de partner; A13 queda disponible
        # para casos donde solo querés metadata mínima.
        "ws_sr_constancia_inscripcion": {
            "service": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5?WSDL",
            "login_service_name": "ws_sr_constancia_inscripcion",
        },
    },
    "production": {
        "wsaa": {
            "service": "https://wsaa.afip.gov.ar/ws/services/LoginCms?WSDL",
            "login_service_name": None,
        },
        "wsfe": {
            "service": "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL",
            "login_service_name": "wsfe",
        },
        "wsfex": {
            "service": "https://servicios1.afip.gov.ar/wsfexv1/service.asmx?WSDL",
            "login_service_name": "wsfex",
        },
        "wsbfe": {
            "service": "https://servicios1.afip.gov.ar/wsbfev1/service.asmx?WSDL",
            "login_service_name": "wsbfe",
        },
        "wscdc": {
            "service": "https://servicios1.afip.gov.ar/WSCDC/service.asmx?WSDL",
            "login_service_name": "wscdc",
        },
        "wsmtxca": {
            "service": "https://serviciosjava.afip.gob.ar/wsmtxca/services/MTXCAService?WSDL",
            "login_service_name": "wsmtxca",
        },
        # Ver nota larga en `testing` arriba: el WSDL `personaServiceA13`
        # exige `<service>ws_sr_padron_a13</service>` en el LoginTicket.
        # `ws_sr_constancia_inscripcion` es un trámite legacy SEPARADO —
        # delegar uno NO autoriza el otro. Hay que delegar
        # `ws_sr_padron_a13` al cert en el portal AFIP.
        "ws_sr_padron_a13": {
            "service": "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL",
            "login_service_name": "ws_sr_padron_a13",
        },
        # Ver nota arriba en `testing`: A5 es el WS rico.
        "ws_sr_constancia_inscripcion": {
            "service": "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5?WSDL",
            "login_service_name": "ws_sr_constancia_inscripcion",
        },
    },
}


def get_wsdl_url(ws, environment):
    """Devuelve la URL WSDL del WS solicitado.

    :param ws: 'wsaa', 'wsfe', 'wsfex', 'wsbfe', 'wscdc', 'wsmtxca'.
    :param environment: 'testing' o 'production'.
    :raises ValueError: si el WS o el entorno no está registrado.
    """
    if environment not in WS_URLS:
        raise ValueError(
            "Entorno desconocido %r, los válidos son: %s" % (
                environment, list(WS_URLS.keys())
            )
        )
    if ws not in WS_URLS[environment]:
        raise ValueError(
            "WS desconocido %r, los válidos son: %s" % (
                ws, list(WS_URLS[environment].keys())
            )
        )
    return WS_URLS[environment][ws]["service"]


def get_login_service_name(ws, environment):
    """Devuelve el nombre del servicio tal como lo espera WSAA en el login."""
    if environment not in WS_URLS or ws not in WS_URLS[environment]:
        raise ValueError("WS/entorno desconocido: %s/%s" % (ws, environment))
    name = WS_URLS[environment][ws]["login_service_name"]
    if name is None:
        raise ValueError("El WS %s no se autentica contra sí mismo" % ws)
    return name
