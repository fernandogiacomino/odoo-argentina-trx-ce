# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Modelos para el padrón mensual de alícuotas IIBB AGIP (CABA).

Diseño:

* `l10n_ar.padron.agip.import` — un registro por **archivo importado**.
* `l10n_ar.padron.agip.alicuota` — un registro por **(CUIT, vigencia)**.
  Es lo que se consulta al emitir una factura para saber qué
  percepción aplicar al cliente.

El `import` es el dueño (`one2many`) de las alícuotas; al borrar un
import se borran sus alícuotas.

Performance: la búsqueda principal es `(cuit, date)` para resolver una
factura saliente. Index sobre `(cuit, date_from, date_to)`. AGIP típicamente
trae ~80k registros por mes; con índice esto es <1ms.
"""
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..lib import padron_agip as agip_lib

_logger = logging.getLogger(__name__)


class PadronAgipImport(models.Model):
    _name = "l10n_ar.padron.agip.import"
    _description = "Padrón AGIP CABA — archivo importado"
    _order = "date_from desc, id desc"
    _rec_name = "display_name"

    name = fields.Char(
        required=True,
        default=lambda self: _("AGIP Nuevo"),
        help="Identificador del padrón. Por convención: 'AGIP YYYY-MM'.",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)
    date_from = fields.Date(
        required=True,
        help="Vigencia desde (extraída del padrón al importar).",
    )
    date_to = fields.Date(string="Vigencia hasta")
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    file_name = fields.Char()
    file_data = fields.Binary(
        attachment=True,
        help="ZIP / TXT original importado, guardado para auditoría.",
    )
    state = fields.Selection(
        [("draft", "Borrador"), ("imported", "Importado"), ("active", "Vigente")],
        default="draft",
        required=True,
        copy=False,
    )
    alicuota_ids = fields.One2many(
        "l10n_ar.padron.agip.alicuota",
        "import_id",
        string="Alícuotas",
    )
    alicuota_count = fields.Integer(compute="_compute_counts")

    @api.depends("name", "date_from", "date_to")
    def _compute_display_name(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.display_name = "%s · %s → %s" % (
                    rec.name, rec.date_from.strftime("%Y-%m"),
                    rec.date_to.strftime("%Y-%m-%d"),
                )
            else:
                rec.display_name = rec.name or _("AGIP")

    @api.depends("alicuota_ids")
    def _compute_counts(self):
        for rec in self:
            rec.alicuota_count = len(rec.alicuota_ids)

    def action_parse_file(self):
        """Parsea `file_data` y crea las alicuotas. Re-import borra anteriores."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Subí un archivo antes de importarlo."))
        try:
            content = base64.b64decode(self.file_data)
            records = agip_lib.parse_bytes(content, self.file_name or "")
        except Exception as e:
            raise UserError(_("Error parseando el padrón AGIP: %s") % e)

        if not records:
            raise UserError(_(
                "El archivo no tiene registros válidos. Verificá que sea "
                "un padrón AGIP (TXT con campos separados por ';')."
            ))

        # Borrar alicuotas previas si re-import.
        self.alicuota_ids.unlink()

        Alic = self.env["l10n_ar.padron.agip.alicuota"]
        vals_list = []
        min_d = max_d = None
        for r in records:
            d = r.get("date_from")
            if d:
                min_d = d if (min_d is None or d < min_d) else min_d
            d2 = r.get("date_to")
            if d2:
                max_d = d2 if (max_d is None or d2 > max_d) else max_d
            vals_list.append({
                "import_id": self.id,
                "cuit": r["cuit"],
                "name": r.get("name") or "",
                "date_from": r.get("date_from"),
                "date_to": r.get("date_to"),
                "tipo": r.get("tipo"),
                "alta_baja": r.get("alta_baja"),
                "aliquot_perception": r.get("aliquot_perception", 0),
                "aliquot_retention": r.get("aliquot_retention", 0),
                "grupo_perception": r.get("grupo_perception", 0),
                "grupo_retention": r.get("grupo_retention", 0),
            })

        # Bulk create — en chunks de 1000 para no saturar memory.
        chunk = 1000
        for i in range(0, len(vals_list), chunk):
            Alic.create(vals_list[i:i + chunk])

        self.write({
            "date_from": min_d,
            "date_to": max_d,
            "state": "imported",
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Padrón AGIP importado"),
                "message": _("Importadas %s alícuotas (%s → %s).") % (
                    len(vals_list), min_d, max_d,
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def action_activate(self):
        """Activa este padrón y desactiva los anteriores que se solapan."""
        self.ensure_one()
        if self.state != "imported":
            raise UserError(_("Solo se puede activar un padrón importado."))
        # Desactivar otros activos.
        others = self.search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "active"),
            ("id", "!=", self.id),
        ])
        others.write({"state": "imported"})
        self.write({"state": "active"})

    def action_view_alicuotas(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Alícuotas — %s") % self.name,
            "res_model": "l10n_ar.padron.agip.alicuota",
            "view_mode": "list,form",
            "domain": [("import_id", "=", self.id)],
        }


class PadronAgipAlicuota(models.Model):
    _name = "l10n_ar.padron.agip.alicuota"
    _description = "Padrón AGIP CABA — Alícuota"
    _order = "cuit, date_from desc"

    import_id = fields.Many2one(
        "l10n_ar.padron.agip.import",
        ondelete="cascade",
        required=True,
        index=True,
    )
    company_id = fields.Many2one(related="import_id.company_id", store=True)
    cuit = fields.Char(required=True, size=11, index=True)
    name = fields.Char(string="Razón social")
    date_from = fields.Date(required=True, index=True)
    date_to = fields.Date(index=True)
    tipo = fields.Selection(
        selection=[
            ("L", "Local"),
            ("C", "Convenio"),
            ("N", "No inscripto"),
        ],
        string="Tipo contribuyente",
    )
    alta_baja = fields.Selection(
        selection=[
            ("A", "Alta"),
            ("B", "Baja"),
            ("M", "Modificación"),
            ("S", "Sin cambios"),
        ],
    )
    aliquot_perception = fields.Float(string="% Percepción", digits=(5, 2))
    aliquot_retention = fields.Float(string="% Retención", digits=(5, 2))
    grupo_perception = fields.Integer(string="Grupo Perc.")
    grupo_retention = fields.Integer(string="Grupo Ret.")

    @api.model
    def find_for(self, cuit, target_date=None, company=None):
        """Busca la alícuota AGIP vigente para `cuit` en `target_date`.

        :param cuit: 11 dígitos (sin guiones).
        :return: recordset (puede ser vacío).
        """
        if not cuit:
            return self.browse()
        company = company or self.env.company
        d = target_date or fields.Date.context_today(self)
        cuit_clean = "".join(c for c in str(cuit) if c.isdigit()).zfill(11)
        return self.search([
            ("company_id", "=", company.id),
            ("cuit", "=", cuit_clean),
            ("date_from", "<=", d),
            "|", ("date_to", ">=", d), ("date_to", "=", False),
            ("import_id.state", "=", "active"),
        ], order="date_from desc", limit=1)
