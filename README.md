# l10n-ar-edi-community

Paquete de módulos para **Odoo 19 Community** que implementa la facturación
electrónica argentina (ARCA / AFIP) sin depender de Odoo Enterprise.

Licencia: LGPL-3 (compatible con Odoo Community).
Autor: Trixocom.
Estado: en desarrollo — Fase 2 funcional en producción AFIP. Emitidas
FA-A, FA-B, NC-A, NC-B, FA-A USD y FA-A con percepción IIBB contra el
WSFEv1 de AFIP prod desde Odoo 19 Community. Padrón A13 funcional
(autocomplete partner por CUIT). PDF con QR AFIP RG 4291. UI con
botón "Enviar a ARCA" + tab AFIP en account.move.

## Alcance

Cubrir los casos que en Enterprise resuelven `l10n_ar_edi`, `l10n_ar_reports` y
`l10n_ar_reports_simple`, trabajando únicamente sobre la localización community
oficial `l10n_ar` + el framework `certificate` del core Community 19.

**Condiciones IVA soportadas**: Responsable Inscripto, Monotributo, Exento /
No alcanzado. Multi-empresa simultáneo.

## Módulos

| Módulo | Responsabilidad | Fase |
|---|---|---|
| `l10n_ar_edi_base` | Campos base (entorno ARCA, CUIT, POS), helpers de validación, extensiones a `res.company` / `account.journal` / `account.move`. | 1 |
| `l10n_ar_afip_ws` | Cliente Python puro de WSAA + WSFEv1 (y futuros WSFEX, WSBFE, WSCDC). Aislado de Odoo para testeo unitario. | 1 |
| `l10n_ar_edi` | Integración entre `account.move` y el cliente WS. Botones, estados de autorización, impresión con CAE + QR AFIP. | 1 |
| `l10n_ar_padron_query` | Consulta WS Padrón AFIP A13 — botón + onchange `vat` para autocompletar partner por CUIT. | 2 |
| `l10n_ar_libro_iva_digital` | Libro IVA Digital (RG 5616) con export de los 5 TXT oficiales. | 2 |
| `l10n_ar_citi` | CITI legacy (Ventas/Compras). | 2 |
| `l10n_ar_mis_comprobantes` | Import y cotejo contra el portal Mis Comprobantes de AFIP. | 2 |
| `l10n_ar_iibb_percepciones` | Percepciones y retenciones IIBB provinciales (ARBA, AGIP, Santa Fe, Córdoba). | 3 |
| `l10n_ar_caea` | CAEA (Código de Autorización Electrónico Anticipado) y comprobantes clase M. | 4 |

## Dependencias externas

- Python: `zeep` (para SOAP de AFIP).
- Módulos Odoo: `l10n_ar`, `certificate` (ambos community oficial).
- OPCIONAL para Fase 2 UX: [OCA account-financial-reporting 19.0](https://github.com/OCA/account-financial-reporting/tree/19.0).
  Solo lo usa `l10n_ar_libro_iva_digital` para vistas interactivas. El export
  TXT es independiente y funciona sin OCA.

## Cómo desarrollar

```bash
# Levantar stack de desarrollo (Odoo 19 community + PostgreSQL)
cd docker
cp odoo.conf.sample odoo.conf
docker compose -f docker-compose.dev.yml up -d

# Instalar módulos en la base de datos de pruebas
docker compose -f docker-compose.dev.yml exec odoo \
    odoo -d dev --init l10n_ar_edi_base,l10n_ar_afip_ws,l10n_ar_edi --stop-after-init
```

## Documentación

> **Para devs (humanos o LLMs) que recién entran al proyecto**:
> empezá por [`docs/HANDOFF.md`](docs/HANDOFF.md). Tiene el estado completo,
> aprendizajes técnicos no obvios y roadmap. Si vas a usar Claude/Cowork,
> el archivo [`CLAUDE.md`](CLAUDE.md) en la raíz del repo se carga
> automáticamente.

- [HANDOFF.md](docs/HANDOFF.md) — **transferencia completa del proyecto**
- [Fases del proyecto](docs/fases.md) (estado actualizado por fase)
- [Arquitectura de módulos](docs/arquitectura.md)
- [Mapa Enterprise → Community](docs/mapa_cobertura.md)
- [Runbook certificado homologación WSAA](docs/runbook_certificado_homologacion.md)
- [Runbook deploy a demo19](docs/runbook_deploy_demo19.md)

## Testing contra AFIP

Todos los tests de integración contra AFIP se ejecutan contra el entorno de
homologación (`wsaahomo.afip.gov.ar`, `wswhomo.afip.gov.ar`). El entorno de
producción se usa solo desde una base productiva con el certificado de
producción del cliente, y nunca desde CI.

## Contribuciones

Este repositorio es privado. Los pull requests se revisan internamente Trixocom.
