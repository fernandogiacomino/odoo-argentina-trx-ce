# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina IIBB — Padrones (base compartida)",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "summary": "Helpers compartidos por los módulos de padrones IIBB provinciales",
    "description": """
Helpers comunes para los módulos de padrones IIBB de jurisdicciones
argentinas (ARBA, AGIP, API Santa Fe, Rentas Córdoba).

Provee:

* `account.tax._is_l10n_ar_iibb_tax_for_prefix(prefix)` — detección
  por nombre de tax (`'P. IIBB <PREFIX>'`).
* `account.move._l10n_ar_resolve_iibb_tax(company, percent, prefix)` —
  busca el tax con `<prefix> <X>%` o lo crea clonando `<prefix> 0%`
  oficial de l10n_ar. Auto-activa templates inactivos.

Los módulos por jurisdicción (`l10n_ar_padron_caba`, `_santafe`,
`_cordoba`, `l10n_ar_iibb_percepciones`) dependen de este y reusan
los helpers — eliminando ~150 líneas de duplicación.

No agrega modelos ni vistas. Solo código.
    """,
    "author": "Trixocom",
    "website": "https://trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar",
        "account",
    ],
    "data": [],
    "installable": True,
    "application": False,
    "auto_install": False,
}
