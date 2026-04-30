# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Wizard: generar Subdiario IVA Compras / Ventas (PDF + XLSX).

A diferencia del Libro IVA Digital RG 5616 (que es un export TXT de
formato fijo para AFIP), el Subdiario IVA es un reporte interno para
el contador. No tiene un formato oficial estricto — replicamos el set
de columnas que usa SIAp + lo que arma el "Mis Comprobantes" del
portal AFIP.

Fuente única de datos: el modelo SQL ``account.ar.vat.line``. Eso
garantiza que la vista interactiva (Argentina → Subdiario IVA — Detalle)
y los exports PDF/XLSX muestren exactamente los mismos números.

UX:
    - Menú: Contabilidad → Reportes → Argentina → Subdiario IVA.
    - El usuario elige período (date_from / date_to) y formato.
    - Botón "Generar PDF" — QWeb landscape, una página por sección.
    - Botón "Exportar XLSX" — workbook con hojas Ventas + Compras.

Para algunos campos (despacho de importación, cotización del cbte,
crédito fiscal computable) se sigue necesitando leer el ``account.move``
original — la vista SQL agrega lo numérico, pero hay metadata que solo
está en el move. Se prefetchean en bloque para no hacer N+1.
"""
import base64
import io
import logging
import re
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import xlsx_writer

_logger = logging.getLogger(__name__)


# Códigos AFIP de tipo de comprobante que representan Notas de Crédito.
NC_DOC_CODES = {3, 8, 13, 21, 41, 53, 113, 118}

# Alícuotas a desglosar en columnas dedicadas (orden = orden visual).
DISPLAY_ALICUOTAS = [21.0, 10.5, 27.0, 5.0, 2.5]


class SubdiarioIvaWizard(models.TransientModel):
    _name = "l10n_ar.subdiario.iva.wizard"
    _description = "Subdiario IVA Compras/Ventas — PDF + XLSX"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
        help="Primer día del período.",
    )
    date_to = fields.Date(
        required=True,
        default=lambda self: fields.Date.today(),
        help="Último día del período.",
    )
    include_sales = fields.Boolean(default=True, string="Incluir Ventas")
    include_purchases = fields.Boolean(default=True, string="Incluir Compras")

    # Salida XLSX.
    file_name = fields.Char(readonly=True)
    file_content = fields.Binary(readonly=True, attachment=False)
    state = fields.Selection(
        [("draft", "Configurar"), ("done", "Listo")],
        default="draft",
    )

    # ------------------------------------------------------------------
    # Botones
    # ------------------------------------------------------------------
    def action_export_xlsx(self):
        """Genera el XLSX y deja el archivo en el wizard para descarga."""
        self.ensure_one()
        self._validate()

        sheets = self._build_sheets()
        period = self.date_from.strftime("%Y%m")
        meta = {
            "title": f"Subdiario IVA — {self.company_id.name} — {period}",
            "author": "Trixocom (l10n_ar_trxinvoice_ce)",
        }
        try:
            xlsx_bytes = xlsx_writer.build_xlsx(sheets, meta=meta)
        except RuntimeError as exc:
            raise UserError(str(exc))

        self.write({
            "file_name": "subdiario_iva_%s_%s.xlsx" % (period, self.company_id.id),
            "file_content": base64.b64encode(xlsx_bytes),
            "state": "done",
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_print_pdf(self):
        """Render del subdiario como PDF QWeb landscape."""
        self.ensure_one()
        self._validate()
        return self.env.ref(
            "l10n_ar_libro_iva_digital.action_report_subdiario_iva"
        ).report_action(self, data={
            "company_id": self.company_id.id,
            "date_from": fields.Date.to_string(self.date_from),
            "date_to": fields.Date.to_string(self.date_to),
            "include_sales": self.include_sales,
            "include_purchases": self.include_purchases,
        })

    def action_open_interactive_view(self):
        """Abre la vista interactiva del Subdiario IVA filtrada por el período."""
        self.ensure_one()
        self._validate()
        action = self.env.ref(
            "l10n_ar_libro_iva_digital.action_account_ar_vat_line"
        ).read()[0]
        domain = [
            ("company_id", "=", self.company_id.id),
            ("invoice_date", ">=", self.date_from),
            ("invoice_date", "<=", self.date_to),
        ]
        if not (self.include_sales and self.include_purchases):
            if self.include_sales:
                domain.append(("tax_type", "=", "sale"))
            elif self.include_purchases:
                domain.append(("tax_type", "=", "purchase"))
        action["domain"] = domain
        action["context"] = {}  # quitar el search_default_this_month
        return action

    def _validate(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("El 'Desde' debe ser anterior o igual al 'Hasta'."))
        if not (self.include_sales or self.include_purchases):
            raise UserError(_("Hay que incluir al menos Ventas o Compras."))

    # ------------------------------------------------------------------
    # API que también consume el reporte QWeb (vía `_get_report_values`).
    # ------------------------------------------------------------------
    def get_report_data(self):
        """Devuelve un dict listo para QWeb con secciones armadas."""
        self.ensure_one()
        sales_rows, purchase_rows = self._build_rows()
        return {
            "company": self.company_id,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "sales": sales_rows,
            "purchases": purchase_rows,
            "totals_sales": self._compute_totals(sales_rows),
            "totals_purchases": self._compute_totals(purchase_rows),
            "alicuotas": DISPLAY_ALICUOTAS,
        }

    # ------------------------------------------------------------------
    # Construcción de filas (compartida XLSX + PDF) — leyendo de la vista SQL
    # ------------------------------------------------------------------
    def _build_rows(self):
        """Devuelve (sales_rows, purchase_rows) como listas de dicts.

        Lee de `account.ar.vat.line` (vista SQL) y prefetchea los moves
        para los campos extra (despacho importación, cotización, etc).
        """
        sales_lines = self._get_lines("sale") if self.include_sales else self.env["account.ar.vat.line"].browse()
        purchase_lines = self._get_lines("purchase") if self.include_purchases else self.env["account.ar.vat.line"].browse()

        # Prefetch moves en bloque (1 query) para evitar N+1.
        all_move_ids = list({l.move_id.id for l in (sales_lines | purchase_lines) if l.move_id})
        moves_by_id = {
            m.id: m for m in self.env["account.move"].browse(all_move_ids)
        }

        sales_rows = [self._build_row(line, moves_by_id, sale=True) for line in sales_lines]
        purchase_rows = [self._build_row(line, moves_by_id, sale=False) for line in purchase_lines]
        return sales_rows, purchase_rows

    def _get_lines(self, tax_type):
        """Devuelve recordset de `account.ar.vat.line` filtrado por
        company + período + tax_type, ordenado por fecha + nombre.
        """
        return self.env["account.ar.vat.line"].search([
            ("company_id", "=", self.company_id.id),
            ("invoice_date", ">=", self.date_from),
            ("invoice_date", "<=", self.date_to),
            ("tax_type", "=", tax_type),
        ], order="invoice_date asc, name asc, id asc")

    def _build_row(self, line, moves_by_id, sale=True):
        """Arma un dict por comprobante.

        ``line`` es un account.ar.vat.line. ``moves_by_id`` es el cache
        prefetchado de account.move.
        """
        inv = moves_by_id.get(line.move_id.id) if line.move_id else None

        # Tipo de comprobante (legible).
        doc_type = line.document_type_id
        try:
            tipo_cbte_code = int(doc_type.code or 0)
        except (TypeError, ValueError):
            tipo_cbte_code = 0
        letter = (doc_type.l10n_ar_letter or "").upper() if doc_type else ""
        tipo_label = self._get_tipo_label(doc_type, tipo_cbte_code, letter)

        # Pos / Nro desde el move (la vista SQL no lo expone).
        pos, nro = (0, 0)
        if inv:
            pos, nro = self._split_pos_and_nro(inv)

        # Doc del partner.
        partner = line.commercial_partner_id or line.partner_id
        doc_code, doc_nro = self._partner_doc(partner)

        # Cotización (necesita el move).
        cur = line.currency_id
        company_cur = self.company_id.currency_id
        if not cur or cur == company_cur:
            tipo_cambio = 1.0
            cod_moneda = "PES"
        else:
            inv_rate = (inv.invoice_currency_rate or 1.0) if inv else 1.0
            tipo_cambio = (1.0 / inv_rate) if inv_rate else 1.0
            cod_moneda = (
                getattr(cur, "l10n_ar_afip_code", None) or cur.name or "PES"
            )

        # Cond. IVA receptor (texto legible).
        resp = line.afip_responsibility_type_id
        cond_iva = resp.name if resp else "—"

        # Importes vienen de la vista SQL (todos positivos).
        amounts = {
            "no_gravado": line.no_gravado or 0.0,
            "exento": line.exento or 0.0,
            "neto_gravado": line.neto_gravado or 0.0,
            "perc_iva": line.perc_iva or 0.0,
            "perc_iibb": line.perc_iibb or 0.0,
            "perc_mun": line.perc_municipal or 0.0,
            "internos": line.otros_tributos or 0.0,
            "otros": line.perc_otras or 0.0,
            "total": line.amount_total or 0.0,
            "iva_total": line.iva_total or 0.0,
        }

        row = {
            "fecha": line.invoice_date,
            "tipo_cbte_code": tipo_cbte_code,
            "tipo_cbte_label": tipo_label,
            "pto_vta": pos,
            "nro_cbte": nro,
            "doc_codigo": doc_code,
            "doc_nro": doc_nro,
            "razon_social": line.partner_name or "",
            "cond_iva": cond_iva,
            "cod_moneda": cod_moneda,
            "tipo_cambio": tipo_cambio,
            "no_gravado": amounts["no_gravado"],
            "exento": amounts["exento"],
            "neto_gravado": amounts["neto_gravado"],
            "perc_iva": amounts["perc_iva"],
            "perc_iibb": amounts["perc_iibb"],
            "perc_mun": amounts["perc_mun"],
            "internos": amounts["internos"],
            "otros": amounts["otros"],
            "total": amounts["total"],
            "iva_total": amounts["iva_total"],
            "_inv_id": line.move_id.id if line.move_id else False,
        }

        # Bases e IVA por alícuota (del SQL view).
        row["base_21"] = line.base_21 or 0.0
        row["iva_21"] = line.vat_21 or 0.0
        row["base_10_5"] = line.base_10_5 or 0.0
        row["iva_10_5"] = line.vat_10_5 or 0.0
        row["base_27"] = line.base_27 or 0.0
        row["iva_27"] = line.vat_27 or 0.0
        row["base_5"] = line.base_5 or 0.0
        row["iva_5"] = line.vat_5 or 0.0
        row["base_2_5"] = line.base_2_5 or 0.0
        row["iva_2_5"] = line.vat_2_5 or 0.0

        if not sale:
            # Compras: agregar campos extra (necesitan el move).
            row["despacho_importacion"] = (
                (inv.l10n_latam_document_number if inv and tipo_cbte_code == 66 else "") or ""
            )
            # Crédito Fiscal Computable — usa _l10n_ar_get_amounts si está.
            cred = line.iva_total or 0.0  # default = IVA total (caso global)
            if inv and hasattr(inv, "_l10n_ar_get_amounts"):
                try:
                    am = inv._l10n_ar_get_amounts()
                    cred = am.get("vat_amount", cred)
                except Exception:
                    pass
            row["credito_fiscal_computable"] = cred

        return row

    @staticmethod
    def _get_tipo_label(doc_type, tipo_cbte_code, letter):
        """Etiqueta legible — usa name del doc_type si existe, sino arma 'FA-A'."""
        if doc_type and doc_type.name:
            return doc_type.name
        if tipo_cbte_code in (1, 6, 11):
            return f"FA-{letter or '?'}"
        if tipo_cbte_code in NC_DOC_CODES:
            return f"NC-{letter or '?'}"
        if tipo_cbte_code in (2, 7, 12):
            return f"ND-{letter or '?'}"
        if tipo_cbte_code == 66:
            return "Despacho de Importación"
        return f"Tipo {tipo_cbte_code}"

    @staticmethod
    def _split_pos_and_nro(inv):
        s = inv.l10n_latam_document_number or ""
        if "-" in s:
            parts = s.split("-")
            try:
                return int(parts[-2]), int(parts[-1])
            except (ValueError, IndexError):
                pass
        return inv.journal_id.l10n_ar_afip_pos_number or 0, 0

    @staticmethod
    def _partner_doc(partner):
        """(cod_doc_afip:int, nro_doc:str). Defaults: 99=CF / "0".

        Inspirado en `l10n_ar_reports._vat_book_get_partner_document_code_and_number`
        de enterprise (sin copiar): para Consumidor Final ('5') y Cliente
        Exterior persona física ('10' no-empresa) usamos el VAT del partner
        si está; para Cliente Exterior empresa ('9') usamos `l10n_ar_vat`
        del partner o fallback al VAT default del país; para todo lo demás
        usamos el VAT del partner como CUIT (código 80).
        """
        if not partner:
            return 99, "0"
        commercial = partner.commercial_partner_id or partner
        resp_code = (
            (commercial.l10n_ar_afip_responsibility_type_id.code
             if commercial.l10n_ar_afip_responsibility_type_id else "")
            or ""
        )
        if resp_code == "5" or (resp_code == "10" and not commercial.is_company):
            idt = partner.l10n_latam_identification_type_id
            if idt and idt.l10n_ar_afip_code:
                try:
                    code = int(idt.l10n_ar_afip_code)
                except (TypeError, ValueError):
                    code = 99
            else:
                code = 99
            vat = (partner.vat or "").strip()
            digits = re.sub(r"[^0-9]", "", vat)
            if code == 99 or not digits:
                return 99, "0"
            return code, digits
        if resp_code == "9":
            doc_number = (
                getattr(partner, "l10n_ar_vat", None)
                or (commercial.country_id.l10n_ar_legal_entity_vat
                    if commercial.is_company else
                    getattr(commercial.country_id, "l10n_ar_natural_vat", None))
                or "0"
            )
            digits = re.sub(r"[^0-9]", "", str(doc_number))
            return 80, digits or "0"
        vat = (commercial.vat or partner.vat or "").strip()
        digits = re.sub(r"[^0-9]", "", vat)
        if not digits:
            return 99, "0"
        return 80, digits

    # ------------------------------------------------------------------
    # XLSX sheets
    # ------------------------------------------------------------------
    def _build_sheets(self):
        sheets = []
        sales_rows, purchase_rows = self._build_rows()

        if not sales_rows and not purchase_rows:
            raise UserError(_(
                "No se encontraron comprobantes posted para %(c)s entre "
                "%(d1)s y %(d2)s.",
                c=self.company_id.name,
                d1=self.date_from, d2=self.date_to,
            ))

        period_label = "%s a %s" % (
            self.date_from.strftime("%d/%m/%Y"),
            self.date_to.strftime("%d/%m/%Y"),
        )

        if self.include_sales and sales_rows:
            sheets.append({
                "name": "Ventas",
                "title": "Subdiario IVA — VENTAS — %s — %s" % (
                    self.company_id.name, period_label),
                "columns": self._columns_sales(),
                "rows": sales_rows,
            })

        if self.include_purchases and purchase_rows:
            sheets.append({
                "name": "Compras",
                "title": "Subdiario IVA — COMPRAS — %s — %s" % (
                    self.company_id.name, period_label),
                "columns": self._columns_purchases(),
                "rows": purchase_rows,
            })
        return sheets

    def _columns_common_head(self):
        return [
            {"key": "fecha", "header": "Fecha", "type": "date"},
            {"key": "tipo_cbte_label", "header": "Tipo Cbte", "type": "text", "width": 12},
            {"key": "pto_vta", "header": "Pto Vta", "type": "int"},
            {"key": "nro_cbte", "header": "Nro Cbte", "type": "int", "width": 12},
            {"key": "doc_codigo", "header": "Cod Doc", "type": "int"},
            {"key": "doc_nro", "header": "Nro Doc", "type": "text", "width": 14},
            {"key": "razon_social", "header": "Razón Social", "type": "text", "width": 32},
            {"key": "cond_iva", "header": "Cond IVA", "type": "text", "width": 18},
            {"key": "cod_moneda", "header": "Mon", "type": "text", "width": 6},
            {"key": "tipo_cambio", "header": "Cotiz", "type": "amount"},
            {"key": "no_gravado", "header": "No Gravado", "type": "amount"},
            {"key": "exento", "header": "Exento", "type": "amount"},
            {"key": "neto_gravado", "header": "Neto Gravado", "type": "amount"},
        ]

    def _columns_alicuotas(self):
        out = []
        for pct in DISPLAY_ALICUOTAS:
            key = _pct_key(pct)
            out.append({"key": f"base_{key}", "header": f"Neto {pct:g}%", "type": "amount"})
            out.append({"key": f"iva_{key}", "header": f"IVA {pct:g}%", "type": "amount"})
        return out

    def _columns_common_tail(self):
        return [
            {"key": "perc_iva", "header": "Perc IVA", "type": "amount"},
            {"key": "perc_iibb", "header": "Perc IIBB", "type": "amount"},
            {"key": "perc_mun", "header": "Perc Mun", "type": "amount"},
            {"key": "internos", "header": "Otros Trib", "type": "amount"},
            {"key": "otros", "header": "Otras Perc", "type": "amount"},
            {"key": "total", "header": "Total", "type": "amount", "width": 16},
        ]

    def _columns_sales(self):
        return self._columns_common_head() + self._columns_alicuotas() + self._columns_common_tail()

    def _columns_purchases(self):
        return (
            self._columns_common_head()
            + self._columns_alicuotas()
            + self._columns_common_tail()
            + [
                {"key": "credito_fiscal_computable", "header": "Cred Fiscal Comput", "type": "amount"},
                {"key": "despacho_importacion", "header": "Desp Importación", "type": "text", "width": 18},
            ]
        )

    @staticmethod
    def _compute_totals(rows):
        if not rows:
            return {}
        keys = [
            "no_gravado", "exento", "neto_gravado",
            "perc_iva", "perc_iibb", "perc_mun",
            "internos", "otros", "total", "iva_total",
            "credito_fiscal_computable",
        ] + [f"base_{_pct_key(p)}" for p in DISPLAY_ALICUOTAS] \
          + [f"iva_{_pct_key(p)}" for p in DISPLAY_ALICUOTAS]
        out = {}
        for k in keys:
            out[k] = sum((r.get(k) or 0.0) for r in rows)
        return out


def _pct_key(pct):
    """`21.0` → `'21'`, `10.5` → `'10_5'` — para usar como sufijo en keys."""
    if pct == int(pct):
        return str(int(pct))
    return str(pct).replace(".", "_")
