# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Helper compartido para resolver y aplicar taxes IIBB en account.move.

Cada jurisdicción provincial usa una variante de:

  if alic.percent > 0:
      tax = self._l10n_ar_resolve_iibb_tax(company, percent, prefix)
      apply tax to lines
  else:
      remove any tax with prefix from lines

Antes cada módulo lo replicaba ~50 líneas. Ahora se centraliza acá.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def _l10n_ar_resolve_iibb_tax(self, company, percent, prefix):
        """Busca o crea el tax `<prefix> <percent>%` clonando `<prefix> 0%`.

        Pattern uniforme para los 4 padrones provinciales:
          - CABA   → prefix='P. IIBB CABA'
          - PBA    → prefix='P. IIBB PBA' (ARBA)
          - SF     → prefix='P. IIBB SF'
          - CBA    → prefix='P. IIBB CBA'

        Auto-activa el template si está desactivado en el primer uso.
        """
        Tax = self.env["account.tax"].sudo().with_context(active_test=False)
        # Format: 3.5 → "3.50", 21.0 → "21".
        pct_str = "%.2f" % percent
        if pct_str.endswith(".00"):
            pct_str = pct_str[:-3]
        target_name = "%s %s%%" % (prefix, pct_str)

        # 1) Tax con % exacto (puede haberse creado en un run anterior).
        exact = Tax.search([
            ("company_id", "=", company.id),
            ("type_tax_use", "=", "sale"),
            ("amount", "=", percent),
            ("name", "ilike", "%s%%" % prefix),
        ], limit=1)
        if exact:
            if not exact.active:
                exact.active = True
            return exact

        # 2) Template `<prefix> 0%` (suele estar desactivado).
        template = Tax.search([
            ("company_id", "=", company.id),
            ("type_tax_use", "=", "sale"),
            ("amount", "=", 0),
            ("name", "ilike", "%s%%" % prefix),
        ], limit=1)
        if not template:
            return Tax.browse()

        # 3) Clonar.
        new_tax = template.copy(default={
            "name": target_name,
            "amount": percent,
            "active": True,
        })
        _logger.info(
            "Creado tax %s clonando '%s' (id=%s)",
            target_name, template.display_name, new_tax.id,
        )
        return new_tax

    def _l10n_ar_apply_iibb_to_lines(self, prefix, target_tax):
        """Pone `target_tax` en todas las líneas (quitando otros con el
        mismo prefijo) o quita todos los que matcheen prefix si target_tax es vacío.
        """
        self.ensure_one()
        for line in self.invoice_line_ids:
            if line.display_type:
                continue
            existing = line.tax_ids.filtered(
                lambda t: t._is_l10n_ar_iibb_tax_for_prefix(prefix)
            )
            if target_tax:
                # Mantener target, quitar otros con el prefijo.
                others = existing - target_tax
                line.tax_ids = [(3, t.id) for t in others] + [(4, target_tax.id)]
            else:
                # No hay tax aplicable — quitar todos los del prefix.
                if existing:
                    line.tax_ids = [(3, t.id) for t in existing]
