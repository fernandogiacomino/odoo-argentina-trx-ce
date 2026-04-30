# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Errores y códigos de rechazo de los WS de AFIP/ARCA.

No es una lista exhaustiva oficial — AFIP publica la tabla completa en sus
manuales de desarrollador, pero estos son los códigos que con mayor
probabilidad aparecen en producción y vale la pena mapear para dar un hint
accionable al usuario (sin obligarlo a buscar el PDF del manual).

Los códigos que NO están acá se devuelven tal cual los da AFIP; el caller
puede mostrar "código X: mensaje crudo" y el usuario tendrá que buscar.

Referencias:
  - WSFEv1 manual para desarrolladores, tabla de errores.
  - WSAA manual de autenticación, tabla de errores.
"""


class AfipWsError(Exception):
    """Error base de cualquier WS de AFIP/ARCA.

    Atributos:
        code: código numérico o string que devolvió AFIP (None si es un
              error de red/protocolo antes de llegar al servicio).
        message: mensaje crudo devuelto por AFIP.
        hint: sugerencia nuestra sobre qué revisar (None si no tenemos una).
    """

    def __init__(self, code, message, hint=None):
        self.code = code
        self.message = message
        self.hint = hint
        human = "AFIP [%s] %s" % (code, message)
        if hint:
            human = "%s\n→ %s" % (human, hint)
        super().__init__(human)


class WsaaError(AfipWsError):
    """Error específico de autenticación contra WSAA."""


class WsfeError(AfipWsError):
    """Error específico de WSFEv1."""


class TransportError(AfipWsError):
    """Error de red, SSL o SOAP antes de llegar al servicio."""

    def __init__(self, message, hint=None):
        super().__init__(code="transport", message=message, hint=hint)


# Hints para los códigos más frecuentes en homologación/producción.
# Formato: código -> (descripción resumida, pista sobre qué revisar).
WSAA_HINTS = {
    "coe.alreadyAuthenticated": (
        "Ya existe un TA vigente con esa firma",
        "Probá esperar unos segundos antes de pedir otro TA, o reutilizá el cacheado.",
    ),
    "certificate.notAuthorized": (
        "El certificado no está autorizado al servicio",
        "Entrá al portal AFIP → Administrador de Relaciones → vincular el "
        "CN del certificado al WS (wsfe, wsfex, etc.) para la CUIT.",
    ),
    "signature.invalid": (
        "La firma CMS no validó contra el CN del certificado",
        "Revisá que estés firmando con la misma private key del certificado "
        "subido. Si rotaste el cert, tenés que rotar también la key.",
    ),
    "request.expired": (
        "El generationTime/expirationTime del LoginTicketRequest expiró antes de llegar",
        "Probá sincronizar el reloj del server (ntpdate). El drift > 5 minutos "
        "contra AFIP rompe la autenticación.",
    ),
}

WSFE_HINTS = {
    10015: (
        "CUIT inválida o no registrada",
        "Verificá la CUIT del receptor en el padrón AFIP (consulta pública).",
    ),
    10016: (
        "Fecha del comprobante fuera de rango permitido",
        "AFIP acepta ±5 días de la fecha actual para servicios, ±10 para bienes. "
        "Revisá la fecha de la factura.",
    ),
    10017: (
        "Código de comprobante no autorizado para el punto de venta",
        "El POS no está habilitado para emitir ese tipo de comprobante. "
        "Verificá en AFIP → Puntos de venta.",
    ),
    10018: (
        "CbteDesde/CbteHasta no coinciden con el próximo autorizado",
        "Llamá FECompUltimoAutorizado para ver el último número y usá ese + 1.",
    ),
    10048: (
        "Error de cálculo en ImpTotal",
        "AFIP recalcula: ImpTotal = ImpNeto + ImpIVA + ImpTrib + ImpOpEx + "
        "ImpTotConc. Revisá redondeos.",
    ),
    10049: (
        "Error de cálculo en ImpIVA",
        "ImpIVA debe ser la suma de los items del array Iva. Chequeá redondeos.",
    ),
    10051: (
        "CAE ya emitido para ese comprobante",
        "Usá FECompConsultar para traer el CAE existente en lugar de reintentar.",
    ),
    10154: (
        "IVA no corresponde a la condición del receptor",
        "Si el receptor es Monotributo/Exento, revisá que el IVA esté en "
        "la alícuota correcta o en 'No gravado' según tipo de comprobante.",
    ),
    600: (
        "Error genérico del servicio",
        "El mensaje crudo de AFIP suele tener el detalle. Si dice "
        "'ValidacionDeToken', el TA venció o no corresponde.",
    ),
    601: (
        "CUIT del emisor no coincide con el del token",
        "El TA fue generado para otra CUIT. Regenerá el token para la "
        "compañía correcta.",
    ),
    602: (
        "Sin resultados",
        "El método no devolvió datos para la CUIT. En FEParamGetPtosVenta "
        "significa que no hay puntos de venta dados de alta en AFIP para "
        "esa CUIT. En homologación hay que crearlos desde "
        "https://wswhomo.afip.gov.ar/wsass/ (o en el portal real para "
        "producción). En otros métodos el 602 es 'consulta sin datos', "
        "no necesariamente un error.",
    ),
}


def get_wsaa_hint(code):
    """Devuelve (descripción, hint) o (None, None) si no lo conocemos."""
    return WSAA_HINTS.get(code, (None, None))


def get_wsfe_hint(code):
    """Devuelve (descripción, hint) o (None, None)."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        pass
    return WSFE_HINTS.get(code, (None, None))
