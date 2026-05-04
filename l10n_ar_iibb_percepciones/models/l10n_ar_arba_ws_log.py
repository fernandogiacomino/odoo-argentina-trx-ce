# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Log de cada llamada al WS ARBA — auditoría + debugging."""
from odoo import _, fields, models


class L10nArArbaWsLog(models.Model):
    _name = "l10n_ar.arba.ws.log"
    _description = "ARBA WS — Log"
    _order = "date desc, id desc"
    _rec_name = "display_name"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        index=True,
        default=lambda self: self.env.company,
    )
    date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    fecha_desde = fields.Date(readonly=True)
    fecha_hasta = fields.Date(readonly=True)
    success = fields.Boolean(readonly=True, index=True)
    attempt = fields.Integer(string="Intento #", default=1, readonly=True)
    triggered_by = fields.Selection(
        selection=[("cron", "Cron"), ("manual", "Manual")],
        default="cron",
        readonly=True,
    )
    error_code = fields.Char(readonly=True)
    error_type = fields.Char(string="Tipo error", readonly=True)
    error_msg = fields.Text(readonly=True)
    is_fatal = fields.Boolean(
        string="Fatal",
        readonly=True,
        help="True si el error requiere intervención humana — no se reintentará.",
    )
    file_size = fields.Integer(string="Tamaño ZIP (bytes)", readonly=True)
    import_id = fields.Many2one(
        "l10n_ar.padron.arba.import",
        string="Padrón importado",
        readonly=True,
    )
    request_xml = fields.Text(
        string="XML enviado",
        readonly=True,
        groups="account.group_account_manager",
    )
    response_zip = fields.Binary(
        string="ZIP descargado",
        attachment=True,
        readonly=True,
        groups="account.group_account_manager",
    )
    response_zip_filename = fields.Char(readonly=True)
    display_name = fields.Char(compute="_compute_display_name")

    def _compute_display_name(self):
        for rec in self:
            tag = "✅" if rec.success else "❌"
            rec.display_name = "%s ARBA WS · %s · attempt %s" % (
                tag, rec.date and rec.date.strftime("%Y-%m-%d %H:%M") or "",
                rec.attempt,
            )

    @classmethod
    def _record(cls, env, company, success, fecha_desde=None, fecha_hasta=None,
                attempt=1, triggered_by="cron",
                error_code=None, error_type=None, error_msg=None, is_fatal=False,
                file_size=0, import_id=None,
                request_xml=None, response_zip=None, response_zip_filename=None):
        return env["l10n_ar.arba.ws.log"].sudo().create({
            "company_id": company.id,
            "fecha_desde": fecha_desde or False,
            "fecha_hasta": fecha_hasta or False,
            "success": bool(success),
            "attempt": int(attempt),
            "triggered_by": triggered_by,
            "error_code": error_code or False,
            "error_type": error_type or False,
            "error_msg": (error_msg or "")[:1000] or False,
            "is_fatal": bool(is_fatal),
            "file_size": file_size or 0,
            "import_id": import_id or False,
            "request_xml": request_xml.decode("iso-8859-1") if isinstance(request_xml, bytes) else request_xml or False,
            "response_zip": response_zip or False,
            "response_zip_filename": response_zip_filename or False,
        })
