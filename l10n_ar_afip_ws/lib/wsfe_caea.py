# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Métodos CAEA del WSFEv1 — Código de Autorización Electrónico Anticipado.

CAEA es el régimen de contingencia de AFIP/ARCA: en lugar de pedir un CAE
en tiempo real al emitir cada comprobante (que requiere conexión activa),
se solicita por anticipado un código (CAEA) válido para una **quincena**:

    Período 1: del 1 al 15 del mes (orden=1)
    Período 2: del 16 al fin del mes (orden=2)

El CAEA se solicita dentro de los **5 días previos** al inicio de la
quincena. Una vez asignado, todos los comprobantes emitidos en esa
quincena pueden usar ese CAEA — útil cuando WSFEv1 está caído / hay
problemas de red — y deben **rendirse** a AFIP dentro de los **8 días
corridos** posteriores al cierre de la quincena vía
``FECAEARegInformativo``.

Si la company no emitió ningún comprobante con un CAEA en su quincena,
debe informarlo con ``FECAEASinMovimientoInformar`` antes del cierre.

Métodos del WSDL (WSFEv1):

    FECAEASolicitar(auth, periodo, orden)
    FECAEAConsultar(auth, periodo, orden)
    FECAEARegInformativo(auth, FeCAEARegInfReq)
    FECAEASinMovimientoInformar(auth, periodo, cuit_pto_vta)
    FECAEASinMovimientoConsultar(auth)

Spec: https://www.afip.gob.ar/fe/documentos/manual_desarrollador_COMPG_v4.pdf
(secciones 4.2, 4.3, 4.4, 4.5, 4.6).

Lib pura — no importa ``odoo.``. Reusa el WSDL del WSFEv1 estándar.
"""
import logging

from zeep.exceptions import Fault, TransportError as ZeepTransportError

from . import errors
from .wsfe import _auth, _build_client, _check_errors  # reusable helpers

_logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Solicitud / consulta
# ----------------------------------------------------------------------
def caea_solicitar(auth, periodo, orden, environment, transport):
    """`FECAEASolicitar` — pide un CAEA para una quincena.

    :param auth: dict {token, sign, cuit}.
    :param periodo: ``YYYYMM`` (string o int).
    :param orden: 1 (primera quincena) o 2 (segunda).
    :return: dict {
        caea: '12345678901234',
        periodo: 'YYYYMM',
        orden: 1|2,
        fch_vig_desde: 'YYYYMMDD',
        fch_vig_hasta: 'YYYYMMDD',
        fch_topea_inf: 'YYYYMMDD',  # límite para rendir
        fch_proceso: 'YYYYMMDD',
        observaciones: list,
        errors: list,
    }.
    """
    client = _build_client(environment, transport)
    try:
        r = client.service.FECAEASolicitar(
            Auth=_auth(auth["cuit"], auth["token"], auth["sign"]),
            Periodo=str(periodo),
            Orden=int(orden),
        )
    except Fault as f:
        raise errors.WsfeError(code="fault", message="FECAEASolicitar fault: %s" % f)
    except ZeepTransportError as e:
        raise errors.TransportError(message="FECAEASolicitar transport: %s" % e)

    _check_errors(r, "FECAEASolicitar")
    result_get = getattr(r, "ResultGet", None) or r
    return {
        "caea": getattr(result_get, "CAEA", None),
        "periodo": getattr(result_get, "Periodo", None),
        "orden": getattr(result_get, "Orden", None),
        "fch_vig_desde": getattr(result_get, "FchVigDesde", None),
        "fch_vig_hasta": getattr(result_get, "FchVigHasta", None),
        "fch_topea_inf": getattr(result_get, "FchTopeInf", None),
        "fch_proceso": getattr(result_get, "FchProceso", None),
        "observaciones": _serialize_obs(getattr(result_get, "Observaciones", None)),
        "errors": getattr(r, "Errors", None),
    }


def caea_consultar(auth, periodo, orden, environment, transport):
    """`FECAEAConsultar` — devuelve el CAEA vigente para esa quincena
    si ya fue solicitado, o errores si no existe."""
    client = _build_client(environment, transport)
    try:
        r = client.service.FECAEAConsultar(
            Auth=_auth(auth["cuit"], auth["token"], auth["sign"]),
            Periodo=str(periodo),
            Orden=int(orden),
        )
    except Fault as f:
        raise errors.WsfeError(code="fault", message="FECAEAConsultar fault: %s" % f)
    except ZeepTransportError as e:
        raise errors.TransportError(message="FECAEAConsultar transport: %s" % e)

    _check_errors(r, "FECAEAConsultar")
    result_get = getattr(r, "ResultGet", None) or r
    return {
        "caea": getattr(result_get, "CAEA", None),
        "periodo": getattr(result_get, "Periodo", None),
        "orden": getattr(result_get, "Orden", None),
        "fch_vig_desde": getattr(result_get, "FchVigDesde", None),
        "fch_vig_hasta": getattr(result_get, "FchVigHasta", None),
        "fch_topea_inf": getattr(result_get, "FchTopeInf", None),
        "fch_proceso": getattr(result_get, "FchProceso", None),
    }


# ----------------------------------------------------------------------
# Rendición informativa de comprobantes emitidos con CAEA
# ----------------------------------------------------------------------
def caea_reg_informativo(auth, fe_caea_reg_inf_req, environment, transport):
    """`FECAEARegInformativo` — informa los comprobantes emitidos con CAEA.

    :param fe_caea_reg_inf_req: dict con shape:

        .. code-block:: python

            {
                "FeCabReq": {
                    "CantReg": 1,           # cantidad de comprobantes
                    "PtoVta": 1001,
                    "CbteTipo": 1,
                },
                "FeDetReq": [
                    {
                        "FECAEADetRequest": {
                            "Concepto": 1,
                            "DocTipo": 80,
                            "DocNro": 30000000007,
                            "CbteDesde": 1, "CbteHasta": 1,
                            "CbteFch": "20260403",
                            "ImpTotal": 121.00,
                            ...todo igual a FECAESolicitar...
                            "CAEA": "12345678901234",
                            "CbteFchHsGen": "20260403080000",  # opcional
                        },
                    },
                ],
            }

    :return: dict similar a `cae_solicitar` con `Resultado`/`CAEA`/
        observaciones/errores por cada comprobante.
    """
    client = _build_client(environment, transport)
    try:
        r = client.service.FECAEARegInformativo(
            Auth=_auth(auth["cuit"], auth["token"], auth["sign"]),
            FeCAEARegInfReq=fe_caea_reg_inf_req,
        )
    except Fault as f:
        raise errors.WsfeError(code="fault", message="FECAEARegInformativo fault: %s" % f)
    except ZeepTransportError as e:
        raise errors.TransportError(message="FECAEARegInformativo transport: %s" % e)

    _check_errors(r, "FECAEARegInformativo")
    cabecera = getattr(r, "FeCabResp", None)
    detalle_root = getattr(r, "FeDetResp", None)
    detalle_list = []
    if detalle_root is not None:
        items = getattr(detalle_root, "FECAEADetResponse", None) or []
        if not isinstance(items, list):
            items = [items]
        for it in items:
            obs_root = getattr(it, "Observaciones", None)
            detalle_list.append({
                "Concepto": getattr(it, "Concepto", None),
                "DocTipo": getattr(it, "DocTipo", None),
                "DocNro": getattr(it, "DocNro", None),
                "CbteDesde": getattr(it, "CbteDesde", None),
                "CbteHasta": getattr(it, "CbteHasta", None),
                "CbteFch": getattr(it, "CbteFch", None),
                "Resultado": getattr(it, "Resultado", None),
                "CAEA": getattr(it, "CAEA", None),
                "Observaciones": _serialize_obs(obs_root),
            })
    return {
        "cabecera": {
            "Cuit": getattr(cabecera, "Cuit", None) if cabecera else None,
            "PtoVta": getattr(cabecera, "PtoVta", None) if cabecera else None,
            "CbteTipo": getattr(cabecera, "CbteTipo", None) if cabecera else None,
            "FchProceso": getattr(cabecera, "FchProceso", None) if cabecera else None,
            "CantReg": getattr(cabecera, "CantReg", None) if cabecera else None,
            "Resultado": getattr(cabecera, "Resultado", None) if cabecera else None,
            "Reproceso": getattr(cabecera, "Reproceso", None) if cabecera else None,
        },
        "detalle": detalle_list,
        "errors": getattr(r, "Errors", None),
        "events": getattr(r, "Events", None),
    }


# ----------------------------------------------------------------------
# Sin movimientos
# ----------------------------------------------------------------------
def caea_sin_movimiento_informar(auth, pto_vta, caea, environment, transport):
    """`FECAEASinMovimientoInformar` — informa que un punto de venta no
    emitió comprobantes con un CAEA dado."""
    client = _build_client(environment, transport)
    try:
        r = client.service.FECAEASinMovimientoInformar(
            Auth=_auth(auth["cuit"], auth["token"], auth["sign"]),
            PtoVta=int(pto_vta),
            CAEA=str(caea),
        )
    except Fault as f:
        raise errors.WsfeError(
            code="fault", message="FECAEASinMovimientoInformar fault: %s" % f,
        )
    except ZeepTransportError as e:
        raise errors.TransportError(
            message="FECAEASinMovimientoInformar transport: %s" % e,
        )
    _check_errors(r, "FECAEASinMovimientoInformar")
    return {
        "resultado": getattr(r, "Resultado", None),
        "fch_proceso": getattr(r, "FchProceso", None),
        "caea": getattr(r, "CAEA", None),
        "errors": getattr(r, "Errors", None),
    }


def caea_sin_movimiento_consultar(auth, environment, transport):
    """`FECAEASinMovimientoConsultar` — consulta el estado de las
    rendiciones sin movimiento."""
    client = _build_client(environment, transport)
    try:
        r = client.service.FECAEASinMovimientoConsultar(
            Auth=_auth(auth["cuit"], auth["token"], auth["sign"]),
        )
    except Fault as f:
        raise errors.WsfeError(
            code="fault", message="FECAEASinMovimientoConsultar fault: %s" % f,
        )
    except ZeepTransportError as e:
        raise errors.TransportError(
            message="FECAEASinMovimientoConsultar transport: %s" % e,
        )
    _check_errors(r, "FECAEASinMovimientoConsultar")
    return {"raw": _serialize_root(r)}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _serialize_obs(obs):
    if not obs:
        return []
    items = getattr(obs, "Obs", None) or []
    if not isinstance(items, list):
        items = [items]
    return [{"code": getattr(o, "Code", None), "msg": getattr(o, "Msg", None)} for o in items]


def _serialize_root(o):
    if o is None:
        return None
    return {
        k: getattr(o, k, None)
        for k in dir(o)
        if not k.startswith("_") and not callable(getattr(o, k, None))
    }
