# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Activity ARCA default por empresa."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ar_arca_activity_id = fields.Many2one(
        "l10n_ar.arca.activity",
        string="Actividad ARCA principal",
        help=(
            "Actividad económica principal de la empresa según el "
            "nomenclador F-883. Se usa como default al generar IVA "
            "Simple si la cuenta contable no tiene actividad propia."
        ),
    )
