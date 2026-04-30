# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Specs de los registros del Libro IVA Digital RG 5616.

Cada función ``build_*_record`` recibe un dict con los datos crudos y
devuelve un string de longitud fija, listo para concatenar en el TXT.

Validamos en cada función con ``assert len(s) == EXPECTED_LEN`` para
que un bug de formatting falle ruidosamente en tests, no en producción
cuando AFIP rechace el TXT.
"""
from . import txt_format as f


# Longitudes oficiales (validadas contra fixtures enterprise + nimarosa).
LEN_VENTAS_CBTE = 266
LEN_COMPRAS_CBTE = 325
LEN_VENTAS_ALICUOTAS = 62
LEN_COMPRAS_ALICUOTAS = 84


def build_ventas_cbte_record(d):
    """REGINFO_CV_VENTAS_CBTE — 266 chars.

    `d` debe tener (todas las longitudes manejadas internamente):
        fecha (date), tipo_cbte (int), pto_vta (int), nro_cbte (int),
        nro_cbte_hasta (int), cod_doc_comprador (str|int), nro_doc (str),
        razon_social (str), imp_total (Decimal), imp_no_gravado (Decimal),
        perc_no_categ (Decimal), imp_exento (Decimal),
        perc_nacionales (Decimal), perc_iibb (Decimal),
        perc_municipales (Decimal), imp_internos (Decimal),
        cod_moneda (str, 'PES'/'DOL'), tipo_cambio (Decimal),
        cant_alicuotas (int), cod_operacion (str, 1 char),
        otros_tributos (Decimal), venc_pago (date|None).
    """
    parts = [
        f.fmt_date(d["fecha"]),                                # 8
        f.fmt_int(d["tipo_cbte"], 3),                          # 3
        f.fmt_int(d["pto_vta"], 5),                            # 5
        f.fmt_int(d["nro_cbte"], 20),                          # 20
        f.fmt_int(d.get("nro_cbte_hasta") or d["nro_cbte"], 20),  # 20
        f.fmt_int(d["cod_doc_comprador"], 2),                  # 2
        f.fmt_cuit(d["nro_doc"], 20),                          # 20
        f.fmt_text(d["razon_social"], 30),                     # 30
        f.fmt_amount(d["imp_total"], 15, 2),                   # 15
        f.fmt_amount(d.get("imp_no_gravado", 0), 15, 2),       # 15
        f.fmt_amount(d.get("perc_no_categ", 0), 15, 2),        # 15
        f.fmt_amount(d.get("imp_exento", 0), 15, 2),           # 15
        f.fmt_amount(d.get("perc_nacionales", 0), 15, 2),      # 15
        f.fmt_amount(d.get("perc_iibb", 0), 15, 2),            # 15
        f.fmt_amount(d.get("perc_municipales", 0), 15, 2),     # 15
        f.fmt_amount(d.get("imp_internos", 0), 15, 2),         # 15
        f.fmt_text(d.get("cod_moneda") or "PES", 3),           # 3
        f.fmt_cotizacion(d.get("tipo_cambio") or 1, 10, 6),    # 10
        f.fmt_int(d["cant_alicuotas"], 1),                     # 1
        f.fmt_text(d.get("cod_operacion") or " ", 1),          # 1
        f.fmt_amount(d.get("otros_tributos", 0), 15, 2),       # 15
        f.fmt_date(d.get("venc_pago")),                        # 8
    ]
    rec = "".join(parts)
    assert len(rec) == LEN_VENTAS_CBTE, (
        "VENTAS_CBTE: longitud %d != %d esperado. Partes: %s"
        % (len(rec), LEN_VENTAS_CBTE, [len(p) for p in parts])
    )
    return rec


def build_compras_cbte_record(d):
    """REGINFO_CV_COMPRAS_CBTE — 325 chars.

    Diferencias vs ventas:
        - `cod_doc_vendedor` (no comprador).
        - + `despacho_importacion` (16) — solo si tipo_cbte=66, sino spaces.
        - + `credito_fiscal_computable` (15) — IVA realmente computable.
        - + `cuit_emisor_corredor` (11), `denominacion_corredor` (30),
            `iva_comision` (15).
        - venc_pago al final igual que ventas.
    """
    parts = [
        f.fmt_date(d["fecha"]),                                # 8
        f.fmt_int(d["tipo_cbte"], 3),                          # 3
        f.fmt_int(d["pto_vta"], 5),                            # 5
        f.fmt_int(d["nro_cbte"], 20),                          # 20
        f.fmt_text(d.get("despacho_importacion") or "", 16),   # 16
        f.fmt_int(d["cod_doc_vendedor"], 2),                   # 2
        f.fmt_cuit(d["nro_doc"], 20),                          # 20
        f.fmt_text(d["razon_social"], 30),                     # 30
        f.fmt_amount(d["imp_total"], 15, 2),                   # 15
        f.fmt_amount(d.get("imp_no_gravado", 0), 15, 2),       # 15
        f.fmt_amount(d.get("imp_exento", 0), 15, 2),           # 15
        f.fmt_amount(d.get("perc_no_categ", 0), 15, 2),        # 15
        f.fmt_amount(d.get("imp_internos", 0), 15, 2),         # 15
        f.fmt_amount(d.get("perc_iibb", 0), 15, 2),            # 15
        f.fmt_amount(d.get("perc_municipales", 0), 15, 2),     # 15
        f.fmt_amount(d.get("perc_nacionales", 0), 15, 2),      # 15
        f.fmt_text(d.get("cod_moneda") or "PES", 3),           # 3
        f.fmt_cotizacion(d.get("tipo_cambio") or 1, 10, 6),    # 10
        f.fmt_int(d["cant_alicuotas"], 1),                     # 1
        f.fmt_text(d.get("cod_operacion") or " ", 1),          # 1
        f.fmt_amount(d.get("credito_fiscal_computable", 0), 15, 2),  # 15
        f.fmt_amount(d.get("otros_tributos", 0), 15, 2),       # 15
        f.fmt_cuit(d.get("cuit_emisor_corredor") or "", 11),   # 11
        f.fmt_text(d.get("denominacion_corredor") or "", 30),  # 30
        f.fmt_amount(d.get("iva_comision", 0), 15, 2),         # 15
    ]
    rec = "".join(parts)
    assert len(rec) == LEN_COMPRAS_CBTE, (
        "COMPRAS_CBTE: longitud %d != %d esperado. Partes: %s"
        % (len(rec), LEN_COMPRAS_CBTE, [len(p) for p in parts])
    )
    return rec


def build_ventas_alicuotas_record(d):
    """REGINFO_CV_VENTAS_CBTE_ALICUOTAS — 62 chars.

    Una línea por (cbte, alícuota IVA). Si la factura tiene IVA 21% y 10.5%,
    salen dos líneas en este TXT (con la misma factura).
    """
    parts = [
        f.fmt_int(d["tipo_cbte"], 3),                          # 3
        f.fmt_int(d["pto_vta"], 5),                            # 5
        f.fmt_int(d["nro_cbte"], 20),                          # 20
        f.fmt_amount(d["neto_gravado"], 15, 2),                # 15
        f.fmt_alicuota(d["alicuota"], 4, 2),                   # 4
        f.fmt_amount(d["iva_liquidado"], 15, 2),               # 15
    ]
    rec = "".join(parts)
    assert len(rec) == LEN_VENTAS_ALICUOTAS, (
        "VENTAS_ALICUOTAS: longitud %d != %d. Partes: %s"
        % (len(rec), LEN_VENTAS_ALICUOTAS, [len(p) for p in parts])
    )
    return rec


def build_compras_alicuotas_record(d):
    """REGINFO_CV_COMPRAS_CBTE_ALICUOTAS — 84 chars.

    Una línea por (cbte, alícuota IVA), con doc del vendedor.
    """
    parts = [
        f.fmt_int(d["tipo_cbte"], 3),                          # 3
        f.fmt_int(d["pto_vta"], 5),                            # 5
        f.fmt_int(d["nro_cbte"], 20),                          # 20
        f.fmt_int(d["cod_doc_vendedor"], 2),                   # 2
        f.fmt_cuit(d["nro_doc"], 20),                          # 20
        f.fmt_amount(d["neto_gravado"], 15, 2),                # 15
        f.fmt_alicuota(d["alicuota"], 4, 2),                   # 4
        f.fmt_amount(d["iva_liquidado"], 15, 2),               # 15
    ]
    rec = "".join(parts)
    assert len(rec) == LEN_COMPRAS_ALICUOTAS, (
        "COMPRAS_ALICUOTAS: longitud %d != %d. Partes: %s"
        % (len(rec), LEN_COMPRAS_ALICUOTAS, [len(p) for p in parts])
    )
    return rec


# ----------------------------------------------------------------------
# Mapeo IVA Id AFIP → porcentaje (catalogo oficial)
# ----------------------------------------------------------------------
#: Catálogo AFIP de alícuotas IVA (campo `Id` de FECAESolicitar.IvaItem).
AFIP_IVA_ID_TO_PERCENT = {
    "3": 0.0,    # 0%
    "4": 10.5,   # 10,5%
    "5": 21.0,   # 21%
    "6": 27.0,   # 27%
    "8": 5.0,    # 5%
    "9": 2.5,    # 2,5%
}


#: Códigos AFIP de tipo de comprobante que son **NC** exclusivamente
#: (no se usan también para facturas). Para estos, NO invertimos signo
#: cuando es out_refund / in_refund — el tipo de cbte ya indica que es NC.
NC_DOC_CODES = {3, 8, 13, 21, 41, 53, 113, 118}
