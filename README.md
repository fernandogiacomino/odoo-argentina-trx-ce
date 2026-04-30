# odoo-argentina-trx-ce

Localización Argentina (ARCA / AFIP) para **Odoo 19 Community**.

Mismo set de módulos que [trixocom/l10n_ar_trxinvoice_ce](https://github.com/trixocom/l10n_ar_trxinvoice_ce)
pero con los addons **al primer nivel** del repo, listo para
``addons_path`` directo sin subdirectorio.

Licencia: **LGPL-3** (compatible con Odoo Community).
Autor: Trixocom.

## Instalación

```bash
# 1. Clonar como uno más en addons_path
cd /opt
git clone https://github.com/trixocom/odoo-argentina-trx-ce.git

# 2. Agregar a odoo.conf
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/opt/odoo-argentina-trx-ce,...

# 3. Update modules list y instalar
odoo -d <db> --update-modules-list --stop-after-init
odoo -d <db> -i l10n_ar_pos_edi --stop-after-init
```

## Módulos

| Módulo | Función |
|---|---|
| `l10n_ar_edi_base` | Campos base AFIP (CUIT, POS, environment, CAE) |
| `l10n_ar_afip_ws` | Cliente WSAA + WSFEv1 + WSFEX + Padrón A5/A13 (lib pura) |
| `l10n_ar_edi` | `account.move` ↔ WSFEv1/WSFEX. Botón "Validar en ARCA", QR RG 4291 |
| `l10n_ar_padron_query` | Autocomplete partner por CUIT (botón + onchange `vat`) |
| `l10n_ar_libro_iva_digital` | Libro IVA Digital RG 5616 + Subdiario IVA + IVA Simple ARCA |
| `l10n_ar_iva_simple` | 4 CSV portal ARCA "IVA Simple" |
| `l10n_ar_iibb_percepciones` | Padrón ARBA + cálculo automático percepciones IIBB |
| `l10n_ar_pos_edi` | POS + Factura Electrónica con QR + CAE en ticket |
| `l10n_ar_caea` | (placeholder) CAEA + Comprobantes Clase M |
| `l10n_ar_mis_comprobantes` | (placeholder) Import Mis Comprobantes AFIP |

## Estado actual

- Fase 1 (emisión MVP A/B/C) ✅ funcional en producción.
- Fase 2 (Servicios, Tributos, USD, Padrón, QR, UI) ✅
- Fase 3 (Reportes: Libro IVA Digital + Subdiario + IVA Simple) ✅
- Fase 4 (WSFEX exportación) ✅ funcional · WSBFE/WSMTXCA/CAEA pendientes
- Fase 5 (Padrón ARBA) ✅ · AGIP/Santa Fe/Córdoba pendientes

Validado contra AFIP **producción** con CUIT 20219464100.

## Documentación

La documentación completa, runbooks, smokes y HANDOFF están en el repo
hermano [trixocom/l10n_ar_trxinvoice_ce](https://github.com/trixocom/l10n_ar_trxinvoice_ce)
junto con `docker/`, `scripts/` y `docs/`.

Este repo (`odoo-argentina-trx-ce`) es solo el **payload de addons**
para deployments productivos donde no se quiere clonar el árbol
completo del proyecto.

## Sincronización con el repo padre

Los addons de este repo se sincronizan desde
`l10n_ar_trxinvoice_ce/addons/*`. **No editar acá** — editar en el
repo padre y resincronizar.
