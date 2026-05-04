# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Acceso directo desde el partner a su alícuota AGIP vigente.

`l10n_ar_padron_agip_alicuota_id`: computado on-the-fly. No store —
cambia con cada padrón mensual nuevo.
"""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    l10n_ar_padron_agip_alicuota_id = fields.Many2one(
        "l10n_ar.padron.agip.alicuota",
        compute="_compute_l10n_ar_padron_agip_alicuota_id",
        string="Alícuota AGIP CABA",
        compute_sudo=True,
        search="_search_l10n_ar_padron_agip_alicuota_id",
    )

    def _compute_l10n_ar_padron_agip_alicuota_id(self):
        Alic = self.env["l10n_ar.padron.agip.alicuota"].sudo()
        for partner in self:
            if not partner.vat:
                partner.l10n_ar_padron_agip_alicuota_id = False
                continue
            partner.l10n_ar_padron_agip_alicuota_id = Alic.find_for(partner.vat)

    def _search_l10n_ar_padron_agip_alicuota_id(self, operator, value):
        # Searchable stub: nunca se usa para query real. Devuelve domain
        # vacío para que Odoo no se queje del field como dependency.
        return [("id", "!=", False)] if value else [("id", "=", False)]
