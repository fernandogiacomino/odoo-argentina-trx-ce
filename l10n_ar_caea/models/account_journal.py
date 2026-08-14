# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Puntos de venta exclusivos CAEA (RG 5785/2025).

La norma exige que los comprobantes emitidos con CAEA salgan por puntos
de venta habilitados EXCLUSIVAMENTE para contingencia. Modelamos eso con:

* `l10n_ar_afip_pos_caea`: marca el journal como PV exclusivo CAEA.
  Estos journals NUNCA emiten vía webservice (`_l10n_ar_afip_ws_for_emission`
  devuelve None) — numeran con secuencia local, lo que los hace 100%
  operables sin conectividad.
* `l10n_ar_caea_journal_id`: en el journal NORMAL (CAE), apunta a su
  journal de contingencia. Cuando WSFE no responde, el move se re-rutea
  a ese diario.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountJournal(models.Model):
    _inherit = "account.journal"

    l10n_ar_afip_pos_caea = fields.Boolean(
        string="PV exclusivo CAEA",
        default=False,
        help="Punto de venta habilitado en ARCA exclusivamente para "
             "emisión con CAEA (contingencia, RG 5785/2025). Este diario "
             "nunca emite vía webservice: numera con secuencia local y "
             "el comprobante se rinde después por FECAEARegInformativo.",
    )
    l10n_ar_caea_journal_id = fields.Many2one(
        "account.journal",
        string="Diario de contingencia CAEA",
        domain="[('l10n_ar_afip_pos_caea', '=', True),"
               " ('type', '=', 'sale'),"
               " ('company_id', '=', company_id)]",
        help="Diario (PV exclusivo CAEA) al que se re-rutean los "
             "comprobantes de este diario cuando WSFE está caído.",
    )

    @api.constrains("l10n_ar_afip_pos_caea", "l10n_ar_afip_pos_number",
                    "type", "l10n_latam_use_documents")
    def _check_l10n_ar_afip_pos_caea(self):
        for journal in self.filtered("l10n_ar_afip_pos_caea"):
            if journal.type != "sale":
                raise ValidationError(_(
                    "El diario CAEA %s debe ser de tipo Ventas."
                ) % journal.name)
            if not journal.l10n_ar_afip_pos_number:
                raise ValidationError(_(
                    "El diario CAEA %s necesita número de punto de venta "
                    "AFIP (el PV exclusivo CAEA habilitado en ARCA)."
                ) % journal.name)
            if not journal.l10n_latam_use_documents:
                raise ValidationError(_(
                    "El diario CAEA %s debe usar documentos (l10n_latam)."
                ) % journal.name)

    @api.constrains("l10n_ar_caea_journal_id")
    def _check_l10n_ar_caea_journal_id(self):
        for journal in self.filtered("l10n_ar_caea_journal_id"):
            target = journal.l10n_ar_caea_journal_id
            if not target.l10n_ar_afip_pos_caea:
                raise ValidationError(_(
                    "El diario de contingencia de %s debe estar marcado "
                    "como 'PV exclusivo CAEA'."
                ) % journal.name)
            if journal.l10n_ar_afip_pos_caea:
                raise ValidationError(_(
                    "%s ya es un PV CAEA — no puede tener a su vez un "
                    "diario de contingencia."
                ) % journal.name)

    @property
    def _l10n_ar_afip_ws_for_emission(self):
        """Un PV exclusivo CAEA jamás emite por webservice."""
        if self.l10n_ar_afip_pos_caea:
            return None
        return super()._l10n_ar_afip_ws_for_emission
