# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Wrappers en res.config.settings para los botones de la vista.

Los botones de los settings tienen que llamar métodos del mismo modelo
(res.config.settings), no directamente de res.company.
"""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ar_caea_enabled = fields.Boolean(
        related="company_id.l10n_ar_caea_enabled",
        readonly=False,
    )

    def action_l10n_ar_request_caea(self):
        self.ensure_one()
        return self.company_id.action_l10n_ar_request_caea()

    def action_l10n_ar_view_caea(self):
        self.ensure_one()
        return self.company_id.action_l10n_ar_view_caea()

    def action_l10n_ar_view_caea_log(self):
        self.ensure_one()
        return self.company_id.action_l10n_ar_view_caea_log()
