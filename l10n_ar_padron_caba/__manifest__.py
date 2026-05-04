# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina IIBB — Padrón AGIP CABA",
    "version": "19.0.1.3.0",
    "category": "Accounting/Localizations",
    "summary": "Padrón mensual de alícuotas IIBB AGIP (CABA / Buenos Aires Ciudad)",
    "description": """
Importa el padrón mensual de alícuotas de IIBB de AGIP (CABA) y aplica
automáticamente la percepción al emitir facturas a contribuyentes
incluidos.

Funcionalidades:

* Modelo `l10n_ar.padron.agip.import` — un registro por archivo
  importado (auditoría).
* Modelo `l10n_ar.padron.agip.alicuota` — un registro por (CUIT, vigencia)
  con percepción + retención + grupo + razón social.
* Parser de archivos TXT separados por `;` (formato AGIP unificado).
  Soporta entrada `.zip` y `.txt` planos. (Para `.rar` que AGIP también
  publica, descomprimir manualmente o convertir a ZIP antes de subir.)
* Override `account.move._onchange_partner_id` que pre-arma la
  percepción si el partner está en padrón.

Layout AGIP unificado (RG 296/2019, RG 352/2022):

    DDMMAAAA;DDMMAAAA;DDMMAAAA;CUIT(11);TIPO;ALTA_BAJA;ALIC_PERC;
    ALIC_RET;GRP_PERC;GRP_RET;RAZON_SOCIAL

Periodicidad: mensual. Publicación con 5 días hábiles de anticipación.
    """,
    "author": "Trixocom",
    "website": "https://trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar_padron_base",
        "l10n_ar",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizards/padron_agip_upload_wizard_view.xml",
        "views/padron_agip_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
