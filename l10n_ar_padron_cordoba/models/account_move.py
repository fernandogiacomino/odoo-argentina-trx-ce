# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Aplicación automática de Percepción IIBB Córdoba en account.move.

Reusa el template oficial **"P. IIBB CBA 0%"** y los helpers compartidos
de `l10n_ar_padron_base`.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TAX_PREFIX = "P. IIBB CBA"


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.onchange("partner_id", "invoice_date")
    def _onchange_partner_l10n_ar_cordoba(self):
        for move in self:
            if move.move_type not in ("out_invoice", "out_refund"):
                continue
            move._l10n_ar_apply_padron_cordoba()

    def _l10n_ar_apply_padron_cordoba(self):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund"):
            return
        partner = self.commercial_partner_id or self.partner_id
        if not partner.vat:
            return

        target_date = self.invoice_date or fields.Date.context_today(self)
        alic = self.env["l10n_ar.padron.cordoba.alicuota"].sudo().find_for(
            partner.vat, target_date=target_date, company=self.company_id,
        )

        if alic and alic.aliquot_perception > 0:
            tax = self._l10n_ar_resolve_iibb_tax(
                self.company_id, alic.aliquot_perception, TAX_PREFIX,
            )
            if not tax:
                _logger.warning(
                    "No se encontró template '%s 0%%' en %s — no aplica padrón CBA.",
                    TAX_PREFIX, self.company_id.name,
                )
                return
            self._l10n_ar_apply_iibb_to_lines(TAX_PREFIX, tax)
        else:
            self._l10n_ar_apply_iibb_to_lines(TAX_PREFIX, target_tax=False)

    def _post(self, soft=True):
        for move in self.filtered(lambda m: m.move_type in ("out_invoice", "out_refund")):
            try:
                move._l10n_ar_apply_padron_cordoba()
            except Exception as e:
                _logger.warning("Padron CBA: %s", e)
        return super()._post(soft=soft)
