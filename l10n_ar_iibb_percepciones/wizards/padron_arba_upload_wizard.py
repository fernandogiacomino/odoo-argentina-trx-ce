# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Wizard: subir padrón ARBA (TXT o ZIP) y procesar a la tabla de alícuotas."""
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import padron_arba as parser

_logger = logging.getLogger(__name__)


class PadronArbaUploadWizard(models.TransientModel):
    _name = "l10n_ar.padron.arba.upload.wizard"
    _description = "Subir padrón ARBA y procesar"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    name = fields.Char(
        string="Identificador del padrón",
        required=True,
        default=lambda self: "ARBA " + fields.Date.context_today(self).strftime("%Y-%m"),
    )
    file_data = fields.Binary(
        string="Archivo (ZIP o TXT)",
        required=True,
    )
    file_name = fields.Char()
    activate = fields.Boolean(
        default=True,
        help="Marcar este padrón como vigente al importar (desactivando "
             "los anteriores con período solapado).",
    )
    state = fields.Selection(
        [("draft", "Subir"), ("done", "Listo")],
        default="draft",
    )
    import_id = fields.Many2one(
        "l10n_ar.padron.arba.import",
        readonly=True,
    )
    line_count = fields.Integer(readonly=True)

    def action_import(self):
        """Parsea el archivo y crea el `import` + bulk-insert de las alícuotas."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Subí un archivo primero."))

        raw = base64.b64decode(self.file_data)

        # Detectar ZIP por firma (PK\x03\x04). Si no es ZIP, asumir TXT.
        try:
            if raw[:2] == b"PK":
                _, records = parser.parse_zip(raw)
            else:
                records = parser.parse_txt(raw)
        except parser.PadronArbaParseError as e:
            raise UserError(_("No pude parsear el archivo: %s") % e)

        if not records:
            raise UserError(_(
                "El archivo está vacío o no tiene registros válidos."
            ))

        # Calcular vigencia desde la mayoría de los registros.
        date_from_set = {r.get("date_from") for r in records if r.get("date_from")}
        date_to_set = {r.get("date_to") for r in records if r.get("date_to")}
        date_from = min(date_from_set) if date_from_set else fields.Date.context_today(self)
        date_to = max(date_to_set) if date_to_set else None

        # Crear el import.
        imp = self.env["l10n_ar.padron.arba.import"].create({
            "name": self.name,
            "date_from": date_from,
            "date_to": date_to,
            "company_id": self.company_id.id,
            "file_name": self.file_name,
            "file_data": self.file_data,
            "state": "draft",
        })

        # Bulk insert.
        n = self.env["l10n_ar.padron.arba.alicuota"].bulk_insert(imp.id, records)
        imp.state = "imported"
        if self.activate:
            imp.action_activate()
        _logger.info(
            "Padrón ARBA importado: id=%s name=%s registros=%d activate=%s",
            imp.id, imp.name, n, self.activate,
        )

        self.write({
            "state": "done",
            "import_id": imp.id,
            "line_count": n,
        })
        # Volver al wizard para mostrar el resultado.
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_open_padron(self):
        """Abre el record del import recién creado."""
        self.ensure_one()
        if not self.import_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "l10n_ar.padron.arba.import",
            "res_id": self.import_id.id,
            "view_mode": "form",
        }
