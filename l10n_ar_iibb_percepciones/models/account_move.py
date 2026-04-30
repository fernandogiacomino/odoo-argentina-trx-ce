# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Aplicación automática de percepción IIBB ARBA en facturas salientes.

Flujo:

1. Al cambiar `partner_id` o `invoice_date`, se consulta el padrón ARBA.
2. Si el partner está en el padrón con alícuota > 0:
   - Se busca el `account.tax` con `l10n_ar_padron_jurisdiction='arba'`
     y `type_tax_use='sale'` que ya tiene esa alícuota como `amount`.
   - Si no existe un tax con esa alícuota exacta, lo creamos en runtime
     basándonos en un "template" identificado por `l10n_ar_padron_jurisdiction`.
   - Se agrega ese tax a todas las invoice_line_ids que NO lo tienen.
3. Si el partner ya NO está en padrón pero tenía un tax ARBA, lo quitamos.

Esto NO toca facturas posted — solo borradores.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ar_arba_aliquot_applied = fields.Float(
        string="Alícuota IIBB ARBA aplicada (%)",
        compute="_compute_l10n_ar_arba_aliquot_applied",
        store=False,
        digits=(5, 2),
        help="Alícuota IIBB de Buenos Aires que se está aplicando en "
             "esta factura, según el padrón ARBA vigente.",
    )

    @api.depends("invoice_line_ids.tax_ids", "invoice_line_ids.tax_ids.amount",
                 "invoice_line_ids.tax_ids.l10n_ar_padron_jurisdiction")
    def _compute_l10n_ar_arba_aliquot_applied(self):
        for move in self:
            arba_taxes = move.invoice_line_ids.tax_ids.filtered(
                lambda t: t.l10n_ar_padron_jurisdiction == "arba"
            )
            move.l10n_ar_arba_aliquot_applied = (
                arba_taxes[:1].amount if arba_taxes else 0.0
            )

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    @api.onchange("partner_id", "invoice_date")
    def _onchange_l10n_ar_arba_apply(self):
        """Aplica/quita percepción IIBB ARBA según el padrón."""
        if self.state != "draft":
            return
        if self.move_type not in ("out_invoice", "out_refund"):
            return
        if (self.country_code or self.company_id.country_id.code) != "AR":
            return
        self._l10n_ar_arba_apply_perception()

    def _l10n_ar_arba_apply_perception(self):
        """Aplica/quita el tax de percepción ARBA en todas las líneas."""
        self.ensure_one()
        company = self.company_id or self.env.company
        date_ref = self.invoice_date or fields.Date.context_today(self)
        Padron = self.env["l10n_ar.padron.arba.alicuota"]
        Tax = self.env["account.tax"]

        # 1) Buscar alícuota vigente del partner en el padrón.
        row = Padron.find_for_cuit(
            self.partner_id.vat, date_ref=date_ref, company=company,
        )
        target_aliquot = row.aliquot_perception if row else 0.0

        # 2) Buscar el tax ARBA con esa alícuota (o ningún ARBA si =0).
        existing_arba = Tax.search([
            ("type_tax_use", "=", "sale"),
            ("l10n_ar_padron_jurisdiction", "=", "arba"),
            ("company_id", "=", company.id),
        ])
        target_tax = (
            existing_arba.filtered(lambda t: t.amount == target_aliquot)[:1]
            if target_aliquot > 0 else Tax.browse()
        )

        # 3) Si necesitamos un tax nuevo (no existe el de esa alícuota), lo
        #    creamos clonando uno existente del jurisdiction ARBA.
        if target_aliquot > 0 and not target_tax:
            template = existing_arba[:1]
            if template:
                target_tax = template.copy({
                    "name": "Percepción IIBB BA %.2f%%" % target_aliquot,
                    "amount": target_aliquot,
                })
                _logger.info(
                    "Creado nuevo tax IIBB BA %.2f%% (id=%s) clonando id=%s",
                    target_aliquot, target_tax.id, template.id,
                )

        # 4) Aplicar a las líneas. Sacamos cualquier ARBA viejo y ponemos
        #    el correcto (o ninguno si target_aliquot == 0).
        for line in self.invoice_line_ids:
            current_arba = line.tax_ids.filtered(
                lambda t: t.l10n_ar_padron_jurisdiction == "arba"
            )
            new_taxes = line.tax_ids - current_arba
            if target_tax:
                new_taxes = new_taxes | target_tax
            if line.tax_ids != new_taxes:
                line.tax_ids = [(6, 0, new_taxes.ids)]
