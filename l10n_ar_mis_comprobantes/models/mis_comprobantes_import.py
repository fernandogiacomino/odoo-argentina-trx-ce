# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Modelo `l10n_ar.mis.comprobantes.import` — un batch de import.

Cada batch corresponde a un archivo XLS subido del portal "Mis
Comprobantes" de ARCA. Los registros son persistentes (no transient)
para que el operador pueda re-cotejar después de cargar comprobantes
faltantes en Odoo, sin tener que re-subir el archivo.

Estados:

  * draft     → recién creado, sin cotejar
  * cotejado  → ya se corrió `_action_match()` y las lines tienen estado
  * archived  → finalizado, no se vuelve a cotejar (cierre de período)
"""
import base64
import logging
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import parser

_logger = logging.getLogger(__name__)


class MisComprobantesImport(models.Model):
    _name = "l10n_ar.mis.comprobantes.import"
    _description = "Mis Comprobantes — batch de import"
    _inherit = ["mail.thread"]
    _order = "create_date desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        default=lambda self: _("Nuevo batch"),
        copy=False,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    kind = fields.Selection(
        selection=[
            ("emitted", "Emitidos"),
            ("received", "Recibidos"),
        ],
        string="Tipo",
        required=True,
        default="emitted",
        tracking=True,
    )
    date_from = fields.Date(
        string="Período desde",
        tracking=True,
        help="Auto-inferido del XLS al importar; usado para buscar matches en Odoo.",
    )
    date_to = fields.Date(
        string="Período hasta",
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("cotejado", "Cotejado"),
            ("archived", "Cerrado"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        "l10n_ar.mis.comprobantes.line",
        "import_id",
        string="Líneas",
    )
    file_data = fields.Binary(string="Archivo XLS importado", attachment=True)
    file_name = fields.Char(string="Nombre archivo")

    # Counters por estado de cotejo (usados en kanban / form header).
    line_count = fields.Integer(compute="_compute_counts")
    match_ok_count = fields.Integer(compute="_compute_counts")
    match_solo_afip_count = fields.Integer(compute="_compute_counts")
    match_solo_odoo_count = fields.Integer(compute="_compute_counts")
    match_diff_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids.match_state")
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.match_ok_count = len(rec.line_ids.filtered(lambda l: l.match_state == "ok"))
            rec.match_solo_afip_count = len(rec.line_ids.filtered(lambda l: l.match_state == "solo_afip"))
            rec.match_solo_odoo_count = len(rec.line_ids.filtered(lambda l: l.match_state == "solo_odoo"))
            rec.match_diff_count = len(rec.line_ids.filtered(lambda l: l.match_state == "amount_diff"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("Nuevo batch"):
                kind = vals.get("kind", "emitted")
                tag = "EMI" if kind == "emitted" else "REC"
                seq = self.env["ir.sequence"].next_by_code(
                    "l10n_ar.mis.comprobantes.import"
                )
                if not seq:
                    # Fallback si la ir.sequence no existe (instalación
                    # parcial / data file con noupdate viejo).
                    Seq = self.env["ir.sequence"].sudo()
                    seq_rec = Seq.search([
                        ("code", "=", "l10n_ar.mis.comprobantes.import")
                    ], limit=1)
                    if not seq_rec:
                        seq_rec = Seq.create({
                            "name": "Mis Comprobantes — Batch import",
                            "code": "l10n_ar.mis.comprobantes.import",
                            "padding": 5,
                            "number_next": 1,
                            "number_increment": 1,
                        })
                    seq = seq_rec.next_by_id() or "00001"
                vals["name"] = "MC-%s-%s" % (tag, seq)
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Import del XLS
    # ------------------------------------------------------------------
    def action_parse_file(self):
        """Parsea `file_data` y crea las lines. Resetea match_state."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Subí un archivo XLS antes de importarlo."))
        try:
            content = base64.b64decode(self.file_data)
            records = parser.parse_xlsx(content, kind=self.kind)
        except Exception as e:
            raise UserError(_("Error parseando el XLS: %s") % e)

        if not records:
            raise UserError(_("El XLS no tiene líneas válidas."))

        # Limpiar lines viejas si las había (re-import).
        self.line_ids.unlink()

        Line = self.env["l10n_ar.mis.comprobantes.line"]
        line_vals = []
        min_d = max_d = None
        for r in records:
            d = r.get("fecha_emision")
            if d:
                min_d = d if (min_d is None or d < min_d) else min_d
                max_d = d if (max_d is None or d > max_d) else max_d
            line_vals.append({
                "import_id": self.id,
                "kind": self.kind,
                "fecha_emision": r.get("fecha_emision"),
                "tipo_cbte": r.get("tipo_cbte"),
                "pto_vta": r.get("pto_vta"),
                "nro_desde": r.get("nro_desde"),
                "nro_hasta": r.get("nro_hasta") or r.get("nro_desde"),
                "cae": r.get("cae") or False,
                "doc_tipo_partner": r.get("doc_tipo_partner") or False,
                "doc_nro_partner": r.get("doc_nro_partner") or False,
                "denom_partner": r.get("denom_partner") or False,
                "moneda": r.get("moneda") or "PES",
                "tipo_cambio": float(r.get("tipo_cambio") or 1),
                "neto_iva_0":    float(r.get("neto_iva_0") or 0),
                "neto_iva_2_5":  float(r.get("neto_iva_2_5") or 0),
                "iva_2_5":       float(r.get("iva_2_5") or 0),
                "neto_iva_5":    float(r.get("neto_iva_5") or 0),
                "iva_5":         float(r.get("iva_5") or 0),
                "neto_iva_10_5": float(r.get("neto_iva_10_5") or 0),
                "iva_10_5":      float(r.get("iva_10_5") or 0),
                "neto_iva_21":   float(r.get("neto_iva_21") or 0),
                "iva_21":        float(r.get("iva_21") or 0),
                "neto_iva_27":   float(r.get("neto_iva_27") or 0),
                "iva_27":        float(r.get("iva_27") or 0),
                "imp_neto_gravado": float(r.get("imp_neto_gravado") or 0),
                "imp_neto_no_gravado": float(r.get("imp_neto_no_gravado") or 0),
                "imp_op_exentas": float(r.get("imp_op_exentas") or 0),
                "imp_otros_tributos": float(r.get("imp_otros_tributos") or 0),
                "imp_iva": float(r.get("imp_iva") or 0),
                "imp_total": float(r.get("imp_total") or 0),
                "match_state": "pending",
            })
        Line.create(line_vals)
        self.write({
            "date_from": min_d,
            "date_to": max_d,
            "state": "draft",
        })
        self.message_post(
            body=_("Importadas %s líneas del archivo %s.")
            % (len(line_vals), self.file_name or _("(sin nombre)")),
        )
        return self.action_match()

    def action_match(self):
        """Coteja cada line contra account.move + busca lines de Odoo
        sin contraparte AFIP y las agrega como `solo_odoo`.

        Estrategia de match:
          - Por (company, kind→move_type, l10n_latam_document_type_id.code,
            journal pos, document_number_int) buscar account.move.
          - Si match: comparar imp_total con redondeo de 0.01. Si difiere
            → 'amount_diff'. Si igual → 'ok'.
          - Si no match: 'solo_afip' (existe en AFIP pero no en Odoo).

        Después busca account.move emitidas en el rango de fechas que NO
        están referenciadas por ninguna line; las agrega como `solo_odoo`.
        """
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Importá un archivo primero."))

        Move = self.env["account.move"]
        # Paso 1: para cada line del batch, buscar move en Odoo.
        afip_keys = set()
        for line in self.line_ids:
            move = line._find_move()
            line._apply_match(move)
            if move:
                afip_keys.add(move.id)

        # Paso 2: lines "solo_odoo" — facturas en Odoo dentro del rango
        # con CAE pero que no aparecen en ninguna line del batch.
        domain_move_type = (
            ["out_invoice", "out_refund"]
            if self.kind == "emitted"
            else ["in_invoice", "in_refund"]
        )
        if self.date_from and self.date_to:
            extra_domain = [
                ("company_id", "=", self.company_id.id),
                ("move_type", "in", domain_move_type),
                ("invoice_date", ">=", self.date_from),
                ("invoice_date", "<=", self.date_to),
                ("state", "=", "posted"),
                ("l10n_ar_afip_auth_code", "!=", False),
                ("id", "not in", list(afip_keys) or [0]),
            ]
            extras = Move.search(extra_domain)
            Line = self.env["l10n_ar.mis.comprobantes.line"]
            for m in extras:
                # Crear una line "solo_odoo" con datos del move.
                pos, nro = self._split_pos_nro(m.l10n_latam_document_number)
                Line.create({
                    "import_id": self.id,
                    "kind": self.kind,
                    "fecha_emision": m.invoice_date,
                    "tipo_cbte": int(m.l10n_latam_document_type_id.code or 0),
                    "pto_vta": pos,
                    "nro_desde": nro,
                    "nro_hasta": nro,
                    "cae": m.l10n_ar_afip_auth_code or False,
                    "doc_nro_partner": (m.commercial_partner_id.vat or "").replace("-", "").strip() or False,
                    "denom_partner": m.commercial_partner_id.name,
                    "imp_total": m.amount_total,
                    "imp_neto_gravado": m.amount_untaxed,
                    "match_state": "solo_odoo",
                    "move_id": m.id,
                })

        self.write({"state": "cotejado"})
        return True

    @staticmethod
    def _split_pos_nro(name):
        if not name:
            return 0, 0
        if "-" in name:
            try:
                a, b = name.split("-")[-2], name.split("-")[-1]
                return int(a), int(b)
            except (ValueError, IndexError):
                return 0, 0
        return 0, 0

    def action_archive_batch(self):
        for rec in self:
            rec.state = "archived"

    def action_reset_batch(self):
        for rec in self:
            rec.line_ids.unlink()
            rec.state = "draft"

    # Botones para abrir las lines filtradas.
    def _action_open_lines(self, match_state):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Líneas — %s") % match_state,
            "res_model": "l10n_ar.mis.comprobantes.line",
            "view_mode": "list,form",
            "domain": [("import_id", "=", self.id), ("match_state", "=", match_state)],
            "context": {"default_import_id": self.id},
        }

    def action_open_ok(self): return self._action_open_lines("ok")
    def action_open_solo_afip(self): return self._action_open_lines("solo_afip")
    def action_open_solo_odoo(self): return self._action_open_lines("solo_odoo")
    def action_open_amount_diff(self): return self._action_open_lines("amount_diff")

    def action_open_solo_afip_to_create(self):
        """Abre la lista de líneas solo_afip+received para que el user
        las tilde y use el botón header 'Crear comprobantes seleccionados'."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Crear faltantes en Odoo — %s") % self.name,
            "res_model": "l10n_ar.mis.comprobantes.line",
            "view_mode": "list,form",
            "domain": [
                ("import_id", "=", self.id),
                ("match_state", "=", "solo_afip"),
                ("kind", "=", "received"),
            ],
            "context": {"default_import_id": self.id},
            "help": (
                "<p class='o_view_nocontent_smiling_face'>"
                "No hay comprobantes para crear</p>"
                "<p>Todos los recibidos del XLS ya están registrados en Odoo.</p>"
            ),
        }
