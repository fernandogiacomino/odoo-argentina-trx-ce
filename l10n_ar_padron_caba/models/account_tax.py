# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Detección de taxes IIBB CABA por nombre.

Usa el helper compartido `_is_l10n_ar_iibb_tax_for_prefix` definido
en `l10n_ar_padron_base`. Acá solo wiring con el prefijo CABA.
"""
from odoo import models


class AccountTax(models.Model):
    _inherit = "account.tax"

    def _is_iibb_caba_tax(self):
        """True si el tax es percepción IIBB CABA."""
        return self._is_l10n_ar_iibb_tax_for_prefix("P. IIBB CABA")
