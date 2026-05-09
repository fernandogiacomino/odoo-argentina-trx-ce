# Auditoría de módulos AR de adhoc — relevancia para `l10n_ar_trixocom`

**Fecha:** 2026-05-09 · **Branch analizada:** `19.0` en todos los repos · **Org GitHub:** [`ingadhoc`](https://github.com/ingadhoc) (verificado, dominio `adhoc.inc`)

---

## TL;DR — Hallazgo crítico

**Estábamos equivocados sobre withholding.** El motor base de retenciones AR ya **vive en Odoo 19 Community**, no es código enterprise:

1. **`l10n_ar_withholding`** es **módulo standard de Odoo 19 Community** (`odoo/addons/l10n_ar_withholding`), **LGPL-3**, contribuido por ADHOC SA. Permite registrar retenciones durante el pago de una factura. Incluye escala de Ganancias.
2. **`l10n_ar_tax`** (en `ingadhoc/odoo-argentina` 19.0, AGPL-3) se llama formalmente *"Automatic Argentinian Withholdings on Payments"*. Es el motor de **aplicación automática** sobre el pago: padrones por jurisdicción, fiscal positions, cómputo automático del % a retener.
3. **`l10n_ar_arba_ws`** (en `ingadhoc/odoo-argentina-ee` 19.0, AGPL-3) se llama formalmente *"ARBA Webservice (A122R)"*. Es exactamente el cliente del WS A122R que estábamos por escribir desde cero.

Y `odoo-argentina-ee` **no es privado** — es un repo público AGPL-3, simplemente está pensado para funcionalidades que en Odoo CE no existen y en Odoo EE sí (tipo `account_reports`).

**Implicancia para A122R / retenciones IIBB BA:**

- No tenemos que reimplementar el motor base — ya está en CE.
- No tenemos que reimplementar A122R — ya existe en `odoo-argentina-ee`, AGPL-3, instalable.
- Decisión a tomar (ver §6): instalarlos como dependencias externas vs. forkearlos a LGPL-3 vs. dejarlo como gap reconocido.

---

## 1. Repos relevantes de adhoc (rama 19.0)

De los 77 repos públicos de la org, estos son los que pegan con AR / contabilidad / retenciones:

| Repo | Branch | Módulos | Foco | Licencia |
|---|---|---|---|---|
| [`odoo-argentina`](https://github.com/ingadhoc/odoo-argentina) | 19.0 | 7 | Localización amigable AR (UX, tax, bank, purchase) | AGPL-3 |
| [`odoo-argentina-ce`](https://github.com/ingadhoc/odoo-argentina-ce) | 19.0 | 4 | Funcionalidades AR que **están en Odoo Enterprise** y adhoc reimplementa para CE | AGPL-3 |
| [`odoo-argentina-ee`](https://github.com/ingadhoc/odoo-argentina-ee) | 19.0 | 13 | Add-ons AR que **adhoc vende** y dependen de Odoo Enterprise (`accountant`, `account_reports`) | AGPL-3 |
| [`account-payment`](https://github.com/ingadhoc/account-payment) | 19.0 | 13 | Pagos avanzados, talonarios, multi-moneda, surcharge | AGPL-3 |
| [`account-financial-tools`](https://github.com/ingadhoc/account-financial-tools) | 19.0 | 8 | Reportes deuda, intereses, transferencias internas | AGPL-3 |
| [`account-invoicing`](https://github.com/ingadhoc/account-invoicing) | 19.0 | 10 | Comisiones, control facturas, line numbers | AGPL-3 |
| [`argentina-sale`](https://github.com/ingadhoc/argentina-sale) | 19.0 | 5 | Ventas + stock con sabor AR | AGPL-3 |

Notas sobre las branches:

- `odoo-argentina` 19.0 es **muy delgada** ahora — sólo 7 módulos. La mayor parte del peso histórico pasó a Odoo Community core (`l10n_ar`, `l10n_ar_edi`, `l10n_ar_withholding`).
- `odoo-argentina-ee` PÚBLICO con licencia AGPL-3 — adhoc lo mantiene abierto pero las funciones que ofrece sólo corren si tenés Odoo Enterprise instalado.
- `account-payment` 19.0 **ya no contiene** los `l10n_ar_account_withholding` históricos de la versión 13/14. La lógica migró a Odoo CE (`l10n_ar_withholding`) y al `l10n_ar_tax` que está en `odoo-argentina`.

---

## 2. Tabla maestra de módulos · `odoo-argentina` (19.0)

| Módulo | Versión | Licencia | Depende de | Propósito | Relevancia para nosotros |
|---|---|---|---|---|---|
| `l10n_ar_bank` | — | AGPL-3 | `l10n_ar` | Bancos AR — datos básicos, masters de bancos | 🟡 nice-to-have |
| `l10n_ar_purchase` | — | AGPL-3 | `purchase`, `l10n_ar` | Compras: tipo de comprobante en PO, mapping | 🟡 ya tenemos parcial |
| `l10n_ar_purchase_stock` | — | AGPL-3 | `l10n_ar_purchase`, `stock` | Compras + stock + remitos | 🟢 backlog |
| **`l10n_ar_tax`** ⭐ | 19.0.1.16.0 | AGPL-3 | `l10n_ar`, `l10n_ar_ux`, `l10n_ar_withholding`, `account_payment_pro`, `l10n_latam_check` | **"Automatic Argentinian Withholdings on Payments"** — auto-aplicación de retenciones según padrón provincial, fiscal position, y `arba_request`. Trae views: `arba_request.xml`, `res_company_jurisdiction_padron_view.xml`, `l10n_ar_payment_withholding_views.xml`. | 🔴 **clave para A122R / withholding** |
| `l10n_ar_tax_backward_compatibility` | — | AGPL-3 | `l10n_ar_tax` | Compat con instalaciones que vienen de versiones viejas | 🟡 sólo si migran de 13/14 |
| `l10n_ar_tax_python` | — | AGPL-3 | `l10n_ar_tax` | Python-eval de impuestos (cálculo dinámico %) | 🟢 backlog útil |
| `l10n_ar_ux` | 19.0.1.8.0 | AGPL-3 | `l10n_ar`, `account_internal_transfer` | UX accounting: tags, fiscal position, transfer report, debit note view | 🟢 leve overlap con nuestro `l10n_ar_edi` |

---

## 3. Tabla maestra · `odoo-argentina-ce` (19.0)

Los 4 módulos que adhoc reimplementa porque sólo existen en Odoo Enterprise:

| Módulo | Versión | Licencia | Estado | Propósito | Vs. nuestro proyecto |
|---|---|---|---|---|---|
| `l10n_ar_afipws` | 18.0.1.0.0 | AGPL-3 | ⚠️ `installable=False` | Cliente WS AFIP base usando `pyafipws` (Mariano Reingart). Certificados, conexiones, autenticación WSAA. | ❌ Nosotros tenemos `l10n_ar_afip_ws` propio (no `pyafipws`, requests directo) |
| `l10n_ar_afipws_fe` | 18.0.2.0.0 | AGPL-3 | ⚠️ `installable=False` | Factura electrónica AFIP usando `pyafipws`. WSFE/WSFEX/WSCDC. | ❌ Nosotros tenemos `l10n_ar_edi` propio (Odoo CE 19) + nuestros `l10n_ar_afip_ws` |
| `l10n_ar_pos_afipws_fe` | — | AGPL-3 | ❓ probable installable=False | POS + factura electrónica AFIP por `pyafipws` | ❌ no lo necesitamos |
| `l10n_ar_reports` | 16.0.1.0.0 | AGPL-3 | ⚠️ `installable=False` | Account VAT report XLSX (versión vieja). Manifest 16.0 sin migrar. | ❌ Nosotros tenemos `l10n_ar_libro_iva_digital` (TXT AFIP) + `l10n_ar_iva_simple` (CSV ARCA) |

**Veredicto:** `odoo-argentina-ce` 19.0 está **abandonado** — todos los módulos siguen con manifest 16.0/18.0 e `installable=False`. La cobertura que ofrecía la heredó Odoo 19 Community con `l10n_ar_edi` (factura electrónica oficial).

---

## 4. Tabla maestra · `odoo-argentina-ee` (19.0) — el que tiene A122R

Repos AGPL-3 públicos que dependen de Odoo Enterprise (`accountant`, `account_reports`):

| Módulo | Versión | Licencia | Depende de | Propósito | Vs. nuestro proyecto |
|---|---|---|---|---|---|
| `account_accountant_ux` | — | AGPL-3 | `accountant` | UX para usuarios del módulo `accountant` (Enterprise) | ❌ requiere EE |
| `account_batch_payment_ux` | — | AGPL-3 | `account_batch_payment` (EE) | Mejoras en pagos batch | ❌ requiere EE |
| `account_journal_book_report` | — | AGPL-3 | `account_reports` (EE) | Libro Diario | ❌ requiere EE |
| `accountant_internal_transfer` | — | AGPL-3 | `accountant` (EE) | Transferencias internas con UX EE | ❌ requiere EE |
| **`l10n_ar_account_reports`** | 19.0.1.17.0 | AGPL-3 | `accountant`, `account_reports` (EE), `l10n_ar`, `l10n_ar_tax`, `l10n_ar_withholding`, `l10n_latam_check`, `l10n_ar_reports`, `account_payment_pro_receiptbook` | Reportes contables AR adaptados al engine `account.report` de Enterprise: SIFERE, SICORE, SIRCAR, PBA, CABA, Mendoza, Misiones, Santa Fe, Tucumán + balance, estado de resultados, ajuste por inflación. | ⚠️ requiere EE — **pero la lógica del cómputo es interesante** y los XML de `data/*_report.xml` son referencia |
| `l10n_ar_account_reports_backward_comp` | — | AGPL-3 | `l10n_ar_account_reports` | Compat hacia atrás | ❌ |
| `l10n_ar_account_tax_settlement_mendoza` | — | AGPL-3 | `l10n_ar_account_reports` | Liquidación impositiva Mendoza | ⚪ provincial específico |
| **`l10n_ar_arba_ws`** ⭐⭐⭐ | 19.0.1.3.0 | AGPL-3 | `l10n_ar_tax`, `l10n_ar_edi` | **"ARBA Webservice (A122R)"** — el cliente que veníamos por escribir. Trae: `data/ir_cron_data.xml`, `views/l10n_ar_dj_arba_views.xml` (DDJJ ARBA), `views/account_payment_views.xml`, `views/l10n_ar_payment_withholding_views.xml`, `wizard/arba_withholding_draft_warning_views.xml`. **No requiere Enterprise** (sólo depende de `l10n_ar_tax` que es Community). | 🔴 **EXACTO match con la spec del WS A122R que documentamos** |
| `l10n_ar_currency_update` | 19.0.1.1.0 | AGPL-3 | `currency_rate_live`, `l10n_ar_edi` | Cron actualización divisas AR (BNA mayorista) | 🟢 overlap con nuestros crons de cotización |
| `l10n_ar_edi_payment_pro` | — | AGPL-3 | `l10n_ar_edi`, `account_payment_pro` | Bridge factura electrónica + pago avanzado | 🟢 backlog |
| `l10n_ar_edi_ux` | — | AGPL-3 | `l10n_ar_edi` | UX adicional sobre `l10n_ar_edi` | 🟢 evaluar overlap |
| `l10n_ar_import_bill` | 19.0.1.4.0 | AGPL-3 | `account_accountant`, `l10n_ar_edi`, `account_invoice_tax`, `account_balance_import` | **"Argentinian Importing Bills from ARCA"** — wizard import de facturas recibidas desde Mis Comprobantes ARCA. **Requiere EE** (`account_accountant`). | 🔴 overlap directo con nuestro `l10n_ar_mis_comprobantes` — el nuestro es CE-puro |
| `l10n_ar_txt_sire` | 18.0.1.0.0 | LGPL-3 | `l10n_ar_account_reports`, `l10n_ar_tax` | Export TXT Régimen SIRE (Sistema Integral de Retenciones Electrónicas) | 🟢 candidato fork — único con LGPL-3 en este repo |

---

## 5. Tabla maestra · `account-payment` (19.0)

Sin módulos de withholding directos en 19.0 — toda esa lógica migró. Pero sí hay infraestructura de pago avanzada:

| Módulo | Versión | Licencia | Depende de | Propósito | Relevancia |
|---|---|---|---|---|---|
| `account_cashbox` | — | AGPL-3 | `account` | Caja: arqueo, movimientos | 🟢 backlog |
| `account_cashbox_bundle` | — | AGPL-3 | `account_cashbox` | Bundle caja | 🟢 backlog |
| `account_cashbox_l10n_latam_check` | — | AGPL-3 | `account_cashbox`, `l10n_latam_check` | Caja con cheques LATAM | 🟢 backlog |
| `account_payment_financial_surcharge` | — | AGPL-3 | `account_payment` | Recargo financiero en pago | 🟢 backlog |
| `account_payment_loan` | — | AGPL-3 | `account_payment` | Pagos como préstamos | ⚪ no aplica AR |
| `account_payment_multi` | — | AGPL-3 | `account_payment` | Multi-pago (un pago contra muchas facturas) | 🟢 muy útil |
| **`account_payment_pro`** ⭐ | 19.0.2.6.0 | AGPL-3 | `account`, `l10n_latam_invoice_document`, `account_internal_transfer`, `l10n_latam_check`, `account_ux` | "Account Payment Super Power" — el motor de pagos avanzados sobre el que se monta `l10n_ar_tax` para retener. Wizard `account_payment_invoice_wizard`. | 🔴 **dependencia de `l10n_ar_tax`** |
| `account_payment_pro_receiptbook` | — | AGPL-3 | `account_payment_pro` | Talonarios de recibo (OP-X 0001-00000001) | 🟢 dependencia de reportes AR |
| `account_payment_ux` | — | AGPL-3 | `account_payment` | UX general en pagos | 🟢 nice-to-have |
| `card_installment` | — | AGPL-3 | `account_payment` | Cuotas de tarjeta | 🟡 evaluar |
| **`l10n_ar_payment_bundle`** | 19.0.1.9.0 | AGPL-3 | `account_payment_pro`, `l10n_ar_tax`, `account_payment_pro_receiptbook` | Bundle integración payment AR — junta `account_payment_pro` + retenciones + receiptbook | 🟢 instalación todo-en-uno |
| `l10n_latam_check_ux` | — | AGPL-3 | `l10n_latam_check` | UX para cheques LATAM | 🟢 backlog |
| `payment_retry` | — | AGPL-3 | `payment` | Retry automático pagos | ⚪ no aplica |

---

## 6. Tabla maestra · `account-financial-tools` (19.0)

| Módulo | Licencia | Propósito | Relevancia |
|---|---|---|---|
| `account_debt_report` | AGPL-3 | Reporte de deuda por partner | 🟢 backlog útil |
| `account_exchange_difference_invoice` | AGPL-3 | Diferencia de cambio sobre factura | 🟢 muy útil para USD |
| `account_financial_amount` | AGPL-3 | Importes financieros adicionales | 🟡 |
| `account_interests` | AGPL-3 | Intereses sobre vencidos | 🟢 backlog |
| `account_internal_transfer` | AGPL-3 | Transferencias internas (dependencia de muchos otros) | 🔴 dep común |
| `account_journal_security` | AGPL-3 | Seguridad por diario contable | 🟡 |
| `account_payment_term_surcharge` | AGPL-3 | Recargo por término de pago | 🟢 |
| `account_ux` | AGPL-3 | UX general accounting | 🟢 dep común |

---

## 7. Tabla maestra · `argentina-sale` (19.0)

| Módulo | Licencia | Propósito | Relevancia |
|---|---|---|---|
| `l10n_ar_sale` | AGPL-3 | Ventas adaptadas AR | 🟢 backlog |
| `l10n_ar_sale_order_type` | AGPL-3 | Tipos de SO con sabor AR | 🟢 |
| `l10n_ar_stock_delivery` | AGPL-3 | Remitos AR | 🟢 backlog importante |
| `l10n_ar_stock_picking_batch` | AGPL-3 | Picking batch AR | 🟡 |
| `l10n_ar_stock_ux` | AGPL-3 | UX stock AR | 🟡 |

---

## 8. Tabla maestra · `account-invoicing` (19.0)

| Módulo | Licencia | Propósito | Relevancia |
|---|---|---|---|
| `account_background_post` | AGPL-3 | Post asíncrono de facturas (job_queue) | 🟢 muy útil para batches |
| `account_invoice_commission` | AGPL-3 | Comisiones sobre facturas | ⚪ |
| `account_invoice_control` | AGPL-3 | Control / aprobación facturas | 🟡 |
| `account_invoice_line_number` | AGPL-3 | Numeración de líneas en factura | 🟡 |
| `account_invoice_move_currency` | AGPL-3 | Moneda independiente del move | 🟢 backlog USD |
| `account_invoice_partial` | AGPL-3 | Facturación parcial | 🟢 |
| `account_invoice_prices_update` | AGPL-3 | Update masivo de precios facturados | 🟡 |
| `account_invoice_tax` | AGPL-3 | Tax extra en factura | 🟢 dep de `l10n_ar_import_bill` |
| `l10n_latam_invoice_document_ux` | AGPL-3 | UX comprobantes LATAM | 🟢 |
| `website_sale_account_invoice_commission` | AGPL-3 | Comisiones eCommerce | ⚪ |

---

## 9. Mapa de dependencias del stack adhoc para retenciones

```
                  ┌────────────────────────────────────────────┐
                  │  Odoo 19 Community (LGPL-3, oficial)       │
                  │  · l10n_ar              (locale base AR)   │
                  │  · l10n_ar_edi          (factura electr.)  │
                  │  · l10n_ar_withholding  (motor retenciones)│ ← AQUÍ ESTÁ LA BASE
                  │  · l10n_latam_check                        │
                  │  · l10n_latam_invoice_document             │
                  └─────┬────────────────────────────────┬─────┘
                        │                                │
        ┌───────────────▼────────────────┐ ┌─────────────▼────────┐
        │ ingadhoc/account-payment 19.0  │ │ ingadhoc/odoo-argentina │
        │ (AGPL-3)                       │ │ 19.0 (AGPL-3)        │
        │ · account_payment_pro          │ │ · l10n_ar_ux         │
        │ · account_payment_pro_         │ │ · l10n_ar_tax  ────┐ │
        │   receiptbook                  │ │   (auto-apply WH)  │ │
        └───────────────┬────────────────┘ └────────────────────┼─┘
                        │                                       │
                        │   ┌───────────────────────────────────┤
                        │   │
        ┌───────────────▼───▼────────────────────────────────┐
        │ ingadhoc/odoo-argentina-ee 19.0 (AGPL-3, público)  │
        │ · l10n_ar_arba_ws ← WS A122R retenciones IIBB BA   │
        │ · l10n_ar_account_reports (requiere EE)            │
        │ · l10n_ar_import_bill (requiere EE)                │
        │ · l10n_ar_currency_update                          │
        │ · l10n_ar_edi_ux                                   │
        └────────────────────────────────────────────────────┘
```

---

## 10. Solapamiento con `l10n_ar_trixocom`

| Funcionalidad | Lo cubre adhoc con… | Lo cubre `l10n_ar_trixocom` con… | ¿Conflicto? |
|---|---|---|---|
| Factura electrónica (WSFEv1/WSFEX/WSCDC) | `l10n_ar_edi` (Odoo CE oficial) + `l10n_ar_afipws_fe` (deprecado) | `l10n_ar_afip_ws` propio (cliente requests + WSAA propio) | 🟡 doble engine — hay que elegir cuál usa el cliente |
| CAEA | nada en adhoc 19.0 | `l10n_ar_caea` propio | ✅ exclusivo nuestro |
| Padrones IIBB (ARBA, AGIP, SF, CBA) — **percepciones** | `l10n_ar_tax` con `res_company_jurisdiction_padron` | `l10n_ar_iibb_percepciones` + 4 módulos provinciales + `l10n_ar_padron_base` | 🔴 doble engine de padrones (potencialmente conflictivo) |
| Retenciones IIBB ARBA (A122R) | **`l10n_ar_arba_ws`** | ⚪ no implementado (gap reconocido) | ✅ adhoc lo cubre |
| Padrón A13 (CUIT autocomplete) | `l10n_ar_afipws.res_partner_update_from_padron_wizard` | `l10n_ar_padron_query` propio | 🟡 doble |
| Mis Comprobantes (XLS) | `l10n_ar_import_bill` (requiere EE) | `l10n_ar_mis_comprobantes` propio (CE puro) | ✅ nosotros somos CE-puro, adhoc requiere EE |
| Libro IVA Digital (TXT) | nada en adhoc 19.0 explícito (pueden usar `account_reports` EE) | `l10n_ar_libro_iva_digital` propio | ✅ exclusivo nuestro |
| IVA Simple (CSV ARCA RG 5616) | nada en adhoc | `l10n_ar_iva_simple` propio | ✅ exclusivo nuestro |
| SIRE (TXT régimen federal) | `l10n_ar_txt_sire` (LGPL-3, manifest 18.0) | nada | ⚪ candidato fork |
| Cotización divisas | `l10n_ar_currency_update` | `cron_afip_cotizacion` + `cron_bna` propios | 🟡 doble |
| Reportes contables AR (SIFERE, SICORE, etc.) | `l10n_ar_account_reports` (requiere EE) | nada | ⚪ requiere EE en adhoc |

---

## 11. Veredicto sobre A122R y withholding

### Opción A — Instalar el stack adhoc tal cual (recomendado para clientes)

```
- l10n_ar_withholding          (Odoo 19 CE — ya viene)
- account_payment_pro          (adhoc/account-payment, AGPL-3)
- account_payment_pro_receiptbook (adhoc/account-payment, AGPL-3)
- l10n_ar_ux                   (adhoc/odoo-argentina, AGPL-3)
- l10n_ar_tax                  (adhoc/odoo-argentina, AGPL-3) — auto-apply
- l10n_ar_arba_ws              (adhoc/odoo-argentina-ee, AGPL-3) — A122R
```

**Pros:** funciona ya, sin reescribir nada, mantenido activamente por adhoc.

**Contras:**
1. **Licencia AGPL-3** — más viral que LGPL-3. Si el cliente integra Odoo en un SaaS que expone interfaz de red, debe publicar todo el código de su instalación.
2. **Requiere `account_payment_pro`** que reemplaza el flujo de pago standard — los flujos UX cambian.
3. **Solapamiento con `l10n_ar_iibb_percepciones`** — `l10n_ar_tax` también gestiona padrones; habría que elegir y deshabilitar uno.

### Opción B — Forkear `l10n_ar_arba_ws` a LGPL-3 dentro de `l10n_ar_trixocom`

AGPL-3 permite leer y reimplementar bajo LGPL-3 (no es copia literal). Reescribir el cliente del WS A122R desde cero usando como referencia el código de adhoc:

- `lib/arba_a122r.py` — cliente REST con auth Keycloak/OAuth2 (~300-500 LOC).
- Models: `l10n_ar.dj.arba` (DDJJ), `l10n_ar.payment.withholding`.
- Cron de submission diaria.
- Wizard de borrador.

**Pros:** licencia LGPL-3 consistente, sin AGPL viral, integrable con nuestro `l10n_ar_padron_base`.

**Contras:** esfuerzo ~2-3 semanas + requiere haber resuelto antes el motor de retenciones sobre `account.payment` (que sí tenemos disponible en CE vía `l10n_ar_withholding`).

### Opción C — Híbrido (pragmático)

1. Para clientes que NO les molesta AGPL-3: documentar el stack adhoc como vía recomendada.
2. Mantener nuestro `l10n_ar_iibb_percepciones` para las **percepciones** (porque ahí sí cubrimos algo que adhoc no hace tan limpio: padrón TXT puro, sin `account_payment_pro`).
3. Implementar nosotros el cliente A122R LGPL-3 (Opción B) sólo si aparece demanda explícita.

**Recomendación:** Opción C. Documentar las dos vías en `docs/integracion_adhoc.md`, dejar A122R en backlog hasta que un cliente lo pida concretamente, y meter sólo `l10n_ar_account_reports` como referencia para futuro engine de reportes (la lógica de los `data/*_report.xml` es oro: están las definiciones de SIFERE, SICORE, etc.).

---

## 12. Trampa importante de naming — actualización al `HANDOFF.md`

Lo que está en el `HANDOFF.md` línea 219 (*"WS A122R REST/JSON contra portal ARBA con Keycloak — adhoc tiene `l10n_ar_arba_ws` para esto pero depende de `l10n_ar_tax` que no existe en community"*) es **incorrecto** a partir de Odoo 19:

- `l10n_ar_tax` **sí existe** en `ingadhoc/odoo-argentina` 19.0 (AGPL-3, público).
- `l10n_ar_withholding` **sí existe** en Odoo 19 Community oficial (LGPL-3, contribuido por adhoc).
- `l10n_ar_arba_ws` es público AGPL-3 en `odoo-argentina-ee`, no propietario.

El obstáculo real **no es la disponibilidad** del código sino **la licencia AGPL-3** y el solapamiento con nuestros propios módulos de padrones. Cualquier futuro `HANDOFF.md` debe corregir esto.

---

## 13. Tarea sugerida si seguimos por el camino A122R

Si en algún momento se decide implementar A122R (Opción B), el orden de tareas sería:

1. Smoke contra el endpoint de homologación de ARBA (`https://dfe.arba.gov.ar/.../A122R`) con un token de prueba — verificar payload JSON y formato de respuestas.
2. Definir `l10n_ar.payment.withholding.iibb` model (line per retención generada).
3. Cliente REST puro `lib/arba_a122r.py` — auth, submit, query, retract.
4. Hook en `account.payment._post()` que genere la línea de retención desde `l10n_ar_withholding` y la envíe.
5. Cron diario de submission.
6. Vista DDJJ ARBA (mensual) consolidando lo enviado.
7. Tests con fixtures de payload + respuestas mock.

Estimación: **15-20 días de desarrollo + 5 días de homologación con ARBA**.

---

## Apéndice — comandos para reproducir esta auditoría

```bash
# Listar todos los repos de la org
curl -s "https://api.github.com/orgs/ingadhoc/repos?per_page=100" \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); [print(x["name"],"|",x["default_branch"]) for x in r]'

# Listar módulos de un repo en branch específica
curl -s "https://api.github.com/repos/ingadhoc/odoo-argentina/contents?ref=19.0" \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); [print(x["name"]) for x in r if x["type"]=="dir"]'

# Leer un manifest puntual
curl -s "https://raw.githubusercontent.com/ingadhoc/odoo-argentina/19.0/l10n_ar_tax/__manifest__.py"
```

---

**Generado:** 2026-05-09 · **Branch base:** `19.0` · **Tasks:** #48-#51
