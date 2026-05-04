# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ar_mc_default_product_id = fields.Many2one(
        related="company_id.l10n_ar_mc_default_product_id",
        readonly=False,
    )
    l10n_ar_mc_default_purchase_journal_id = fields.Many2one(
        related="company_id.l10n_ar_mc_default_purchase_journal_id",
        readonly=False,
    )
