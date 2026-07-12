# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Errores y códigos de rechazo de los WS de AFIP/ARCA.

Catálogo de hints para los códigos más frecuentes de cada servicio.
Para cada código devolvemos:

    (descripción, hint accionable)

donde el `hint` le dice al operador **qué revisar** o **qué hacer**
en términos concretos, no la jerga interna del manual de AFIP.

Servicios cubiertos:
  - **WSAA**: autenticación. Códigos string (`coe.X`, `certificate.X`).
  - **WSFEv1**: emisión mercado interno. Códigos numéricos (10000-10999).
  - **WSFEX**: factura de exportación. Códigos numéricos (1500-1700).
  - **WSCDC**: constatación de comprobantes recibidos.
  - **CAEA**: solicitud y rendición CAEA.

Referencias:
  - https://www.afip.gob.ar/fe/documentos/manualdesarrolladorCOMPGV4.pdf
  - https://www.afip.gob.ar/ws/documentacion/manuales/Manual_Desarrollador_WSFEX.pdf
  - https://www.afip.gob.ar/ws/WSCDC/manualWSCDC.pdf
"""


class AfipWsError(Exception):
    """Error base de cualquier WS de AFIP/ARCA."""

    def __init__(self, code, message, hint=None):
        self.code = code
        self.message = message
        self.hint = hint
        human = "AFIP [%s] %s" % (code, message)
        if hint:
            human = "%s\n→ %s" % (human, hint)
        super().__init__(human)


class WsaaError(AfipWsError):
    """Error de autenticación contra WSAA."""


class WsfeError(AfipWsError):
    """Error de WSFEv1 / WSFEX / WSCDC / CAEA."""


class WscdcError(AfipWsError):
    """Error específico de WSCDC."""


class TransportError(AfipWsError):
    """Error de red, SSL o SOAP antes de llegar al servicio."""

    def __init__(self, message, hint=None):
        super().__init__(code="transport", message=message, hint=hint)


# ======================================================================
# WSAA — Autenticación
# ======================================================================
WSAA_HINTS = {
    "coe.alreadyAuthenticated": (
        "Ya existe un TA vigente con esa firma",
        "Esperá unos segundos antes de pedir otro TA, o reutilizá el cacheado.",
    ),
    "certificate.notAuthorized": (
        "El certificado no está autorizado al servicio",
        "Portal AFIP → Administrador de Relaciones → vincular el CN del cert "
        "al WS (wsfe, wsfex, wscdc) para la CUIT.",
    ),
    "signature.invalid": (
        "La firma CMS no validó contra el CN del certificado",
        "Revisá que estés firmando con la misma private key del cert. "
        "Si rotaste el cert, rotá también la key.",
    ),
    "request.expired": (
        "El generationTime/expirationTime del LoginTicket expiró",
        "Sincronizá el reloj del server (ntpdate). Drift > 5 min rompe auth.",
    ),
    "request.notFound": (
        "El servicio solicitado no existe o el certificado no tiene permiso",
        "Verificá que el nombre del servicio sea exacto (ej. 'wsfe' no 'WSFE').",
    ),
}


# ======================================================================
# WSFEv1 — Mercado interno
# ======================================================================
WSFE_HINTS = {
    # ---- Errores de servicio / autenticación ----
    600: (
        "Error genérico del servicio",
        "Si el mensaje dice 'ValidacionDeToken', el TA venció. Si dice "
        "'AccesoDenegado', revisá la delegación del cert al servicio.",
    ),
    601: (
        "CUIT del emisor no coincide con el del token",
        "El TA fue generado para otra CUIT. Regenerá el token para la "
        "compañía correcta.",
    ),
    602: (
        "Sin resultados / no existen datos",
        "El método no devolvió datos para los parámetros pedidos. En "
        "FEParamGetPtosVenta significa que no hay puntos de venta dados "
        "de alta en AFIP. En consultas (FECAEAConsultar, etc.) significa "
        "que el período/orden no fue solicitado.",
    ),

    # ---- Validaciones de cabecera ----
    10000: (
        "CantReg no coincide con la cantidad de comprobantes enviados",
        "El nodo FeCabReq.CantReg debe ser igual a len(FeDetReq).",
    ),
    10001: (
        "CbteTipo inválido o no autorizado",
        "Verificá el código de tipo de comprobante con FEParamGetTiposCbte. "
        "Si es válido pero no autorizado, hay que habilitarlo en AFIP.",
    ),
    10002: (
        "Punto de venta inválido",
        "El POS no está creado en AFIP. Crear desde el portal "
        "'Administración de puntos de venta y domicilios'.",
    ),
    10003: (
        "Concepto inválido",
        "Concepto debe ser 1 (Productos), 2 (Servicios) o 3 (Productos y "
        "Servicios).",
    ),

    # ---- Validaciones de receptor ----
    10004: (
        "Tipo de documento del receptor inválido",
        "Tipos válidos: 80=CUIT, 86=CUIL, 87=CDI, 89=LE, 90=LC, 91=CI Ext, "
        "94=Pasaporte, 95=CI Bs.As. RNP, 96=DNI, 99=Sin identificar.",
    ),
    10005: (
        "DocNro inválido",
        "Si DocTipo=80 (CUIT), tiene que ser 11 dígitos válidos. Si DocTipo=99, "
        "DocNro debe ser 0.",
    ),
    10006: (
        "DocTipo=99 (CF) requiere DocNro=0 e ImpTotal ≤ máximo del régimen",
        "Para Consumidor Final el límite es el que define la RG vigente "
        "(consultar). Si supera, usar DocTipo=96 (DNI) con el número real.",
    ),
    10015: (
        "CUIT del receptor inválida o no registrada",
        "Verificá la CUIT en el padrón AFIP (consulta pública). "
        "Si recién se inscribió, esperá 24h.",
    ),
    10016: (
        "El número o la fecha del comprobante no se corresponde con el "
        "próximo a autorizar",
        "Dos causas posibles. (a) NÚMERO: AFIP ya consumió ese número — pasa "
        "cuando un pedido de CAE salió pero la transacción de Odoo se "
        "reintentó/abortó después. Llamá FECompUltimoAutorizado(PtoVta, "
        "CbteTipo) y compará; si el comprobante que AFIP tiene en ese número "
        "es el tuyo (FECompConsultar), adoptá ese CAE en lugar de pedir uno "
        "nuevo. (b) FECHA: AFIP acepta ±5 días de la fecha actual para "
        "Servicios y ±10 días para Productos; si la factura es muy vieja hay "
        "que regularizar con FECAESinMovimientoInformar.",
    ),
    10017: (
        "Tipo de comprobante no autorizado para ese POS",
        "El POS no está habilitado para emitir ese tipo. AFIP → Puntos de "
        "venta → Habilitar el tipo.",
    ),
    10018: (
        "CbteDesde/CbteHasta no coincide con el próximo autorizado",
        "Llamá FECompUltimoAutorizado(PtoVta, CbteTipo) para traer el "
        "último número y usá UltimoAutorizado + 1.",
    ),

    # ---- Cotización / moneda ----
    10024: (
        "Cotización (MonCotiz) no válida",
        "Si MonId='PES' (ARS) MonCotiz debe ser 1. Para USD/EUR la cotización "
        "debe ser ≈ a la oficial AFIP del día (FEParamGetCotizacion).",
    ),
    10025: (
        "MonId no existe en el catálogo",
        "Códigos válidos: PES (ARS), DOL (USD), 060 (EUR). Ver "
        "FEParamGetTiposMonedas.",
    ),

    # ---- Importes ----
    10042: (
        "ImpNeto debe ser cero o positivo",
        "Si ImpNeto = 0 verificá que no esté faltando. ImpNeto < 0 solo "
        "aplica a NC y debe ir como positivo (el signo lo pone el tipo cbte).",
    ),
    10043: (
        "ImpTotal debe ser ≥ 0",
        "Re-verificá la suma. NC se envía con importe positivo, AFIP la "
        "interpreta como negativa por el tipo de cbte.",
    ),
    10047: (
        "ImpIVA mal calculado",
        "ImpIVA debe ser la suma de los `Importe` del array Iva. Si solo "
        "hay 1 alícuota, ImpIVA = base * pct/100 (con 2 dec).",
    ),
    10048: (
        "ImpTotal mal calculado",
        "ImpTotal = ImpNeto + ImpIVA + ImpTrib + ImpOpEx + ImpTotConc. "
        "Probable diff por redondeo en el detalle de IVA o tributos.",
    ),
    10049: (
        "ImpIVA distinto de la suma del array Iva",
        "Recalcular cada Iva.Importe = Iva.BaseImp * pct/100 redondeado a "
        "2 decimales y sumar.",
    ),
    10050: (
        "ImpTrib distinto de la suma del array Tributos",
        "Recalcular cada Tributo.Importe = BaseImp * Alic/100 y sumar.",
    ),

    # ---- Resultado / consulta ----
    10051: (
        "CAE ya emitido para ese comprobante",
        "El comprobante ya está autorizado. Usá FECompConsultar para traer "
        "el CAE existente en lugar de reintentar.",
    ),
    10052: (
        "Comprobante asociado no existe",
        "Para NC/ND, verificá que el CbtesAsoc.Tipo + PtoVta + Nro + Cuit "
        "matchee una factura emitida.",
    ),

    # ---- Servicio (concepto 2/3) ----
    10070: (
        "FchServDesde/Hasta requeridos para Concepto Servicios",
        "Para Concepto=2 o 3, agregar FchServDesde, FchServHasta y "
        "FchVtoPago en formato YYYYMMDD.",
    ),
    10071: (
        "FchServHasta < FchServDesde",
        "El período de servicio invertido. Verificar las fechas.",
    ),
    10072: (
        "FchVtoPago menor a la fecha del comprobante",
        "El vencimiento de pago debe ser posterior o igual al CbteFch.",
    ),

    # ---- Receptor / condición IVA ----
    10073: (
        "DocTipo del receptor incorrecto para letra A",
        "Las letras A, M y FCE-A requieren DocTipo=80 (CUIT). Para B/C/E "
        "se permite también DNI/Pasaporte.",
    ),
    10074: (
        "CondicionIVAReceptorId inválido",
        "Catálogo oficial (FEParamGetCondicionIvaReceptor, v4.3): 1=RI, "
        "4=Exento, 5=CF, 6=Monotributo, 7=Sujeto No Categorizado, "
        "8=Prov.Exterior, 9=Cliente.Exterior, 10=IVA Liberado, "
        "13=Monotributo Social, 15=No Alcanzado, "
        "16=Monotributo Trabajador Indep. Promovido.",
    ),
    10154: (
        "Condición IVA del receptor no compatible con el tipo de comprobante",
        "Cmp_Clase: A/M/C admite Id 1, 6, 13, 16. B/C admite 4, 5, 7, 8, "
        "9, 10, 15. Por ej. una FA-A no puede emitirse a Consumidor Final.",
    ),
    10242: (
        "CondicionIVAReceptor obligatorio o valor no válido",
        "RG 5616: desde 06/04/2025 opcional, OBLIGATORIO desde "
        "01/06/2026. Asegurate de mandar CondicionIVAReceptorId con valor "
        "del catálogo (ver código 10074). Llamar FEParamGetCondicionIvaReceptor "
        "para obtener la tabla actualizada.",
    ),

    # Códigos nuevos publicados con la v4.3 del manual (RG-4291), Alta
    # del 14/05/2026 22:00hs según evento WSFE Code 43 — sin descripción
    # textual oficial al día del commit; los hints son inferidos del
    # contexto. Cuando salga el manual definitivo, revisar.
    10247: (
        "Validación cruzada CondicionIVAReceptor / tipo comprobante (v4.3)",
        "Nuevo código de alta el 14/05/2026 — verifica que el "
        "CondicionIVAReceptorId sea consistente con Cmp_Clase del tipo "
        "de comprobante y con DocTipo del receptor. Revisar manual v4.3.",
    ),
    10248: (
        "Combinación de parámetros inválida (v4.3)",
        "Nuevo código de alta el 14/05/2026 — chequear combinación "
        "DocTipo + DocNro + CondicionIVAReceptorId. Si el receptor tiene "
        "CUIT, AFIP exige consistencia con padrón. Manual v4.3 pendiente.",
    ),
    10249: (
        "Validación adicional v4.3",
        "Nuevo código de alta el 14/05/2026 — sin descripción oficial. "
        "Re-leer el manual v4.3 cuando esté disponible y refinar este hint.",
    ),

    # ---- Iva detalle ----
    10080: (
        "Array Iva contiene Id no válido",
        "Códigos válidos AlicIva: 3=0%, 4=10.5%, 5=21%, 6=27%, 8=5%, 9=2.5%.",
    ),
    10081: (
        "Iva.BaseImp = 0 con Iva.Importe > 0",
        "Si la base es 0 el importe IVA debe ser 0.",
    ),

    # ---- Tributos ----
    10090: (
        "Tributo.Id no válido",
        "Catálogo: 01=Imp.Nac, 02=Imp.Prov, 03=Mun, 04=Internos, "
        "06=Perc.IVA, 07=Perc.IIBB, 08=Perc.Mun, 09=Otras Perc, 99=Otro.",
    ),

    # ---- Reproceso / sistema ----
    10100: (
        "Reproceso del comprobante",
        "AFIP detectó que ese comprobante ya fue procesado en una llamada "
        "anterior. Verificar con FECompConsultar antes de re-emitir.",
    ),

    # ---- Específicos CAEA ----
    # Códigos nuevos de alta el 14/05/2026 22hs (evento WSFE Code 43):
    # 827, 828, 829. Sin descripción oficial al día del commit; cuando
    # salga el manual definitivo, ajustar los hints.
    827: (
        "Validación CAEA v4.3 — código 827",
        "Nuevo código de alta el 14/05/2026 para CAEA. Sin descripción "
        "oficial al momento del commit. Posiblemente: validación de "
        "ventana de rendición o consistencia período/orden ampliada. "
        "Revisar manual WSFEv1 v4.3 RG-4291 cuando esté disponible.",
    ),
    828: (
        "Validación CAEA v4.3 — código 828",
        "Nuevo código de alta el 14/05/2026 para CAEA. Sin descripción "
        "oficial. Revisar manual v4.3 y refinar.",
    ),
    829: (
        "Validación CAEA v4.3 — código 829",
        "Nuevo código de alta el 14/05/2026 para CAEA. Sin descripción "
        "oficial. Revisar manual v4.3 y refinar.",
    ),

    15000: (
        "Período/Orden inválido para CAEA",
        "Período = YYYYMM. Orden = 1 (1° quincena) o 2 (2° quincena).",
    ),
    15004: (
        "CAEA ya solicitado para ese período/orden",
        "Usar FECAEAConsultar para traerlo en lugar de re-solicitar.",
    ),
    15006: (
        "Solicitud de CAEA fuera de ventana",
        "Solo se puede solicitar dentro de los 5 días previos al inicio "
        "de la quincena. Esperar a la ventana.",
    ),
    15008: (
        "CAEA no rendido dentro del plazo",
        "Hay que rendir vía FECAEARegInformativo dentro de los 8 días "
        "posteriores al cierre de la quincena.",
    ),
}


# ======================================================================
# WSFEX — Factura de Exportación
# ======================================================================
WSFEX_HINTS = {
    1500: (
        "Tipo de comprobante no válido para exportación",
        "Códigos WSFEX: 19=FA-E, 20=NC-E, 21=ND-E. Otros van por WSFEv1.",
    ),
    1501: (
        "Punto de venta no autorizado para exportación",
        "El POS debe estar marcado como 'Exportación' en AFIP. Verificar "
        "en FEXGetParam_PtoVenta.",
    ),
    1502: (
        "Cliente del exterior con datos incompletos",
        "Para FA-E el partner necesita: nombre, domicilio, país (con código "
        "AFIP) y Cuit_pais_cliente.",
    ),
    1503: (
        "Tipo_expo inválido",
        "Tipo_expo: 1=Bienes, 2=Servicios, 4=Otros. (3 está reservado.)",
    ),
    1505: (
        "Cmp_asoc inválido para NC/ND-E",
        "Para NC-E (20) o ND-E (21) hay que asociar la FA-E original "
        "(Cbte_tipo=19) con su Punto_vta y Cbte_nro.",
    ),
    1506: (
        "Items vacío",
        "Una FA-E debe tener al menos 1 ítem en el array Items.",
    ),
    1507: (
        "Imp_total no coincide con suma de Pro_total_item",
        "ImporteTotal debe ser exactamente la suma de los Pro_total_item "
        "del array Items.",
    ),
    1551: (
        "Permisos requeridos para Tipo_expo=1 (Bienes)",
        "Para exportación de bienes, agregar el array Permisos con los "
        "DUA / Despachos.",
    ),
    1552: (
        "Dst_cmp inválido",
        "Dst_cmp = código AFIP de país destino (ver l10n_ar_afip_code en "
        "res.country o FEXGetParam_DST_pais).",
    ),
    1601: (
        "Cuit_pais_cliente inválido",
        "Es el CUIT que usa el receptor en su país (ver "
        "FEXGetParam_DST_CUIT). Si es persona física usar el natural_vat "
        "del país; si es empresa, el legal_entity_vat.",
    ),
}


# ======================================================================
# WSCDC — Constatación de comprobantes recibidos
# ======================================================================
WSCDC_HINTS = {
    100: (
        "El comprobante no se encuentra en las bases de AFIP",
        "Esto significa Resultado='R'. Posibles causas: número/POS mal "
        "informado, CAE inexistente, comprobante anulado.",
    ),
    102: (
        "La cuit del emisor no se corresponde con el CAE/CAI/CAEA",
        "Verificá el CUIT del proveedor (debe ser 11 dígitos sin guiones, "
        "y matchear al que figura en la factura física).",
    ),
    103: (
        "Punto de venta no se corresponde con el CAE",
        "El POS de la factura no coincide con el que generó el CAE. "
        "Re-leer el comprobante físico.",
    ),
    104: (
        "Tipo comprobante no se corresponde con el CAE",
        "El tipo (1=FA-A, 6=FA-B, etc.) no matchea. Verificar.",
    ),
    105: (
        "El N° de comprobante no se corresponde con el CAE/CAI/CAEA",
        "El número de comprobante registrado en AFIP es distinto. "
        "Re-leer el comprobante físico.",
    ),
    106: (
        "Fecha del comprobante no se corresponde con el CAE",
        "La fecha de emisión registrada en AFIP es distinta. "
        "Verificar el comprobante físico.",
    ),
    110: (
        "El importe total no se corresponde con lo registrado en AFIP",
        "Diferencia de importe — pueden ser centavos por redondeo (revisar) "
        "o el comprobante físico tiene otro total.",
    ),
    112: (
        "El tipo y número de documento del receptor no se corresponde",
        "Para letra A/M el receptor debe ir con DocTipo=80 (CUIT). Para "
        "B/C también DNI. Verificar que el CUIT/DNI del receptor sea el "
        "que registramos al recibir.",
    ),
}


# ======================================================================
# Helpers públicos
# ======================================================================
def get_wsaa_hint(code):
    """Hint para errores WSAA — código string."""
    return WSAA_HINTS.get(code, (None, None))


def get_wsfe_hint(code):
    """Hint para errores WSFEv1 / CAEA — código numérico."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        pass
    return WSFE_HINTS.get(code, (None, None))


def get_wsfex_hint(code):
    """Hint para errores WSFEX — código numérico."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        pass
    return WSFEX_HINTS.get(code, (None, None))


def get_wscdc_hint(code):
    """Hint para errores WSCDC — código numérico."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        pass
    return WSCDC_HINTS.get(code, (None, None))


def get_hint(service, code):
    """Hint genérico — `service` ∈ {'wsaa', 'wsfe', 'wsfex', 'wscdc', 'caea'}."""
    if service == "wsaa":
        return get_wsaa_hint(code)
    if service in ("wsfe", "caea"):
        return get_wsfe_hint(code)
    if service == "wsfex":
        return get_wsfex_hint(code)
    if service == "wscdc":
        return get_wscdc_hint(code)
    return (None, None)
