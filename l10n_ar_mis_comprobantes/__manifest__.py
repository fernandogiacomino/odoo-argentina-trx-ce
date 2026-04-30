# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina EDI — Cotejo Mis Comprobantes",
    "version": "19.0.0.1.0",
    "category": "Accounting/Localizations/Reporting",
    "summary": "Importa Mis Comprobantes y coteja diferencias con Odoo",
    "description": """
Importa archivos XLS/CSV descargados del portal "Mis Comprobantes" de
AFIP/ARCA y los coteja contra los asientos registrados en Odoo.

Genera un reporte de diferencias:

* Comprobantes que están en AFIP pero no en Odoo (facturas perdidas o no
  contabilizadas aún).
* Comprobantes que están en Odoo pero no en AFIP (emisiones que fallaron y
  no fueron detectadas en el momento).
* Diferencias de monto o fecha entre los dos sistemas.

Útil como control mensual complementario al Libro IVA Digital.
    """,
    "author": "Trixocom",
    "website": "https://trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar_edi",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "data": [
        # "security/ir.model.access.csv",
        # "wizards/mis_comprobantes_import_wizard_view.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
