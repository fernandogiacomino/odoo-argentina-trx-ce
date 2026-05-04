# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Helper compartido para detectar taxes IIBB por jurisdicción.

Cada módulo provincial llama `_is_l10n_ar_iibb_tax_for_prefix(prefix)`
con su prefijo (`P. IIBB CABA`, `P. IIBB SF`, `P. IIBB CBA`, etc.) y
el helper devuelve True si el `display_name` empieza con ese prefijo.
"""
from odoo import models


class AccountTax(models.Model):
    _inherit = "account.tax"

    def _is_l10n_ar_iibb_tax_for_prefix(self, prefix):
        """True si el nombre del tax empieza con el prefijo dado.

        Reemplaza los flags `is_l10n_ar_padron_<jur>` que cada módulo
        definía por su cuenta. Reusa los templates oficiales de l10n_ar
        (`P. IIBB <PREFIX>`).
        """
        self.ensure_one()
        name = (self.display_name or "")
        return name.startswith(prefix)
