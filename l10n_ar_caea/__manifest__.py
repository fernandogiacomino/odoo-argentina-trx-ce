# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina EDI — CAEA y Clase M",
    "version": "19.0.0.1.0",
    "category": "Accounting/Localizations/EDI",
    "summary": "CAEA (autorización anticipada) y comprobantes clase M",
    "description": """
Soporta el Código de Autorización Electrónico Anticipado (CAEA) de AFIP
para emisión offline en casos de contingencia.

Flujo CAEA:

1. Solicitud mensual al WS `wsfev1.CAEASolicitar`.
2. Emisión de comprobantes con el CAEA sin conexión a AFIP.
3. Rendición dentro de los 5/10 días hábiles siguientes vía
   `wsfev1.CAEARegInformativo`.

También soporta comprobantes clase M, emitidos por contribuyentes recién
inscriptos o con observaciones en el padrón AFIP.

Fase 4 — requiere que las fases 1–3 estén estables.
    """,
    "author": "Trixocom",
    "website": "https://trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar_edi",
    ],
    "data": [
        # "security/ir.model.access.csv",
        # "views/caea_view.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
