# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Vista SQL `account.ar.vat.line` — 1 row por account.move (posted, con
documentos AFIP), con todas las columnas del Subdiario IVA pre-agregadas
en SQL.

Fuente única de verdad para:
    - Vista interactiva (tree / pivot / search) bajo Argentina → Subdiario IVA
    - Wizard de export PDF / XLSX (que arma sus filas leyendo de acá).

Inspirado en (no copiado) ``odoo/enterprise/l10n_ar_reports/report/
account_ar_vat_line.py`` (Apr 2026). Diferencias intencionales:

    * **Granularidad por move**, no por (move × tax_type). En community el
      `move_type` ya define unívocamente si es venta o compra; agrupar por
      tax_type del impuesto agregaba una distinción que en la práctica no
      sirve para el subdiario.
    * **No gravado y Exento separados**. Enterprise los agrupa en
      ``not_taxed``; nosotros los exponemos como columnas distintas
      porque el contador los suele querer separados.
    * **ABS()** en cada SUM. Enterprise mantiene el signo del `balance`
      (negativo en ventas, positivo en compras) e invierte después en
      Python. Nosotros nos aliamos con la convención visual del
      subdiario (todo positivo); el signo del comprobante (FA-A vs NC-A)
      ya distingue si suma o resta a través del ``document_type_id``.
    * **Sin column_group_key / split_options_per_column_group** —
      enterprise lo necesita para el motor `account.report` (comparativos
      multi-período). Nosotros usamos vistas estándar tree/pivot.

Mapping AFIP → columna (ver ``addons/l10n_ar_afip_ws/lib/`` para más):

    `account.tax.group.l10n_ar_vat_afip_code`:
        '4' → 10.5%   '5' → 21%   '6' → 27%   '8' → 5%   '9' → 2.5%
        '1' → Exento  '2' → No gravado  '7' → Exento Imp.
        '0','3' → "otros no gravados" (acá los meto en `no_gravado`).

    `account.tax.group.l10n_ar_tribute_afip_code`:
        '06' → Perc IVA          → ``perc_iva``
        '07' → Perc IIBB         → ``perc_iibb``
        '03','08' → Municipales  → ``perc_municipal``
        '09' → Otras nacionales  → ``perc_otras``
        '02','04','05','99' → Provinciales/Internos/Otros → ``otros_tributos``
"""
from odoo import api, fields, models, tools
from odoo.tools import SQL


class AccountArVatLine(models.Model):
    _name = "account.ar.vat.line"
    _description = "Línea VAT pre-agregada para Subdiario IVA"
    _auto = False
    _order = "invoice_date asc, name asc, id asc"
    _rec_name = "name"

    # ------------------------------------------------------------------
    # Identidad
    # ------------------------------------------------------------------
    move_id = fields.Many2one("account.move", "Comprobante", readonly=True)
    name = fields.Char("Número", readonly=True)
    invoice_date = fields.Date("Fecha", readonly=True)
    date = fields.Date("Fecha contable", readonly=True)
    state = fields.Selection(
        [("draft", "Borrador"), ("posted", "Asentado"), ("cancel", "Cancelado")],
        string="Estado", readonly=True,
    )
    move_type = fields.Selection(
        [
            ("out_invoice", "Factura de cliente"),
            ("out_refund", "Nota de crédito de cliente"),
            ("in_invoice", "Factura de proveedor"),
            ("in_refund", "Nota de crédito de proveedor"),
        ],
        string="Tipo", readonly=True,
    )
    tax_type = fields.Selection(
        [("sale", "Ventas"), ("purchase", "Compras")],
        string="Operación", readonly=True,
    )

    # ------------------------------------------------------------------
    # Partner / journal / company
    # ------------------------------------------------------------------
    partner_id = fields.Many2one("res.partner", "Partner", readonly=True)
    commercial_partner_id = fields.Many2one(
        "res.partner", "Partner comercial", readonly=True
    )
    partner_name = fields.Char("Razón social", readonly=True)
    cuit = fields.Char("CUIT", readonly=True)
    afip_responsibility_type_id = fields.Many2one(
        "l10n_ar.afip.responsibility.type", "Cond. IVA", readonly=True
    )
    document_type_id = fields.Many2one(
        "l10n_latam.document.type", "Tipo de comprobante", readonly=True
    )
    journal_id = fields.Many2one("account.journal", "Diario", readonly=True)
    company_id = fields.Many2one("res.company", "Empresa", readonly=True)
    currency_id = fields.Many2one("res.currency", "Moneda", readonly=True)

    company_currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True
    )

    # ------------------------------------------------------------------
    # Importes (todos en moneda compañía, ABS, 1 row por move)
    # ------------------------------------------------------------------
    amount_total = fields.Monetary(
        "Total", currency_field="company_currency_id", readonly=True
    )

    base_21 = fields.Monetary("Neto 21%", currency_field="company_currency_id", readonly=True)
    vat_21 = fields.Monetary("IVA 21%", currency_field="company_currency_id", readonly=True)
    base_10_5 = fields.Monetary("Neto 10,5%", currency_field="company_currency_id", readonly=True)
    vat_10_5 = fields.Monetary("IVA 10,5%", currency_field="company_currency_id", readonly=True)
    base_27 = fields.Monetary("Neto 27%", currency_field="company_currency_id", readonly=True)
    vat_27 = fields.Monetary("IVA 27%", currency_field="company_currency_id", readonly=True)
    base_5 = fields.Monetary("Neto 5%", currency_field="company_currency_id", readonly=True)
    vat_5 = fields.Monetary("IVA 5%", currency_field="company_currency_id", readonly=True)
    base_2_5 = fields.Monetary("Neto 2,5%", currency_field="company_currency_id", readonly=True)
    vat_2_5 = fields.Monetary("IVA 2,5%", currency_field="company_currency_id", readonly=True)

    # Computados en SQL directamente (para que read_group / pivot puedan
    # sumarlos). Si fueran `compute=` Python no-stored, fallarían en
    # `_field_to_sql` con "Cannot convert ... to SQL because it is not
    # stored". El motor pivot necesita SQL puro.
    neto_gravado = fields.Monetary(
        "Neto Gravado", currency_field="company_currency_id", readonly=True,
        help="Suma de todas las bases con alícuota IVA != 0% (21%, 10.5%, 27%, 5%, 2.5%).",
    )
    iva_total = fields.Monetary(
        "IVA Total", currency_field="company_currency_id", readonly=True,
        help="Suma del IVA liquidado en todas las alícuotas.",
    )

    no_gravado = fields.Monetary(
        "No Gravado", currency_field="company_currency_id", readonly=True
    )
    exento = fields.Monetary(
        "Exento", currency_field="company_currency_id", readonly=True
    )

    perc_iva = fields.Monetary(
        "Perc. IVA", currency_field="company_currency_id", readonly=True
    )
    perc_iibb = fields.Monetary(
        "Perc. IIBB", currency_field="company_currency_id", readonly=True
    )
    perc_municipal = fields.Monetary(
        "Perc. Municipal", currency_field="company_currency_id", readonly=True
    )
    perc_otras = fields.Monetary(
        "Otras Perc. Nac.", currency_field="company_currency_id", readonly=True,
        help="Percepciones nacionales no-IVA (Ganancias, etc).",
    )
    otros_tributos = fields.Monetary(
        "Otros Tributos", currency_field="company_currency_id", readonly=True,
        help="Tributos provinciales, internos y otros (códigos AFIP 02/04/05/99).",
    )

    # ------------------------------------------------------------------
    # Acción: abrir el move desde la línea
    # ------------------------------------------------------------------
    def action_open_move(self):
        self.ensure_one()
        return self.move_id.get_formview_action()

    # ------------------------------------------------------------------
    # Vista SQL — `_table_query` evalúa en cada acceso (Odoo 19+).
    # ------------------------------------------------------------------
    @property
    def _table_query(self):
        return self._build_query()

    @api.model
    def _build_query(self) -> SQL:
        return SQL(
            """
            WITH tax_lines AS (
                SELECT
                    aml.id            AS aml_id,
                    aml.move_id,
                    ntg.l10n_ar_vat_afip_code     AS vat_code,
                    ntg.l10n_ar_tribute_afip_code AS tribute_code,
                    aml.balance
                FROM account_move_line aml
                JOIN account_tax        nt  ON aml.tax_line_id = nt.id
                JOIN account_tax_group  ntg ON nt.tax_group_id = ntg.id
                WHERE aml.tax_line_id IS NOT NULL
            ),
            base_lines AS (
                SELECT
                    aml.id     AS aml_id,
                    aml.move_id,
                    -- MAX para evitar duplicar si una línea tiene varios impuestos.
                    MAX(btg.l10n_ar_vat_afip_code) AS vat_code,
                    aml.balance
                FROM account_move_line aml
                JOIN account_move_line_account_tax_rel amltr ON aml.id = amltr.account_move_line_id
                JOIN account_tax        bt  ON amltr.account_tax_id = bt.id
                JOIN account_tax_group  btg ON bt.tax_group_id = btg.id
                GROUP BY aml.id, aml.move_id, aml.balance
            ),
            move_aml AS (
                SELECT aml.id, aml.move_id FROM account_move_line aml
            )
            SELECT
                am.id                   AS id,
                am.id                   AS move_id,
                am.name,
                am.invoice_date,
                am.date,
                am.state,
                am.move_type,
                am.partner_id,
                am.commercial_partner_id,
                am.journal_id,
                am.company_id,
                am.currency_id,
                -- Total en MONEDA COMPAÑIA (ARS), positivo. Importante:
                -- `am.amount_total` esta en moneda del cbte (puede ser USD)
                -- y romperia coherencia con base_*/vat_* (que vienen de
                -- account_move_line.balance, en moneda compañia). El
                -- Subdiario IVA argentino se presenta en pesos (RG 5616).
                ABS(am.amount_total_signed) AS amount_total,
                am.l10n_latam_document_type_id        AS document_type_id,
                am.l10n_ar_afip_responsibility_type_id AS afip_responsibility_type_id,
                rp.name AS partner_name,
                rp.vat  AS cuit,
                CASE
                    WHEN am.move_type IN ('out_invoice','out_refund') THEN 'sale'
                    ELSE 'purchase'
                END AS tax_type,

                COALESCE(SUM(CASE WHEN base.vat_code = '5' THEN ABS(base.balance) END), 0) AS base_21,
                COALESCE(SUM(CASE WHEN tax.vat_code  = '5' THEN ABS(tax.balance)  END), 0) AS vat_21,
                COALESCE(SUM(CASE WHEN base.vat_code = '4' THEN ABS(base.balance) END), 0) AS base_10_5,
                COALESCE(SUM(CASE WHEN tax.vat_code  = '4' THEN ABS(tax.balance)  END), 0) AS vat_10_5,
                COALESCE(SUM(CASE WHEN base.vat_code = '6' THEN ABS(base.balance) END), 0) AS base_27,
                COALESCE(SUM(CASE WHEN tax.vat_code  = '6' THEN ABS(tax.balance)  END), 0) AS vat_27,
                COALESCE(SUM(CASE WHEN base.vat_code = '8' THEN ABS(base.balance) END), 0) AS base_5,
                COALESCE(SUM(CASE WHEN tax.vat_code  = '8' THEN ABS(tax.balance)  END), 0) AS vat_5,
                COALESCE(SUM(CASE WHEN base.vat_code = '9' THEN ABS(base.balance) END), 0) AS base_2_5,
                COALESCE(SUM(CASE WHEN tax.vat_code  = '9' THEN ABS(tax.balance)  END), 0) AS vat_2_5,

                -- Totales agregados (en SQL para que read_group/pivot funcione).
                COALESCE(SUM(CASE WHEN base.vat_code IN ('4','5','6','8','9')
                                  THEN ABS(base.balance) END), 0) AS neto_gravado,
                COALESCE(SUM(CASE WHEN tax.vat_code  IN ('4','5','6','8','9')
                                  THEN ABS(tax.balance)  END), 0) AS iva_total,

                COALESCE(SUM(CASE WHEN base.vat_code = '1' THEN ABS(base.balance) END), 0) AS exento,
                COALESCE(SUM(CASE WHEN base.vat_code IN ('0','2','3','7') THEN ABS(base.balance) END), 0) AS no_gravado,

                COALESCE(SUM(CASE WHEN tax.tribute_code = '06' THEN ABS(tax.balance) END), 0) AS perc_iva,
                COALESCE(SUM(CASE WHEN tax.tribute_code = '07' THEN ABS(tax.balance) END), 0) AS perc_iibb,
                COALESCE(SUM(CASE WHEN tax.tribute_code IN ('03','08') THEN ABS(tax.balance) END), 0) AS perc_municipal,
                COALESCE(SUM(CASE WHEN tax.tribute_code = '09' THEN ABS(tax.balance) END), 0) AS perc_otras,
                COALESCE(SUM(CASE WHEN tax.tribute_code IN ('02','04','05','99') THEN ABS(tax.balance) END), 0) AS otros_tributos
            FROM account_move am
            JOIN account_journal aj ON aj.id = am.journal_id
            LEFT JOIN res_partner   rp  ON rp.id = am.commercial_partner_id
            LEFT JOIN move_aml      ma  ON ma.move_id = am.id
            LEFT JOIN tax_lines     tax ON tax.aml_id = ma.id
            LEFT JOIN base_lines    base ON base.aml_id = ma.id
            WHERE
                am.state = 'posted'
                AND aj.l10n_latam_use_documents = TRUE
                AND am.move_type IN ('out_invoice','out_refund','in_invoice','in_refund')
            GROUP BY
                am.id, rp.name, rp.vat
            """
        )
