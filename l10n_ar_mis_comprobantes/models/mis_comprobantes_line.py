# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Modelo `l10n_ar.mis.comprobantes.line` — una fila del XLS importado.

Cada line representa un comprobante listado en el portal "Mis
Comprobantes". Puede ser:

  * un comprobante emitido por la company (kind='emitted') →
    matchea con una `account.move` move_type='out_invoice'/'out_refund'.
  * un comprobante recibido (kind='received') → matchea con
    'in_invoice'/'in_refund'.

`match_state` se calcula por `import_id._action_match()`.

Cuando `match_state == 'solo_afip'` (existe en AFIP, no en Odoo) se
puede usar ``action_create_move()`` para crear automáticamente un
``account.move`` con el partner detectado por CUIT, un producto
genérico configurado en la empresa, y el IVA inferido del ratio
``imp_iva / imp_neto_gravado``.
"""
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

_logger = logging.getLogger(__name__)


class MisComprobantesLine(models.Model):
    _name = "l10n_ar.mis.comprobantes.line"
    _description = "Mis Comprobantes — línea del batch"
    _order = "fecha_emision desc, pto_vta, nro_desde"

    import_id = fields.Many2one(
        "l10n_ar.mis.comprobantes.import",
        ondelete="cascade",
        required=True,
        string="Batch",
    )
    company_id = fields.Many2one(related="import_id.company_id", store=True)
    kind = fields.Selection(
        selection=[
            ("emitted", "Emitido"),
            ("received", "Recibido"),
        ],
        required=True,
    )
    fecha_emision = fields.Date(string="Fecha emisión")
    tipo_cbte = fields.Integer(string="Tipo cbte (AFIP)")
    pto_vta = fields.Integer(string="Pto. Venta")
    nro_desde = fields.Integer(string="Nro Desde")
    nro_hasta = fields.Integer(string="Nro Hasta")
    cae = fields.Char(string="CAE / CAI / CAEA")
    doc_tipo_partner = fields.Char(string="Tipo doc partner")
    doc_nro_partner = fields.Char(string="Nro doc partner")
    denom_partner = fields.Char(string="Denominación partner")
    moneda = fields.Char(default="PES", size=3)
    tipo_cambio = fields.Float(default=1)
    # Buckets per alícuota — el XLS de ARCA discrimina explícitamente.
    neto_iva_0    = fields.Float(string="Neto Grav. IVA 0%")
    neto_iva_2_5  = fields.Float(string="Neto Grav. IVA 2,5%")
    iva_2_5       = fields.Float(string="IVA 2,5%")
    neto_iva_5    = fields.Float(string="Neto Grav. IVA 5%")
    iva_5         = fields.Float(string="IVA 5%")
    neto_iva_10_5 = fields.Float(string="Neto Grav. IVA 10,5%")
    iva_10_5      = fields.Float(string="IVA 10,5%")
    neto_iva_21   = fields.Float(string="Neto Grav. IVA 21%")
    iva_21        = fields.Float(string="IVA 21%")
    neto_iva_27   = fields.Float(string="Neto Grav. IVA 27%")
    iva_27        = fields.Float(string="IVA 27%")
    imp_neto_gravado = fields.Float(string="Neto gravado total")
    imp_neto_no_gravado = fields.Float(string="Neto no gravado")
    imp_op_exentas = fields.Float(string="Op. exentas")
    imp_otros_tributos = fields.Float(string="Otros tributos")
    imp_iva = fields.Float(string="Total IVA")
    imp_total = fields.Float(string="Total")

    move_id = fields.Many2one(
        "account.move",
        string="Comprobante en Odoo",
        ondelete="set null",
    )
    match_state = fields.Selection(
        selection=[
            ("pending", "Pendiente cotejo"),
            ("ok", "OK"),
            ("solo_afip", "Sólo en AFIP"),
            ("solo_odoo", "Sólo en Odoo"),
            ("amount_diff", "Diferencia importe"),
        ],
        default="pending",
        string="Estado cotejo",
    )
    match_diff_total = fields.Float(
        string="Diferencia total",
        help="imp_total (AFIP) − amount_total (Odoo). Cero si coinciden.",
    )

    # ------------------------------------------------------------------
    # Match
    # ------------------------------------------------------------------
    def _find_move(self):
        """Busca el `account.move` que matchea con esta line.

        Estrategia:
          1. CAE (key única globalmente, stored).
          2. (tipo, journal pos, nro) — el `l10n_latam_document_number`
             es computed NON-stored, no se puede meter en `search()`.
             Filtramos por SQL-friendly fields y matcheamos el nro en
             Python.
        """
        self.ensure_one()
        Move = self.env["account.move"].sudo()
        company = self.import_id.company_id
        move_type_dom = (
            ("move_type", "in", ["out_invoice", "out_refund"])
            if self.kind == "emitted"
            else ("move_type", "in", ["in_invoice", "in_refund"])
        )
        # 1) Por CAE (más confiable).
        if self.cae:
            m = Move.search([
                ("company_id", "=", company.id),
                move_type_dom,
                ("l10n_ar_afip_auth_code", "=", self.cae),
            ], limit=1)
            if m:
                return m

        # 2) Por (tipo, pos, nro). l10n_latam_document_number es NO stored,
        # así que filtramos por fields stored y comparamos el doc_number
        # en Python.
        if self.tipo_cbte and self.pto_vta and self.nro_desde:
            target_num = "%05d-%08d" % (self.pto_vta, self.nro_desde)
            candidates = Move.search([
                ("company_id", "=", company.id),
                move_type_dom,
                ("l10n_latam_document_type_id.code", "=", str(self.tipo_cbte)),
                ("journal_id.l10n_ar_afip_pos_number", "=", self.pto_vta),
                ("state", "=", "posted"),
            ])
            for cand in candidates:
                if (cand.l10n_latam_document_number or "").endswith(target_num):
                    return cand

        return Move.browse(False)

    def _apply_match(self, move):
        """Setea `match_state` y `move_id` según el move encontrado."""
        self.ensure_one()
        if not move:
            self.write({"match_state": "solo_afip", "move_id": False, "match_diff_total": 0})
            return
        diff = float(self.imp_total or 0) - float(move.amount_total or 0)
        # Comparación con tolerancia 0.01 (centavos).
        if float_compare(self.imp_total or 0, move.amount_total or 0, precision_digits=2) == 0:
            state = "ok"
        else:
            state = "amount_diff"
        self.write({
            "move_id": move.id,
            "match_state": state,
            "match_diff_total": diff,
        })

    def action_open_move(self):
        """Abre el move asociado en una nueva ventana."""
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Auto-creación de account.move desde lines `solo_afip`
    # ------------------------------------------------------------------
    # Mapeo tipo_cbte AFIP → move_type. Para emitidos ya tenemos las
    # facturas (somos los que las emitimos), así que esto solo aplica a
    # recibidos.
    _CBTE_TO_MOVE_TYPE = {
        # Facturas y similares de proveedor → in_invoice
        1: "in_invoice", 2: "in_invoice", 3: "in_refund",
        6: "in_invoice", 7: "in_invoice", 8: "in_refund",
        11: "in_invoice", 12: "in_invoice", 13: "in_refund",
        51: "in_invoice", 52: "in_invoice", 53: "in_refund",
        81: "in_invoice", 82: "in_invoice", 83: "in_invoice",
        # 3, 8, 13, 53, 83 son notas de crédito → in_refund
    }

    def action_create_move(self):
        """Crea un `account.move` (in_invoice/in_refund) en draft a partir
        de los datos del XLS. Solo aplica a `kind=received` y
        `match_state in ('solo_afip', 'pending')`.

        Estrategia:
          * Partner: search por CUIT (vat). Si no existe, crear uno
            básico con name=denom_partner.
          * Journal: company.l10n_ar_mc_default_purchase_journal_id, o
            primer journal type=purchase.
          * Doc type: lookup por `code` (= tipo_cbte).
          * Producto: company.l10n_ar_mc_default_product_id (obligatorio).
          * Línea: una sola con price_unit=imp_neto_gravado y un tax que
            matchee el ratio iva/neto.
          * Setea CAE + auth_mode='CAE' + l10n_latam_document_number.
          * Después del create el usuario abre el move y revisa antes
            de postear (no postea automático — lleva validación humana).
        """
        moves = self.env["account.move"]
        for line in self:
            move = line._do_create_move()
            if move:
                moves |= move
        if len(self) == 1 and moves:
            return moves.action_open_move() if hasattr(moves, "action_open_move") else {
                "type": "ir.actions.act_window",
                "res_model": "account.move",
                "res_id": moves.id,
                "view_mode": "form",
                "target": "current",
            }
        # Bulk: abrir lista filtrada por los moves recién creados.
        return {
            "type": "ir.actions.act_window",
            "name": _("Comprobantes creados"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", moves.ids)],
        }

    def _do_create_move(self):
        self.ensure_one()
        if self.kind != "received":
            raise UserError(_(
                "La auto-creación solo aplica a comprobantes recibidos. "
                "Línea %s tiene kind='%s'."
            ) % (self.id, self.kind))
        if self.match_state == "ok" and self.move_id:
            raise UserError(_(
                "La línea %s ya tiene un comprobante asociado (%s)."
            ) % (self.id, self.move_id.display_name))

        company = self.import_id.company_id
        product = company.l10n_ar_mc_default_product_id
        if not product:
            raise UserError(_(
                "Configurá un producto genérico en Configuración → "
                "Localización Argentina → 'Producto genérico Mis "
                "Comprobantes' antes de crear comprobantes automáticamente."
            ))

        partner = self._find_or_create_partner()

        journal = (
            company.l10n_ar_mc_default_purchase_journal_id
            or self.env["account.journal"].search([
                ("type", "=", "purchase"),
                ("company_id", "=", company.id),
            ], limit=1)
        )
        if not journal:
            raise UserError(_(
                "No hay un diario de compras configurado en la empresa %s."
            ) % company.name)

        # Tipo de comprobante.
        DocType = self.env["l10n_latam.document.type"]
        doc_type = DocType.search([
            ("code", "=", str(self.tipo_cbte)),
            ("country_id.code", "=", "AR"),
        ], limit=1)
        if not doc_type:
            raise UserError(_(
                "No encontré l10n_latam.document.type con código %s."
            ) % self.tipo_cbte)

        # Move type por tipo de cbte.
        move_type = self._CBTE_TO_MOVE_TYPE.get(self.tipo_cbte, "in_invoice")

        # ----------------------------------------------------------
        # Estrategia per-bucket: el XLS de ARCA discrimina neto e IVA
        # por cada alícuota (0% / 2,5% / 5% / 10,5% / 21% / 27%) más
        # neto no gravado, exentas y otros tributos.
        #
        # Generamos UNA invoice_line por cada bucket con valor > 0,
        # cada una con su tax IVA correspondiente. Para FA-B/C donde
        # AFIP no discrimina (todos los buckets en 0, solo total), una
        # línea sin tax con el total - otros tributos.
        #
        # `amount_total` resultante = imp_total del XLS, exacto.
        # ----------------------------------------------------------
        BUCKETS = [
            # (pct, neto_field, iva_field)
            (0.0,  "neto_iva_0",    None),
            (2.5,  "neto_iva_2_5",  "iva_2_5"),
            (5.0,  "neto_iva_5",    "iva_5"),
            (10.5, "neto_iva_10_5", "iva_10_5"),
            (21.0, "neto_iva_21",   "iva_21"),
            (27.0, "neto_iva_27",   "iva_27"),
        ]
        otros = float(self.imp_otros_tributos or 0)
        no_grav = float(self.imp_neto_no_gravado or 0)
        exentas = float(self.imp_op_exentas or 0)
        total = float(self.imp_total or 0)

        invoice_line_cmds = []
        line_label = _("AFIP %s — %s") % (
            self._formatted_doc_number(), self.denom_partner or "",
        )

        # Precarga taxes por alícuota — cache en dict para no re-buscar.
        tax_cache = {}
        def _get_tax(pct):
            if pct not in tax_cache:
                tax_cache[pct] = self._find_tax_by_pct(company, pct)
            return tax_cache[pct]

        # 1) Una línea por cada bucket con neto > 0.
        any_bucket = False
        for pct, neto_f, iva_f in BUCKETS:
            neto_val = float(getattr(self, neto_f) or 0)
            if neto_val <= 0:
                continue
            any_bucket = True
            tax = _get_tax(pct)
            invoice_line_cmds.append((0, 0, {
                "product_id": product.id,
                "name": "%s [IVA %s%%]" % (line_label, str(pct).rstrip("0").rstrip(".")),
                "quantity": 1,
                "price_unit": neto_val,
                "tax_ids": [(6, 0, tax.ids)] if tax else [(6, 0, [])],
            }))

        # 2) Neto No Gravado — sin tax.
        if no_grav > 0:
            invoice_line_cmds.append((0, 0, {
                "product_id": product.id,
                "name": "%s [No Gravado]" % line_label,
                "quantity": 1,
                "price_unit": no_grav,
                "tax_ids": [(6, 0, [])],
            }))

        # 3) Op. Exentas — tax 0% si existe, sino sin tax.
        if exentas > 0:
            tax_exento = _get_tax(0.0)
            invoice_line_cmds.append((0, 0, {
                "product_id": product.id,
                "name": "%s [Exenta]" % line_label,
                "quantity": 1,
                "price_unit": exentas,
                "tax_ids": [(6, 0, tax_exento.ids)] if tax_exento else [(6, 0, [])],
            }))

        # 4) Si no hubo NINGÚN bucket discriminado (FA-B/C típico) ni
        #    no_gravado ni exentas, el portal solo trae imp_total.
        #    Línea única con total - otros, sin IVA computable.
        if not any_bucket and no_grav == 0 and exentas == 0:
            base_total = total - otros
            if base_total > 0:
                invoice_line_cmds.append((0, 0, {
                    "product_id": product.id,
                    "name": "%s [Sin IVA discriminado]" % line_label,
                    "quantity": 1,
                    "price_unit": base_total,
                    "tax_ids": [(6, 0, [])],
                }))

        # 5) Otros Tributos — siempre como línea separada sin tax
        #    (percepciones, internos, etc. — gasto no recuperable).
        if otros > 0:
            invoice_line_cmds.append((0, 0, {
                "product_id": product.id,
                "name": "%s [Otros Tributos / Percepciones]" % line_label,
                "quantity": 1,
                "price_unit": otros,
                "tax_ids": [(6, 0, [])],
            }))

        # ----------------------------------------------------------
        # Moneda extranjera (PREX CARD en USD, etc.)
        # ----------------------------------------------------------
        move_currency = self._resolve_currency(company)

        move_vals = {
            "company_id": company.id,
            "journal_id": journal.id,
            "move_type": move_type,
            "partner_id": partner.id,
            "invoice_date": self.fecha_emision,
            "date": self.fecha_emision,
            "l10n_latam_document_type_id": doc_type.id,
            "l10n_latam_document_number": self._formatted_doc_number(),
            "l10n_ar_afip_auth_code": self.cae or False,
            "l10n_ar_afip_auth_mode": "CAE" if self.cae else False,
            "ref": self._formatted_doc_number(),
            "invoice_line_ids": invoice_line_cmds,
        }
        if move_currency and move_currency != company.currency_id:
            move_vals["currency_id"] = move_currency.id

        move = self.env["account.move"].create(move_vals)

        # Si el total quedó distinto del XLS por redondeo o tax, lo
        # registramos en el chatter y dejamos al humano decidir.
        odoo_total = float_round(move.amount_total, 2)
        afip_total = float_round(self.imp_total or 0, 2)
        diff = odoo_total - afip_total
        body = _(
            "Comprobante creado automáticamente desde Mis Comprobantes (línea #%s). "
            "AFIP: $%s · Odoo: $%s · Δ: $%s"
        ) % (self.id, afip_total, odoo_total, diff)
        move.message_post(body=body)

        # Volcamos el move a la línea y re-cotejamos.
        self._apply_match(move)
        return move

    def action_create_move_bulk(self):
        """Acción server: crea moves para todas las líneas seleccionadas
        que estén en `solo_afip` + `kind=received`.

        Si la selección incluye otras (emitidos / ya matcheadas) las
        ignora silenciosamente — no rompe, simplemente las omite. Si
        ninguna califica, levanta UserError.
        """
        if not self:
            raise UserError(_("No seleccionaste ninguna línea."))
        targets = self.filtered(
            lambda l: l.kind == "received"
            and l.match_state == "solo_afip"
            and not l.move_id
        )
        skipped = len(self) - len(targets)
        if not targets:
            raise UserError(_(
                "Ninguna de las %s líneas seleccionadas califica para "
                "creación automática.\n\nRequisitos:\n"
                "  • kind = Recibido\n"
                "  • match_state = Sólo en AFIP\n"
                "  • Sin comprobante asociado todavía"
            ) % len(self))
        result = targets.action_create_move()
        if skipped:
            result.setdefault("context", {}).update(
                {"info_skipped": skipped}
            )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _formatted_doc_number(self):
        self.ensure_one()
        return "%05d-%08d" % (self.pto_vta, self.nro_desde)

    def _find_or_create_partner(self):
        """Busca partner por CUIT; si no existe, crea uno mínimo."""
        self.ensure_one()
        Partner = self.env["res.partner"].sudo()
        cuit = (self.doc_nro_partner or "").strip()
        if cuit:
            # Comparamos por VAT con/sin formato.
            p = Partner.search([
                ("vat", "in", [cuit, "%s-%s-%s" % (cuit[:2], cuit[2:10], cuit[10:])]),
                "|", ("company_id", "=", self.import_id.company_id.id),
                ("company_id", "=", False),
            ], limit=1)
            if p:
                return p
        # Crear nuevo.
        country_ar = self.env.ref("base.ar", raise_if_not_found=False)
        # IdentificationType (l10n_ar) — preferentemente '80' (CUIT).
        IdType = self.env["l10n_latam.identification.type"]
        id_type = IdType.search([
            ("l10n_ar_afip_code", "=", self.doc_tipo_partner or "80"),
        ], limit=1)
        # Responsabilidad: por defecto Responsable Inscripto si CUIT
        # empieza con 20/23/24/27/30/33/34. No tenemos cómo saber
        # exactamente, asignamos RI como guess.
        ResType = self.env["l10n_ar.afip.responsibility.type"]
        ri = ResType.search([("code", "=", "1")], limit=1)
        vals = {
            "name": (self.denom_partner or _("Proveedor %s") % cuit)[:200],
            "vat": cuit or False,
            "country_id": country_ar.id if country_ar else False,
        }
        if id_type:
            vals["l10n_latam_identification_type_id"] = id_type.id
        if ri:
            vals["l10n_ar_afip_responsibility_type_id"] = ri.id
        partner = Partner.create(vals)
        _logger.info(
            "Creado partner #%s para CUIT %s (%s)",
            partner.id, cuit, partner.name,
        )
        return partner

    def _resolve_currency(self, company):
        """Devuelve `res.currency` que matchea `self.moneda` del XLS.

        Códigos comunes:
          * "$"       → ARS (default)
          * "USD"     → USD
          * "EUR"     → EUR
          * "DOL"     → USD (código AFIP)

        Si no encuentra, devuelve la currency de la company.
        """
        self.ensure_one()
        Currency = self.env["res.currency"].sudo()
        m = (self.moneda or "").strip().upper()
        if not m or m == "$" or m == "ARS" or m == "PES":
            return company.currency_id
        # Mapping AFIP → ISO.
        afip_iso = {"DOL": "USD", "060": "EUR"}
        m = afip_iso.get(m, m)
        cur = Currency.search([("name", "=", m)], limit=1)
        return cur or company.currency_id

    def _find_tax_by_pct(self, company, pct):
        """Devuelve un account.tax type=purchase con `amount=pct` (en %).

        Si hay varios candidatos prioriza el que NO sea price_include
        (más limpio para FA-A). Si no hay ninguno, devuelve recordset
        vacío.
        """
        self.ensure_one()
        Tax = self.env["account.tax"].sudo()
        candidates = Tax.search([
            ("company_id", "=", company.id),
            ("type_tax_use", "=", "purchase"),
            ("amount", "=", pct),
            ("amount_type", "=", "percent"),
            ("active", "=", True),
        ])
        if not candidates:
            return Tax.browse(False)
        # Preferir el que NO es price_include (default Odoo).
        no_inc = candidates.filtered(lambda t: not t.price_include)
        return (no_inc or candidates)[:1]
