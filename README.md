# odoo-argentina-trx-ce

Localización Argentina (ARCA / AFIP) para **Odoo 19 Community** —
módulos al primer nivel del repo, listos para `addons_path` directo.

Licencia: **LGPL-3** · Autor: **Trixocom**

> **Espejo de payload** del repo padre
> [`trixocom/l10n_ar_trxinvoice_ce`](https://github.com/trixocom/l10n_ar_trxinvoice_ce)
> que tiene `docs/`, `scripts/`, `docker/`, runbooks, smokes y HANDOFF
> completo. Editar siempre en el padre — este repo se sincroniza después.

## Estado

- ✅ Fase 1 — emisión MVP A/B/C en producción AFIP
- ✅ Fase 2 — Servicios, Tributos (IIBB), USD/MonCotiz, Padrón A5, QR RG 4291
- ✅ Fase 3 — Reportes: Libro IVA Digital RG 5616 + Subdiario IVA + IVA Simple
- 🟡 Fase 4 — WSFEX (Factura E exportación) ✅ · WSBFE/WSMTXCA/CAEA pendientes
- 🟡 Fase 5 — Padrón ARBA ✅ · AGIP/Santa Fe/Córdoba pendientes

Validado contra AFIP **producción** (CUIT 20219464100). Emitidos: FA-A,
FA-B, NC-A, NC-B, FA-A USD, FA-A con percepción IIBB ARBA, FA-E
exportación, FA-A desde POS.

## Módulos

### Núcleo de emisión

| Módulo | Resumen | Depende |
|---|---|---|
| `l10n_ar_edi_base` | Campos AFIP base (CUIT, POS, environment, CAE, QR). Helpers comunes. | `l10n_ar`, `certificate` |
| `l10n_ar_afip_ws` | Cliente SOAP (zeep) puro para WSAA, WSFEv1, WSFEXv1, Padrón A5/A13. Lib pura sin imports de `odoo` para testabilidad. | `l10n_ar_edi_base` |
| `l10n_ar_edi` | Pegamento `account.move` ↔ WSFEv1/WSFEX. Override de `_post()` que dispara CAE. Botón "Validar en ARCA". Tab AFIP con CAE/vto/QR/XML req-resp. PDF con QR RG 4291. Dispatcher por journal POS system (`RLI_RLM` → wsfe, `FEERCEL/FEERCELP` → wsfex). | `l10n_ar_edi_base`, `l10n_ar_afip_ws` |

### UX y autocompletado

| Módulo | Resumen | Depende |
|---|---|---|
| `l10n_ar_padron_query` | Botón "Consultar ARCA" + onchange `vat` → autocompleta razón social, condición IVA, domicilio fiscal desde el padrón A5 (`personaServiceA5/getPersona_v2`). Sanitiza CUIT con guiones automáticamente. Sobreescribe datos del partner cuando se invoca explícitamente. | `l10n_ar_edi_base`, `l10n_ar_afip_ws` |

### Reportes fiscales

| Módulo | Resumen | Depende |
|---|---|---|
| `l10n_ar_libro_iva_digital` | **Libro IVA Digital RG 5616** — wizard que genera ZIP con los 5 TXT oficiales (Latín-1 + CRLF, longitudes fijas). **Subdiario IVA** — wizard PDF (QWeb landscape A4) + XLSX (openpyxl) + vista interactiva (list / pivot / graph) sobre la vista SQL `account.ar.vat.line` (1 row pre-agregada por move). | `l10n_ar_edi`, `openpyxl` |
| `l10n_ar_iva_simple` | **4 CSV portal ARCA** (`DEBITO`, `REST_DEBITO`, `CREDITO`, `REST_CREDITO`) para régimen IVA Simple (Monotributo/PyME). Encoding latin-1 + `;` + decimales con coma. Réplica community de enterprise `l10n_ar_reports_simple`. | `l10n_ar_libro_iva_digital` |

### Padrones provinciales

| Módulo | Resumen | Depende |
|---|---|---|
| `l10n_ar_iibb_percepciones` | **Padrón ARBA** (Buenos Aires) — wizard upload TXT/ZIP con bulk_insert SQL (~100k filas en <2s). Auto-aplicación al `_onchange_partner_id`/`invoice_date`: busca alícuota en padrón vigente y aplica/quita el tax automáticamente. Tax dinámico clonado del template. Tax llega al WSFE como `Tributo Id=7`. AGIP/Santa Fe/Córdoba pendientes. | `l10n_ar_edi_base` |

### Punto de venta

| Módulo | Resumen | Depende |
|---|---|---|
| `l10n_ar_pos_edi` | **POS + Factura Electrónica argentina**. El ticket POS muestra QR RG 4291 + CAE + vto + nro de comprobante cuando la venta se factura. Suprime el bloque "¿Necesita factura?" del portal POS y el download automático del PDF post-pago en companies AR (el ticket cumple solo). Override `pos.order._prepare_invoice_vals` para vincular refunds POS con la factura original (necesario para `CbtesAsoc` en NC). RPC `pos.order.get_l10n_ar_invoice_data` que trae los datos AFIP on-demand al frontend OWL. | `point_of_sale`, `l10n_ar_edi` |

### Placeholders (próximas fases)

| Módulo | Resumen | Estado |
|---|---|---|
| `l10n_ar_caea` | CAEA (Código de Autorización Electrónico Anticipado) + comprobantes clase M. | ⚪ scaffold pendiente |
| `l10n_ar_mis_comprobantes` | Import XLS portal AFIP "Mis Comprobantes" + cotejo contra `account.ar.vat.line` (vista SQL canónica) + reporte diferencias. | ⚪ scaffold pendiente |

## Instalación

```bash
# 1. Clonar como un addons_path más
cd /opt
git clone https://github.com/trixocom/odoo-argentina-trx-ce.git

# 2. Agregar a /etc/odoo/odoo.conf
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/opt/odoo-argentina-trx-ce

# 3. Update modules list e instalar
docker exec <odoo> odoo -d <db> -i l10n_ar_pos_edi --stop-after-init
```

Las dependencias se resuelven en cascada — instalar `l10n_ar_pos_edi`
trae automáticamente `l10n_ar_edi`, `l10n_ar_edi_base`,
`l10n_ar_afip_ws`, `l10n_ar`, `certificate`, `point_of_sale` y `account`.

## Pre-condiciones del server

- **Odoo 19 Community** (no enterprise).
- Localización argentina oficial `l10n_ar` (community, ya viene con Odoo).
- Python: `zeep`, `cryptography`, `openpyxl` (vienen via pip o ya están en
  los containers de Odoo).
- Cert AFIP cargado en la company (`certificate.certificate` +
  `certificate.key`) — ver runbook de homologación en el repo padre.

## Compatibilidad

- ✅ **`odoomates/odooapps` 19.0** — auditado, conviven sin conflictos.
  Único punto de superposición (`om_account_asset.action_post`) es
  ortogonal porque cascadea via `super()`.
- ⚠️ **`way4tech_enterprise_theme`** — puede requerir parche manual SQL
  para agregar columna `homemenu_config` al `res.users.settings` si la
  versión instalada del theme no la creó por upgrade. Ver HANDOFF
  sección 4 en el repo padre.

## Documentación adicional

Toda la documentación de proyecto, runbooks de cert AFIP, deploy en
demo19/test19, smokes contra AFIP prod, HANDOFF con aprendizajes
técnicos no obvios (gotchas de WS AFIP, Odoo 19 views, etc.), y
roadmap por fases está en
[`trixocom/l10n_ar_trxinvoice_ce`](https://github.com/trixocom/l10n_ar_trxinvoice_ce/tree/main/docs).

## Contacto

- **Hector Quiroz Mendiburu** — hectorquiroz@trixocom.com
- Empresa: Trixocom
