# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Helper en `res.partner` para resolver alícuota IIBB del padrón."""
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ar_arba_aliquot_perception = fields.Float(
        string="Alícuota percepción IIBB BA (%)",
        compute="_compute_l10n_ar_arba_aliquot",
        store=False,
        digits=(5, 2),
        help="Alícuota vigente hoy para este CUIT en el padrón ARBA "
             "activo. Solo informativo — la alícuota efectiva al emitir "
             "una factura se calcula a la fecha de la factura.",
    )
    l10n_ar_arba_aliquot_retention = fields.Float(
        string="Alícuota retención IIBB BA (%)",
        compute="_compute_l10n_ar_arba_aliquot",
        store=False,
        digits=(5, 2),
    )
    l10n_ar_arba_in_padron = fields.Boolean(
        string="En padrón ARBA",
        compute="_compute_l10n_ar_arba_aliquot",
        store=False,
    )

    @api.depends("vat", "company_id")
    def _compute_l10n_ar_arba_aliquot(self):
        Padron = self.env["l10n_ar.padron.arba.alicuota"]
        today = fields.Date.context_today(self)
        for p in self:
            row = Padron.find_for_cuit(
                p.vat, date_ref=today,
                company=p.company_id or self.env.company,
            )
            p.l10n_ar_arba_in_padron = bool(row)
            p.l10n_ar_arba_aliquot_perception = row.aliquot_perception if row else 0.0
            p.l10n_ar_arba_aliquot_retention = row.aliquot_retention if row else 0.0
