# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Configuración ARBA WS por empresa.

Si `l10n_ar_arba_ws_enabled=True`, los crones bajan automáticamente el
padrón mensual desde el web service de ARBA.
"""
from odoo import _, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ar_arba_ws_enabled = fields.Boolean(
        string="Descarga padrón ARBA por WS",
        default=False,
        help=(
            "Activá esto SOLO si la empresa está adherida al régimen de "
            "Agentes de Recaudación de ARBA y tiene credenciales del DFE "
            "(Domicilio Fiscal Electrónico). Cuando está activo:\n\n"
            "• Cron mensual el 1° del mes 09:00 baja el padrón nuevo.\n"
            "• Si ARBA no responde, reintenta cada hora hasta 3 veces.\n"
            "• Si los 3 intentos fallan, queda visible un warning en\n"
            "  Configuración con el motivo del último error.\n"
            "• El padrón descargado se importa automáticamente y se\n"
            "  activa, reemplazando al anterior."
        ),
    )
    l10n_ar_arba_ws_user = fields.Char(
        string="Usuario ARBA DFE",
        help="Usuario del Domicilio Fiscal Electrónico de ARBA.",
        groups="account.group_account_manager",
    )
    l10n_ar_arba_ws_password = fields.Char(
        string="Password ARBA DFE",
        groups="account.group_account_manager",
    )
    l10n_ar_arba_ws_environment = fields.Selection(
        selection=[
            ("testing", "Testing (test.arba.gov.ar)"),
            ("production", "Producción (dfe.arba.gov.ar)"),
        ],
        default="production",
        string="Entorno ARBA",
        groups="account.group_account_manager",
    )
    l10n_ar_arba_ws_last_run = fields.Datetime(
        string="Última ejecución cron",
        readonly=True,
    )
    l10n_ar_arba_ws_last_status = fields.Selection(
        selection=[
            ("success", "Éxito"),
            ("retrying", "Reintentando"),
            ("failed", "Falló (3 intentos)"),
        ],
        readonly=True,
    )
    l10n_ar_arba_ws_last_error = fields.Char(
        string="Último error ARBA",
        readonly=True,
    )

    def action_l10n_ar_arba_ws_test(self):
        """Smoke manual: descarga el padrón del mes en curso."""
        self.ensure_one()
        rec = self.env["l10n_ar.padron.arba.import"].sudo().l10n_ar_arba_ws_download(
            self, triggered_by="manual",
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Padrón ARBA descargado"),
            "res_model": "l10n_ar.padron.arba.import",
            "res_id": rec.id if rec else False,
            "view_mode": "form",
            "target": "current",
        }

    def action_l10n_ar_view_arba_ws_log(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Log ARBA WS — %s") % self.name,
            "res_model": "l10n_ar.arba.ws.log",
            "view_mode": "list,form",
            "domain": [("company_id", "=", self.id)],
        }
