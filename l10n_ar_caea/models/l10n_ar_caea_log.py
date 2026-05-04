# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Modelo `l10n_ar.caea.log` — auditoría de llamadas WS CAEA.

Cada llamada al WS CAEA (solicitar, consultar, rendir, sin movimiento)
deja una entrada con:

  * event_type: 'solicitar' / 'consultar' / 'rendir' / 'sin_movimiento'
  * date: timestamp
  * success: True si AFIP respondió OK
  * message: resumen humano del resultado
  * error_code/error_msg: si AFIP devolvió error
  * xml_request/xml_response: para forensic (visible solo Account Manager)
  * caea_id: link al CAEA si aplica
  * affected_count: comprobantes afectados (rendiciones)

Sirve para:
  * Auditoría regulatoria (probarle a AFIP qué se mandó / cuándo)
  * Debugging cuando algo falla en cron silencioso
  * Vista de "última actividad CAEA" en el dashboard
"""
from odoo import _, fields, models


class L10nArCaeaLog(models.Model):
    _name = "l10n_ar.caea.log"
    _description = "CAEA — Log de llamadas WS"
    _order = "date desc, id desc"
    _rec_name = "display_name"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
    )
    caea_id = fields.Many2one(
        "l10n_ar.caea",
        string="CAEA",
        ondelete="set null",
        index=True,
    )
    date = fields.Datetime(
        string="Fecha/hora",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )
    event_type = fields.Selection(
        selection=[
            ("solicitar", "Solicitar CAEA"),
            ("consultar", "Consultar CAEA"),
            ("rendir", "Rendir comprobantes"),
            ("sin_movimiento", "Informar sin movimiento"),
        ],
        required=True,
        readonly=True,
    )
    success = fields.Boolean(string="OK", readonly=True, index=True)
    message = fields.Char(string="Resumen", readonly=True)
    error_code = fields.Char(readonly=True)
    error_msg = fields.Text(readonly=True)
    affected_count = fields.Integer(
        string="Cbtes afectados",
        readonly=True,
        help="Para rendiciones: cantidad de comprobantes informados.",
    )
    triggered_by = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("cron", "Cron"),
            ("post_fallback", "Fallback _post"),
        ],
        default="manual",
        readonly=True,
    )
    xml_request = fields.Text(
        string="XML enviado",
        readonly=True,
        groups="account.group_account_manager",
    )
    xml_response = fields.Text(
        string="XML recibido",
        readonly=True,
        groups="account.group_account_manager",
    )
    display_name = fields.Char(compute="_compute_display_name", store=False)

    def _compute_display_name(self):
        for rec in self:
            tag = "✅" if rec.success else "❌"
            rec.display_name = "%s %s · %s" % (
                tag, dict(self._fields["event_type"].selection).get(rec.event_type),
                rec.date and rec.date.strftime("%Y-%m-%d %H:%M") or "",
            )

    @classmethod
    def _record_event(cls, env, company, event_type, success, message="",
                      caea=None, error_code=None, error_msg=None,
                      affected_count=0, xml_request=None, xml_response=None,
                      triggered_by="manual"):
        """Helper para crear una entrada de log desde otros modelos."""
        return env["l10n_ar.caea.log"].sudo().create({
            "company_id": company.id,
            "caea_id": caea.id if caea else False,
            "event_type": event_type,
            "success": bool(success),
            "message": (message or "")[:255],
            "error_code": error_code or False,
            "error_msg": error_msg or False,
            "affected_count": int(affected_count or 0),
            "triggered_by": triggered_by,
            "xml_request": xml_request or False,
            "xml_response": xml_response or False,
        })
