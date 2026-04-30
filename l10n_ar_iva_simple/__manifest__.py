# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina EDI — IVA Simple (4 CSV portal ARCA)",
    "version": "19.0.0.1.0",
    "category": "Accounting/Localizations/Reporting",
    "summary": "Genera los 4 CSV del régimen IVA Simple para upload manual al portal ARCA",
    "description": """
Réplica community del módulo enterprise `l10n_ar_reports_simple`.

Genera los 4 archivos CSV que el contribuyente sube manualmente al
portal ARCA "IVA Simple" (régimen abreviado para contribuyentes con
bajo volumen / Monotributo / RI sin Libro IVA Digital obligatorio):

* `DEBITO_<fecha>.csv`        — Ventas (FA-A/B/C/E + ND)
* `REST_DEBITO_<fecha>.csv`   — Ventas NC (out_refund)
* `CREDITO_<fecha>.csv`       — Compras (in_invoice)
* `REST_CREDITO_<fecha>.csv`  — Compras NC (in_refund)

Encoding latin-1, separador `;`, decimales con coma (formato AFIP).

Spec oficial:
https://www.afip.gob.ar/iva/responsables-inscriptos/ayuda/manuales.asp

Inspirado (no copiado) en odoo/enterprise/l10n_ar_reports_simple v19.
Diferencias intencionales con enterprise:

* La **actividad** se ingresa en el wizard (community no tiene
  `l10n_ar_arca_activity_id` en `account.account`/`res.company`).
* Los tags `tag_fixed_asset_account` y `tag_leases_rentals_account` se
  crean como data del módulo (este es el flag que distingue Bienes de
  Uso vs Locaciones vs Productos en el campo Concepto).
* Sin dependencia con `account_reports` enterprise (todo via SQL plano
  + lib pura).
    """,
    "author": "Trixocom",
    "website": "https://trixocom.com",
    "license": "LGPL-3",
    "depends": [
        # l10n_ar_libro_iva_digital aporta el menú padre Argentina y la
        # vista SQL account.ar.vat.line (no la usamos directamente, pero
        # garantiza coherencia conceptual: ambos módulos viven juntos).
        "l10n_ar_libro_iva_digital",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/account_account_tag_data.xml",
        "wizards/iva_simple_wizard_view.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
