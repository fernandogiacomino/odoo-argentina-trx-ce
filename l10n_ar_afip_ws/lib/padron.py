# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Cliente del WS Padrón AFIP — A5 (rico) y A13 (mínimo).

Devuelve los datos públicos de un CUIT/CUIL: razón social, responsabilidad
IVA, domicilio fiscal, monotributo si aplica, estado de la clave fiscal,
e impuestos en los que está inscripto.

Por defecto usamos A5 (`personaServiceA5`, método `getPersona_v2`)
porque trae `categoriaIva`, `impuesto[]` y `actividad[]` — lo que
necesitamos para inferir la responsabilidad IVA del partner.

A13 (`personaServiceA13`, método `getPersona`) es una versión liviana
que NO devuelve esos campos; queda como opción para callers que solo
quieren metadata mínima.

El servicio que se usa para el LoginTicketRequest depende del WS:

    - A5  → `<service>ws_sr_constancia_inscripcion</service>`
    - A13 → `<service>ws_sr_padron_a13</service>`

Son DELEGACIONES SEPARADAS en el portal AFIP — delegar una NO autoriza
la otra.

Igual que `wsfe.py`, esta capa es pura: recibe/devuelve dicts. La
integración con `res.partner` se hace en `l10n_ar_padron_query`.
"""
import logging

from zeep.exceptions import Fault, TransportError as ZeepTransportError

from . import errors, urls

_logger = logging.getLogger(__name__)

#: Mapeo de impuestos AFIP a su descripción legible. Sólo los más comunes;
#: el WS devuelve el `idImpuesto` y nosotros lo dejamos pasar al caller
#: para que decida qué hacer.
IMPUESTO_IVA = 30
IMPUESTO_MONOTRIBUTO = 20
IMPUESTO_GANANCIAS = 11

#: Mapeo categoría AFIP → código `l10n_ar.afip.responsibility.type`.
#: El WS devuelve un texto "RESPONSABLE INSCRIPTO" / "MONOTRIBUTO" / etc.
#: y nosotros lo cruzamos al code numérico de l10n_ar.
RESPONSABILIDAD_BY_DESCRIPCION = {
    "RESPONSABLE INSCRIPTO": "1",
    "IVA RESPONSABLE INSCRIPTO": "1",
    "EXENTO": "4",
    "IVA SUJETO EXENTO": "4",
    "CONSUMIDOR FINAL": "5",
    "MONOTRIBUTO": "6",
    "RESPONSABLE MONOTRIBUTO": "6",
    "MONOTRIBUTO SOCIAL": "13",
    "MONOTRIBUTISTA SOCIAL": "13",
    "MONOTRIBUTO TRABAJADOR INDEPENDIENTE PROMOVIDO": "16",
    "NO ALCANZADO": "15",
    "IVA NO ALCANZADO": "15",
}


def _build_client(environment, transport, ws="ws_sr_constancia_inscripcion"):
    """Construye el cliente zeep para A5 o A13 según `ws`."""
    import zeep
    wsdl = urls.get_wsdl_url(ws, environment)
    try:
        return zeep.Client(wsdl=wsdl, transport=transport)
    except ZeepTransportError as e:
        raise errors.TransportError(
            message="No pude traer el WSDL del WS Padrón (%s): %s" % (wsdl, e),
        )


def dummy(environment, transport, ws="ws_sr_constancia_inscripcion"):
    """dummy(): ping sin auth. Devuelve {appserver, dbserver, authserver}."""
    client = _build_client(environment, transport, ws=ws)
    try:
        r = client.service.dummy()
    except (Fault, ZeepTransportError) as e:
        raise errors.TransportError(message="padron.dummy: %s" % e)
    return {
        "app_server": getattr(r, "appserver", None),
        "db_server": getattr(r, "dbserver", None),
        "auth_server": getattr(r, "authserver", None),
    }


def get_persona(auth, id_persona, environment, transport,
                ws="ws_sr_constancia_inscripcion"):
    """Consulta los datos de un CUIT/CUIL en el Padrón AFIP.

    Por defecto pega contra A5 (`getPersona_v2`); pasá
    `ws="ws_sr_padron_a13"` para usar A13 (`getPersona`).

    :param auth: dict {'token', 'sign', 'cuit'} obtenido del TA del
        `<service>` correcto. **NO** se puede usar un TA de otro WS —
        AFIP rechaza con "Token recibido es para el servicio [X]".
    :param id_persona: int — el CUIT/CUIL a consultar (11 dígitos).
    :return: dict normalizado:
        {
            "id_persona": 30718055853,
            "tipo_persona": "JURIDICA" | "FISICA",
            "tipo_clave": "CUIT" | "CUIL" | "CDI",
            "estado_clave": "ACTIVO" | "INACTIVO",
            "razon_social": "...",                # si JURIDICA
            "nombre": "...", "apellido": "...",   # si FISICA
            "fecha_inscripcion": date | None,
            "fecha_fallecimiento": date | None,   # si FISICA
            "fecha_cierre": date | None,          # si JURIDICA
            "impuestos": [int, ...],              # ids de impuestos activos
            "categorias_monotributo": [{"idImpuesto": int, "descripcion": str,
                                        "periodo": int, "estado": str}, ...],
            "actividades": [{"idActividad": int, "descripcionActividad": str,
                             "nomenclador": int, "periodo": int,
                             "orden": int}, ...],
            "domicilio_fiscal": {
                "tipoDomicilio": "FISCAL" | "REAL" | "LEGAL",
                "calle": str, "numero": int|None,
                "localidad": str, "codPostal": str,
                "idProvincia": int, "descripcionProvincia": str,
                "datoAdicional": str,
            } | None,
            "categoria_iva": str,                  # "RESPONSABLE INSCRIPTO" | "EXENTO" | ...
            "categoria_iva_codigo": str | None,    # mapeado a l10n_ar (1=RI, 4=Ex, ...)
        }

    :raises errors.WsfeError: si AFIP devuelve `Errors` (CUIT no encontrado, etc.).
    """
    client = _build_client(environment, transport, ws=ws)
    # A5 expone `getPersona_v2`, A13 expone `getPersona`. Misma firma.
    method_name = "getPersona_v2" if ws == "ws_sr_constancia_inscripcion" else "getPersona"
    method = getattr(client.service, method_name)
    try:
        r = method(
            token=auth["token"],
            sign=auth["sign"],
            cuitRepresentada=int(auth["cuit"]),
            idPersona=int(id_persona),
        )
    except Fault as f:
        # AFIP a veces devuelve faults SOAP en lugar de errores estructurados
        # para errores de auth o CUIT inexistente. Los pasamos como WsfeError
        # con code='fault' para que el caller decida.
        raise errors.WsfeError(code="fault", message=str(f))
    except ZeepTransportError as e:
        raise errors.TransportError(message=str(e))

    return _serialize_persona(r)


def _serialize_persona(r):
    """Convierte la respuesta zeep en un dict plano y útil.

    Detecta automáticamente el formato:
        - **A5** (`personaServiceA5`/`getPersona_v2`): wrapper raíz con
          `datosGenerales`, `datosMonotributo`, `datosRegimenGeneral`.
        - **A13** (`personaServiceA13`/`getPersona`): wrapper `persona`
          con todos los nodos planos.

    Y devuelve siempre el mismo dict normalizado.
    """
    if r is None:
        return None

    def _g(o, name, default=None):
        if o is None:
            return default
        v = getattr(o, name, default)
        return v if v is not None else default

    # Detectar formato.
    datos_generales = _g(r, "datosGenerales")
    if datos_generales is not None:
        return _serialize_a5(r, _g)
    # Fallback A13: wrapper `persona` o el root mismo.
    pers = _g(r, "persona") or r
    return _serialize_a13(pers, _g)


def _serialize_a13(pers, _g):
    """Parser para `personaServiceA13`/`getPersona`."""
    if pers is None:
        return None

    res = _empty_persona_dict()
    res.update({
        "id_persona": _g(pers, "idPersona"),
        "tipo_persona": _g(pers, "tipoPersona"),
        "tipo_clave": _g(pers, "tipoClave"),
        "estado_clave": _g(pers, "estadoClave"),
        "razon_social": _g(pers, "razonSocial"),
        "nombre": _g(pers, "nombre"),
        "apellido": _g(pers, "apellido"),
        "fecha_inscripcion": _g(pers, "fechaInscripcion"),
        "fecha_fallecimiento": _g(pers, "fechaFallecimiento"),
        "fecha_cierre": _g(pers, "fechaCierre"),
        "actividad_principal_id": _g(pers, "idActividadPrincipal"),
        "actividad_principal_descripcion": _g(pers, "descripcionActividadPrincipal"),
        "forma_juridica": _g(pers, "formaJuridica"),
    })

    # Domicilio: A13 lo manda como lista `domicilio[]`.
    domicilios = _g(pers, "domicilio", []) or []
    chosen = next((d for d in domicilios if _g(d, "tipoDomicilio") == "FISCAL"),
                  domicilios[0] if domicilios else None)
    if chosen is not None:
        res["domicilio_fiscal"] = _serialize_domicilio(chosen, _g)

    # Actividades: si vino la principal plana, la usamos como única.
    if res["actividad_principal_id"]:
        res["actividades"].append({
            "idActividad": res["actividad_principal_id"],
            "descripcionActividad": res["actividad_principal_descripcion"],
            "nomenclador": None,
            "periodo": _g(pers, "periodoActividadPrincipal"),
            "orden": 1,
        })

    return res


def _serialize_a5(r, _g):
    """Parser para `personaServiceA5`/`getPersona_v2`.

    A5 separa la respuesta en tres bloques:
        - datosGenerales:    datos identificatorios + domicilio fiscal.
        - datosMonotributo:  si la persona es MT (categoría, actividad).
        - datosRegimenGeneral: si tiene IVA / Ganancias / etc.
                               (impuesto[], actividad[]).
    """
    dg = _g(r, "datosGenerales")
    dm = _g(r, "datosMonotributo")
    drg = _g(r, "datosRegimenGeneral")

    res = _empty_persona_dict()

    # ---- datos generales ----------------------------------------------
    res.update({
        "id_persona": _g(dg, "idPersona"),
        "tipo_persona": _g(dg, "tipoPersona"),
        "tipo_clave": _g(dg, "tipoClave"),
        "estado_clave": _g(dg, "estadoClave"),
        "razon_social": _g(dg, "razonSocial"),
        "nombre": _g(dg, "nombre"),
        "apellido": _g(dg, "apellido"),
        "fecha_inscripcion": _g(dg, "fechaInscripcion"),
        "fecha_fallecimiento": _g(dg, "fechaFallecimiento"),
        "fecha_cierre": _g(dg, "fechaCierre"),
        "forma_juridica": _g(dg, "formaJuridica"),
    })
    dom = _g(dg, "domicilioFiscal")
    if dom is not None:
        res["domicilio_fiscal"] = _serialize_domicilio(dom, _g)

    # ---- impuestos del régimen general --------------------------------
    impuestos_raw = _g(drg, "impuesto", []) or []
    for imp in impuestos_raw:
        try:
            id_imp = int(_g(imp, "idImpuesto"))
        except (TypeError, ValueError):
            continue
        estado = _g(imp, "estadoImpuesto") or _g(imp, "estado")
        # Solo contamos como "activos" los AC. Los inactivos los
        # guardamos en el detalle pero no entran al `impuestos[]`.
        if estado == "AC":
            res["impuestos"].append(id_imp)
        res["impuestos_detalle"].append({
            "idImpuesto": id_imp,
            "descripcion": _g(imp, "descripcionImpuesto") or _g(imp, "descripcion"),
            "periodo": _g(imp, "periodo"),
            "estado": estado,
        })

    # ---- actividades --------------------------------------------------
    acts = _g(drg, "actividad", []) or []
    for a in acts:
        res["actividades"].append({
            "idActividad": _g(a, "idActividad"),
            "descripcionActividad": _g(a, "descripcionActividad"),
            "nomenclador": _g(a, "nomenclador"),
            "periodo": _g(a, "periodo"),
            "orden": _g(a, "orden"),
        })
    # actividad principal = orden=1 si existe, sino la primera.
    principal = (
        next((a for a in res["actividades"] if a.get("orden") == 1), None)
        or (res["actividades"][0] if res["actividades"] else None)
    )
    if principal:
        res["actividad_principal_id"] = principal["idActividad"]
        res["actividad_principal_descripcion"] = principal["descripcionActividad"]

    # ---- monotributo --------------------------------------------------
    if dm is not None:
        cat = _g(dm, "categoriaMonotributo")
        res["categorias_monotributo"].append({
            "idImpuesto": _g(dm, "idImpuesto"),
            "descripcion": cat,
            "periodo": _g(dm, "periodo"),
            "estado": _g(dm, "estado"),
        })

    # ---- inferencia de responsabilidad IVA ---------------------------
    # Catálogo l10n_ar.afip.responsibility.type.code:
    #   '1'=RI, '4'=Exento, '5'=Consumidor Final, '6'=Monotributo,
    #   '13'=Monotributo Social, '15'=IVA No Alcanzado.
    if dm is not None:
        # Tiene datos de monotributo activos → MT.
        res["categoria_iva"] = "MONOTRIBUTO"
        res["categoria_iva_codigo"] = "6"
    elif IMPUESTO_IVA in res["impuestos"]:
        # Inscripto en IVA general → Responsable Inscripto.
        res["categoria_iva"] = "RESPONSABLE INSCRIPTO"
        res["categoria_iva_codigo"] = "1"
    elif 32 in res["impuestos"]:
        # Inscripto en "IVA Exento" (idImpuesto=32).
        res["categoria_iva"] = "IVA SUJETO EXENTO"
        res["categoria_iva_codigo"] = "4"
    elif 33 in res["impuestos"]:
        # Inscripto en "IVA No Alcanzado" (idImpuesto=33).
        res["categoria_iva"] = "IVA NO ALCANZADO"
        res["categoria_iva_codigo"] = "15"
    # else: no hay datos → Consumidor Final / sin determinar. Dejamos
    # los campos en None para que el caller no pise nada.

    return res


def _empty_persona_dict():
    return {
        "id_persona": None,
        "tipo_persona": None,
        "tipo_clave": None,
        "estado_clave": None,
        "razon_social": None,
        "nombre": None,
        "apellido": None,
        "fecha_inscripcion": None,
        "fecha_fallecimiento": None,
        "fecha_cierre": None,
        "impuestos": [],
        "impuestos_detalle": [],
        "categorias_monotributo": [],
        "actividades": [],
        "domicilio_fiscal": None,
        "categoria_iva": None,
        "categoria_iva_codigo": None,
        "actividad_principal_id": None,
        "actividad_principal_descripcion": None,
        "forma_juridica": None,
    }


def _serialize_domicilio(dom, _g):
    """Normaliza un nodo `domicilio` (A13 lista) o `domicilioFiscal` (A5 dict).

    A13 manda `direccion` ya armado y CP como `codigoPostal`. A5 manda
    `calle` + `numero` separados y CP como `codigoPostal` también
    (cambió respecto a versiones viejas). Soportamos ambos.
    """
    return {
        "tipoDomicilio": _g(dom, "tipoDomicilio"),
        "calle": _g(dom, "direccion") or _g(dom, "calle"),
        "numero": _g(dom, "numero"),
        "localidad": _g(dom, "localidad"),
        "codPostal": _g(dom, "codigoPostal") or _g(dom, "codPostal"),
        "idProvincia": _g(dom, "idProvincia"),
        "descripcionProvincia": _g(dom, "descripcionProvincia"),
        "datoAdicional": _g(dom, "datoAdicional"),
    }
