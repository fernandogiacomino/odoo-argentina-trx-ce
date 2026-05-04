# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ar_arba_ws_enabled = fields.Boolean(
        related="company_id.l10n_ar_arba_ws_enabled",
        readonly=False,
    )
    l10n_ar_arba_ws_user = fields.Char(
        related="company_id.l10n_ar_arba_ws_user",
        readonly=False,
    )
    l10n_ar_arba_ws_password = fields.Char(
        related="company_id.l10n_ar_arba_ws_password",
        readonly=False,
    )
    l10n_ar_arba_ws_environment = fields.Selection(
        related="company_id.l10n_ar_arba_ws_environment",
        readonly=False,
    )
    l10n_ar_arba_ws_last_run = fields.Datetime(
        related="company_id.l10n_ar_arba_ws_last_run",
    )
    l10n_ar_arba_ws_last_status = fields.Selection(
        related="company_id.l10n_ar_arba_ws_last_status",
    )
    l10n_ar_arba_ws_last_error = fields.Char(
        related="company_id.l10n_ar_arba_ws_last_error",
    )

    def action_l10n_ar_arba_ws_test(self):
        """Guarda los settings PRIMERO (los related no persisten hasta
        que se hace 'Save'), después invoca el test contra ARBA."""
        self.ensure_one()
        # Persistir el form de settings — escribe los related en company.
        self.execute()
        return self.company_id.action_l10n_ar_arba_ws_test()

    def action_l10n_ar_view_arba_ws_log(self):
        self.ensure_one()
        return self.company_id.action_l10n_ar_view_arba_ws_log()
