# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Wizard: generar Libro IVA Digital RG 5616 — ZIP con los 5 TXT.

UX: el usuario abre el wizard desde el menú "Reportes → Argentina →
Libro IVA Digital", elige período (date_from / date_to) y sale ZIP.
Recomendado: período mensual completo (primer/último día del mes).

Genera, dependiendo del contenido del período, hasta 5 archivos:

    - LIBRO_IVA_DIGITAL_VENTAS_CBTE.txt           (siempre, si hay ventas)
    - LIBRO_IVA_DIGITAL_VENTAS_ALICUOTAS.txt      (siempre, si hay ventas)
    - LIBRO_IVA_DIGITAL_COMPRAS_CBTE.txt          (si hay compras)
    - LIBRO_IVA_DIGITAL_COMPRAS_ALICUOTAS.txt     (si hay compras)
    - LIBRO_IVA_DIGITAL_IMPORTACION_BIENES_ALICUOTA.txt
        (si hay compras tipo 66 = despacho importación)

Inspirado en (no copiado): `enterprise/l10n_ar_reports/models/l10n_ar_vat_book.py`
y `nimarosa/afip_libro_iva` (gem Ruby de referencia).
"""
import base64
import io
import logging
import zipfile
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import record_specs as rs
from ..lib import txt_format as txt

_logger = logging.getLogger(__name__)


class LibroIvaDigitalWizard(models.TransientModel):
    _name = "l10n_ar.libro.iva.digital.wizard"
    _description = "Libro IVA Digital — generación de TXT (RG 5616)"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
        help="Primer día del período. Recomendado: día 1 del mes.",
    )
    date_to = fields.Date(
        required=True,
        default=lambda self: fields.Date.today(),
        help="Último día del período. Recomendado: último día del mes.",
    )
    file_name = fields.Char(readonly=True)
    file_content = fields.Binary(readonly=True, attachment=False)
    state = fields.Selection(
        [("draft", "Configurar"), ("done", "Listo")],
        default="draft",
    )

    # ------------------------------------------------------------------
    # Botón
    # ------------------------------------------------------------------
    def action_generate(self):
        """Genera el ZIP en memoria y lo deja en el wizard para descarga."""
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("El 'Desde' debe ser anterior o igual al 'Hasta'."))

        files = self._generate_txts()
        if not files:
            raise UserError(_(
                "No se encontraron comprobantes posted para %(c)s entre "
                "%(d1)s y %(d2)s.",
                c=self.company_id.name,
                d1=self.date_from, d2=self.date_to,
            ))

        # Empaquetar en ZIP.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in files.items():
                zf.writestr(fname, content)
        buf.seek(0)

        period = self.date_from.strftime("%Y%m")
        self.write({
            "file_name": "libro_iva_digital_%s_%s.zip" % (
                period, self.company_id.id,
            ),
            "file_content": base64.b64encode(buf.getvalue()),
            "state": "done",
        })

        # Devolver una action que recarga el wizard, así el user ve el
        # campo `file_content` con el botón de descarga.
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    # ------------------------------------------------------------------
    # Generación
    # ------------------------------------------------------------------
    def _generate_txts(self):
        """Itera moves del período y arma cada TXT.

        :return: dict {filename: bytes}. Solo incluye los archivos que
            tienen al menos un registro.
        """
        self.ensure_one()
        sales, purchases = self._get_moves()

        ventas_cbte = []
        ventas_alic = []
        for inv in sales:
            cbte = self._build_cbte_dict(inv, sale=True)
            ventas_cbte.append(rs.build_ventas_cbte_record(cbte))
            for alic in self._iter_alicuotas(inv):
                ventas_alic.append(rs.build_ventas_alicuotas_record({
                    "tipo_cbte": cbte["tipo_cbte"],
                    "pto_vta": cbte["pto_vta"],
                    "nro_cbte": cbte["nro_cbte"],
                    "neto_gravado": alic["base"],
                    "alicuota": alic["percent"],
                    "iva_liquidado": alic["importe"],
                }))

        compras_cbte = []
        compras_alic = []
        compras_imp_alic = []  # Importación bienes (tipo 66)
        for inv in purchases:
            cbte = self._build_cbte_dict(inv, sale=False)
            compras_cbte.append(rs.build_compras_cbte_record(cbte))
            es_importacion = cbte["tipo_cbte"] == 66
            for alic in self._iter_alicuotas(inv):
                row = {
                    "tipo_cbte": cbte["tipo_cbte"],
                    "pto_vta": cbte["pto_vta"],
                    "nro_cbte": cbte["nro_cbte"],
                    "cod_doc_vendedor": cbte["cod_doc_vendedor"],
                    "nro_doc": cbte["nro_doc"],
                    "neto_gravado": alic["base"],
                    "alicuota": alic["percent"],
                    "iva_liquidado": alic["importe"],
                }
                rec = rs.build_compras_alicuotas_record(row)
                if es_importacion:
                    compras_imp_alic.append(rec)
                else:
                    compras_alic.append(rec)

        # Convertir lista de strings → bytes con encoding y CRLF.
        files = {}
        if ventas_cbte:
            files["LIBRO_IVA_DIGITAL_VENTAS_CBTE.txt"] = self._encode_lines(ventas_cbte)
        if ventas_alic:
            files["LIBRO_IVA_DIGITAL_VENTAS_ALICUOTAS.txt"] = self._encode_lines(ventas_alic)
        if compras_cbte:
            files["LIBRO_IVA_DIGITAL_COMPRAS_CBTE.txt"] = self._encode_lines(compras_cbte)
        if compras_alic:
            files["LIBRO_IVA_DIGITAL_COMPRAS_ALICUOTAS.txt"] = self._encode_lines(compras_alic)
        if compras_imp_alic:
            files["LIBRO_IVA_DIGITAL_IMPORTACION_BIENES_ALICUOTA.txt"] = self._encode_lines(compras_imp_alic)

        _logger.info(
            "Libro IVA Digital generado para %s [%s..%s]: ventas=%d compras=%d imp=%d",
            self.company_id.name, self.date_from, self.date_to,
            len(ventas_cbte), len(compras_cbte), len(compras_imp_alic),
        )
        return files

    @staticmethod
    def _encode_lines(records):
        """Encode lista de strings (registros ya formateados) a bytes Latin-1
        con separador CRLF y trailing CRLF."""
        return txt.join_records(
            [txt.compose_record([r]) for r in records]
        )

    # ------------------------------------------------------------------
    # Helpers de iteración
    # ------------------------------------------------------------------
    def _get_moves(self):
        """Devuelve (sales, purchases) — recordsets ordenados por fecha+nro."""
        Move = self.env["account.move"]
        base_domain = [
            ("company_id", "=", self.company_id.id),
            ("state", "=", "posted"),
            ("invoice_date", ">=", self.date_from),
            ("invoice_date", "<=", self.date_to),
            # Solo journals que usan documentos AFIP.
            ("journal_id.l10n_latam_use_documents", "=", True),
        ]
        sales = Move.search(
            base_domain + [("move_type", "in", ("out_invoice", "out_refund"))],
            order="invoice_date, name, id",
        )
        purchases = Move.search(
            base_domain + [("move_type", "in", ("in_invoice", "in_refund"))],
            order="invoice_date, name, id",
        )
        return sales, purchases

    def _iter_alicuotas(self, inv):
        """Devuelve lista de dicts {percent, base, importe} para los TXT
        de ALICUOTAS.

        Reusa `inv._get_vat()` (community l10n_ar) que ya devuelve los
        items con código AFIP. Si el comprobante NO tiene IVA discriminado
        (FB, FC, NC-B/C — letra B/C), AFIP exige al menos UNA fila de
        alícuota con base=imp_total y alicuota=0% para los que llevan IVA
        no discriminado. Ese caso lo armamos con un fallback.
        """
        items = inv._get_vat() or []
        # Determinar si la NC arrastra signo o no.
        sign = self._get_sign(inv)
        rows = []
        for it in items:
            pct = rs.AFIP_IVA_ID_TO_PERCENT.get(str(it.get("Id")), 0.0)
            rows.append({
                "percent": pct,
                "base": (it.get("BaseImp") or 0.0) * sign,
                "importe": (it.get("Importe") or 0.0) * sign,
            })
        # Si no hay items, fallback: una fila al 0% con el total como base.
        if not rows:
            rows.append({
                "percent": 0.0,
                "base": (inv.amount_untaxed or 0.0) * sign,
                "importe": 0.0,
            })
        return rows

    def _get_sign(self, inv):
        """+1 / -1 según el tipo de cbte.

        Convención AFIP del Libro IVA: las NC se identifican por su código
        de tipo de comprobante (3=NC-A, 8=NC-B, 13=NC-C, etc.). Para esos
        códigos, los importes van **positivos** — el signo lo indica el
        tipo. Para casos donde Odoo usa out_refund con el MISMO código que
        out_invoice (improbable en l10n_ar, pero por las dudas), invertimos.
        """
        try:
            doc_code = int(inv.l10n_latam_document_type_id.code or 0)
        except (TypeError, ValueError):
            doc_code = 0
        if doc_code in rs.NC_DOC_CODES:
            return 1
        if inv.move_type in ("out_refund", "in_refund"):
            return -1
        return 1

    # ------------------------------------------------------------------
    # Construcción del registro CBTE (cabecera del comprobante)
    # ------------------------------------------------------------------
    def _build_cbte_dict(self, inv, sale=True):
        """Arma el dict que `build_*_cbte_record` espera."""
        sign = self._get_sign(inv)
        amounts = inv._l10n_ar_get_amounts() if hasattr(inv, "_l10n_ar_get_amounts") else {}

        try:
            tipo_cbte = int(inv.l10n_latam_document_type_id.code or 0)
        except (TypeError, ValueError):
            tipo_cbte = 0
        pos, nro = self._split_pos_and_nro(inv)

        # Doc del partner.
        doc_code, doc_nro = self._partner_doc(inv.partner_id)

        # Razón social (truncada a 30, sin tildes problemáticas).
        razon = inv.partner_id.name or ""

        # Cotización: invoice_currency_rate es ARS-by-FX (e.g., USD→0.00071).
        # Para Libro IVA queremos FX-by-ARS (USD→1399.5). Invertimos.
        cur = inv.currency_id
        company_cur = inv.company_id.currency_id
        if cur == company_cur:
            tipo_cambio = 1.0
            cod_moneda = "PES"
        else:
            inv_rate = inv.invoice_currency_rate or 1.0
            tipo_cambio = (1.0 / inv_rate) if inv_rate else 1.0
            cod_moneda = (
                getattr(cur, "l10n_ar_afip_code", None) or "PES"
            )

        # Cantidad de alícuotas distintas (mínimo 1).
        cant = max(1, len(self._iter_alicuotas(inv)))

        # Código de operación: 'X'=exportación, 'Z'=zona franca, etc.
        cod_op = self._get_codigo_operacion(inv)

        common = {
            "fecha": inv.invoice_date,
            "tipo_cbte": tipo_cbte,
            "pto_vta": pos,
            "nro_cbte": nro,
            "razon_social": razon,
            "imp_total": (inv.amount_total or 0.0) * sign,
            "imp_no_gravado": (amounts.get("vat_untaxed_base_amount") or 0.0) * sign,
            "perc_no_categ": 0,  # raro en sale; queda 0
            "imp_exento": (amounts.get("vat_exempt_base_amount") or 0.0) * sign,
            "perc_nacionales": (amounts.get("vat_perc_amount") or 0.0) * sign
                + (amounts.get("profits_perc_amount") or 0.0) * sign,
            "perc_iibb": (amounts.get("iibb_perc_amount") or 0.0) * sign,
            "perc_municipales": (amounts.get("mun_perc_amount") or 0.0) * sign,
            "imp_internos": (amounts.get("intern_tax_amount") or 0.0) * sign,
            "cod_moneda": cod_moneda,
            "tipo_cambio": tipo_cambio,
            "cant_alicuotas": cant,
            "cod_operacion": cod_op,
            "otros_tributos": (amounts.get("other_taxes_amount") or 0.0) * sign
                + (amounts.get("other_perc_amount") or 0.0) * sign,
            "venc_pago": inv.invoice_date_due,
        }
        if sale:
            common["cod_doc_comprador"] = doc_code
            common["nro_doc"] = doc_nro
        else:
            common["cod_doc_vendedor"] = doc_code
            common["nro_doc"] = doc_nro
            # Importación de bienes: nº de despacho = l10n_latam_document_number.
            if tipo_cbte == 66:
                common["despacho_importacion"] = inv.l10n_latam_document_number or ""
            common["credito_fiscal_computable"] = (amounts.get("vat_amount") or 0.0) * sign

        return common

    @staticmethod
    def _split_pos_and_nro(inv):
        """De `01001-00000123` saca (1001, 123). Robusto si el name viene
        con prefijo (FA-A 01001-00000123)."""
        s = inv.l10n_latam_document_number or ""
        if "-" in s:
            parts = s.split("-")
            try:
                return int(parts[-2]), int(parts[-1])
            except (ValueError, IndexError):
                pass
        # Fallback: del journal y un autoincrement.
        return inv.journal_id.l10n_ar_afip_pos_number or 0, 0

    @staticmethod
    def _partner_doc(partner):
        """(cod_doc_afip, nro_doc) — 80=CUIT, 86=CUIL, 96=DNI, 99=CF."""
        if not partner:
            return 99, ""
        idt = partner.l10n_latam_identification_type_id
        if idt and idt.l10n_ar_afip_code:
            try:
                code = int(idt.l10n_ar_afip_code)
            except (TypeError, ValueError):
                code = 99
        else:
            code = 99
        vat = (partner.vat or "").strip()
        digits = "".join(c for c in vat if c.isdigit())
        if code == 99 or not digits:
            return 99, "0"
        return code, digits

    def _get_codigo_operacion(self, inv):
        """Código de operación AFIP (1 char).

        Inspirado en enterprise (`_vat_book_get_REGINFO_CV_CBTE`):
            'X' = exportación (letra E del comprobante)
            'Z' = receptor zona franca (resp 10 = "IVA Liberado")
            'E' = exenta (sin neto gravado, solo exento o no gravado)
            'N' = no gravado (sin neto gravado, solo no_gravado)
            ' ' = default
        """
        letter = (inv.l10n_latam_document_type_id.l10n_ar_letter or "").upper()
        if letter == "E":
            return "X"
        partner_resp = inv.partner_id.l10n_ar_afip_responsibility_type_id
        if partner_resp and partner_resp.code == "10":
            return "Z"
        amounts = inv._l10n_ar_get_amounts() if hasattr(inv, "_l10n_ar_get_amounts") else {}
        neto_gravado = inv.amount_untaxed - (
            amounts.get("vat_exempt_base_amount", 0)
            + amounts.get("vat_untaxed_base_amount", 0)
        )
        if neto_gravado <= 0.005:
            if amounts.get("vat_exempt_base_amount", 0) > 0:
                return "E"
            if amounts.get("vat_untaxed_base_amount", 0) > 0:
                return "N"
        return " "
