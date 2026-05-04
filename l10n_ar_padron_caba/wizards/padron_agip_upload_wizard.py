# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Wizard para subir el padrón mensual AGIP — atajo desde menú."""
from odoo import _, fields, models
from odoo.exceptions import UserError


class PadronAgipUploadWizard(models.TransientModel):
    _name = "l10n_ar.padron.agip.upload.wizard"
    _description = "Subir padrón AGIP CABA"

    name = fields.Char(
        required=True,
        default=lambda self: _("AGIP %s") % fields.Date.context_today(self).strftime("%Y-%m"),
    )
    file_data = fields.Binary(
        string="Archivo padrón",
        required=True,
        help="Archivo TXT plano o ZIP descargado del portal AGIP.",
    )
    file_name = fields.Char()
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
    )

    def action_import(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Subí el archivo del padrón."))
        Imp = self.env["l10n_ar.padron.agip.import"]
        rec = Imp.create({
            "name": self.name,
            "company_id": self.company_id.id,
            "file_data": self.file_data,
            "file_name": self.file_name,
            "date_from": fields.Date.context_today(self),  # se actualiza al parsear
        })
        rec.action_parse_file()
        rec.action_activate()
        return {
            "type": "ir.actions.act_window",
            "name": rec.display_name,
            "res_model": "l10n_ar.padron.agip.import",
            "res_id": rec.id,
            "view_mode": "form",
            "target": "current",
        }
