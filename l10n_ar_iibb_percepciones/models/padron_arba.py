# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Modelos para el padrón mensual de alícuotas IIBB ARBA (Buenos Aires).

Diseño:

* `l10n_ar.padron.arba.import` — un registro por **archivo importado**.
  Trackea quién subió qué padrón, cuándo, con qué resultado.
* `l10n_ar.padron.arba.alicuota` — un registro por **(CUIT, vigencia)**.
  Es lo que se consulta al emitir una factura para saber qué
  percepción aplicar.

El `import` es el dueño (`one2many`) de las alícuotas; al borrar un
import se borran sus alícuotas.

Performance: la búsqueda principal es `(cuit, date)` para resolver una
factura saliente. Index compuesto sobre `(cuit, date_from, date_to)`.
ARBA típicamente trae ~100k registros por mes; con índice esto es <1ms.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PadronArbaImport(models.Model):
    _name = "l10n_ar.padron.arba.import"
    _description = "Padrón ARBA — archivo importado"
    _order = "date_from desc, id desc"
    _rec_name = "display_name"

    name = fields.Char(
        required=True,
        help="Identificador del padrón. Por convención: 'ARBA YYYY-MM' o "
             "lo que el usuario ponga.",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)
    date_from = fields.Date(
        required=True,
        help="Vigencia desde (extraída del primer registro del padrón).",
    )
    date_to = fields.Date(
        help="Vigencia hasta (último día del período).",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    file_name = fields.Char()
    file_data = fields.Binary(
        attachment=True,
        help="ZIP/TXT original importado, guardado para auditoría.",
    )
    state = fields.Selection(
        [("draft", "Borrador"), ("imported", "Importado"), ("active", "Vigente")],
        default="draft",
        required=True,
        copy=False,
    )
    line_count = fields.Integer(
        compute="_compute_line_count", store=True,
        help="Cantidad de alícuotas procesadas.",
    )
    line_ids = fields.One2many(
        "l10n_ar.padron.arba.alicuota",
        "import_id",
        string="Alícuotas",
    )

    @api.depends("name", "date_from", "date_to")
    def _compute_display_name(self):
        for rec in self:
            d1 = rec.date_from and rec.date_from.strftime("%Y-%m") or ""
            rec.display_name = "%s · %s" % (rec.name or "Padrón ARBA", d1)

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_activate(self):
        """Marca este padrón como vigente y desactiva los anteriores con
        período solapado."""
        for rec in self:
            overlapping = self.search([
                ("id", "!=", rec.id),
                ("company_id", "=", rec.company_id.id),
                ("state", "=", "active"),
            ])
            for other in overlapping:
                if (
                    other.date_to and rec.date_from
                    and other.date_to >= rec.date_from
                ):
                    other.state = "imported"
            rec.state = "active"
        return True


class PadronArbaAlicuota(models.Model):
    _name = "l10n_ar.padron.arba.alicuota"
    _description = "Padrón ARBA — alícuota por CUIT y período"
    _order = "cuit, date_from desc"
    _rec_name = "cuit"

    import_id = fields.Many2one(
        "l10n_ar.padron.arba.import",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="import_id.company_id",
        store=True,
        index=True,
    )
    cuit = fields.Char(required=True, index=True, size=11)
    date_from = fields.Date(required=True, index=True)
    date_to = fields.Date(index=True)
    fecha_pub = fields.Date()
    aliquot_perception = fields.Float(
        digits=(5, 2),
        help="Alícuota de percepción IIBB BA en porcentaje (3.00 = 3%).",
    )
    aliquot_retention = fields.Float(
        digits=(5, 2),
        help="Alícuota de retención IIBB BA en porcentaje.",
    )
    tipo = fields.Selection(
        [("0", "Bajo riesgo"), ("1", "Alto riesgo")],
        help="Calificación de riesgo del contribuyente al momento de "
             "emisión del padrón.",
    )
    alta_baja = fields.Selection(
        [("A", "Alta"), ("B", "Baja"), ("S", "Sin cambios")],
        help="Marca del registro respecto al padrón anterior.",
    )
    grupo_perception = fields.Char(size=1)
    grupo_retention = fields.Char(size=1)

    # Odoo 19 deprecó `_sql_constraints` (warning ignorado al cargar el
    # registry → el UNIQUE index no se crea, y el ON CONFLICT del
    # bulk_insert falla con "no unique or exclusion constraint matching".
    # Workaround: crear el index UNIQUE explícitamente en `init()`.
    # Cuando la nueva API `models.Constraint` esté estable, migrar acá.
    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                l10n_ar_padron_arba_alicuota_uniq_import_cuit_date
            ON l10n_ar_padron_arba_alicuota (import_id, cuit, date_from)
        """)

    # ------------------------------------------------------------------
    # API pública: consulta para aplicar percepción
    # ------------------------------------------------------------------
    @api.model
    def find_for_cuit(self, cuit, date_ref=None, company=None):
        """Devuelve la alícuota vigente para `cuit` en `date_ref` o False.

        Solo considera padrones en estado `active`.

        :param cuit: str de 11 dígitos.
        :param date_ref: date — por defecto hoy.
        :param company: res.company — por defecto self.env.company.
        :return: recordset con 0 o 1 registro.
        """
        if not cuit:
            return self.browse()
        digits = "".join(c for c in str(cuit) if c.isdigit())
        if len(digits) != 11:
            return self.browse()
        date_ref = date_ref or fields.Date.context_today(self)
        company = company or self.env.company
        domain = [
            ("cuit", "=", digits),
            ("import_id.state", "=", "active"),
            ("import_id.company_id", "=", company.id),
            ("date_from", "<=", date_ref),
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", date_ref),
        ]
        return self.search(domain, order="date_from desc, id desc", limit=1)

    # ------------------------------------------------------------------
    # Bulk insert helper — usado por el wizard de upload
    # ------------------------------------------------------------------
    @api.model
    def bulk_insert(self, import_id, records):
        """Inserta registros via SQL plano para performance.

        ARBA trae ~100k filas por mes; ORM `create()` toma minutos.
        Con SQL directo bajamos a <2 segundos.

        :param import_id: id del `l10n_ar.padron.arba.import`.
        :param records: iterable de dicts (de `lib.padron_arba.parse_*`).
        :return: cantidad de filas insertadas.
        """
        if not records:
            return 0
        # Normalizamos en memoria.
        rows = []
        for r in records:
            cuit = (r.get("cuit") or "").strip()
            if len(cuit) != 11 or not cuit.isdigit():
                continue  # ignorar registros mal formados
            if not r.get("date_from"):
                continue
            rows.append((
                import_id,
                cuit,
                r["date_from"],
                r.get("date_to"),
                r.get("fecha_pub"),
                r.get("aliquot_perception") or 0.0,
                r.get("aliquot_retention") or 0.0,
                r.get("tipo") or False,
                r.get("alta_baja") or False,
                r.get("grupo_perception") or False,
                r.get("grupo_retention") or False,
            ))
        if not rows:
            return 0
        # executemany es ~3-5x más rápido que una query gigante con VALUES.
        self.env.cr.executemany(
            """
            INSERT INTO l10n_ar_padron_arba_alicuota
                (import_id, cuit, date_from, date_to, fecha_pub,
                 aliquot_perception, aliquot_retention, tipo, alta_baja,
                 grupo_perception, grupo_retention,
                 create_uid, create_date, write_uid, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, NOW() AT TIME ZONE 'UTC', %s, NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (import_id, cuit, date_from) DO UPDATE SET
                date_to = EXCLUDED.date_to,
                aliquot_perception = EXCLUDED.aliquot_perception,
                aliquot_retention = EXCLUDED.aliquot_retention,
                tipo = EXCLUDED.tipo,
                alta_baja = EXCLUDED.alta_baja,
                grupo_perception = EXCLUDED.grupo_perception,
                grupo_retention = EXCLUDED.grupo_retention,
                write_date = NOW() AT TIME ZONE 'UTC'
            """,
            [
                row + (self.env.uid, self.env.uid)
                for row in rows
            ],
        )
        # invalidar cache
        self.env["l10n_ar.padron.arba.alicuota"].invalidate_model()
        return len(rows)
