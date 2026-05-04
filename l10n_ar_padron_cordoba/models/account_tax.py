# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Detección de taxes IIBB Córdoba por nombre — usa helper compartido."""
from odoo import models


class AccountTax(models.Model):
    _inherit = "account.tax"

    def _is_iibb_cordoba_tax(self):
        """True si el tax es percepción IIBB Rentas Córdoba."""
        return self._is_l10n_ar_iibb_tax_for_prefix("P. IIBB CBA")
