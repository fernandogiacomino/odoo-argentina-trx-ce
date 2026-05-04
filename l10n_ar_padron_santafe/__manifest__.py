# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina IIBB — Padrón API Santa Fe (PARP)",
    "version": "19.0.1.3.0",
    "category": "Accounting/Localizations",
    "summary": "Padrón Web Contribuyentes API Santa Fe (PARP) — RG API 14/2025",
    "description": """
Importa el padrón mensual de alícuotas de IIBB de la Administración
Provincial de Impuestos (API) de Santa Fe — PARP — y aplica la
percepción automáticamente al emitir facturas.

Funcionalidades:

* Modelos: `l10n_ar.padron.santafe.import` (batch) +
  `l10n_ar.padron.santafe.alicuota` (CUIT, vigencia, alic perc/ret,
  grupo, marca alícuota).
* Parser TXT separado por `;` o ZIP. Encoding Latin-1 (ISO-8859-1).
* Override `account.move._onchange_partner_id` para auto-aplicar
  percepción si el partner está en padrón.

Layout PARP (RG API 14/2025, Anexo I):

    DDMMAAAA;DDMMAAAA;DDMMAAAA;CUIT(11);TIPO(C/D);ALTA_BAJA(S/B);
    MARCA_ALIC(S/N);ALIC_PERC;ALIC_RET;GRUPO_PERC;GRUPO_RET

Tipo: C=Local · D=Convenio Multilateral. 23 grupos (0% a 6%).
Periodicidad mensual.
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
        "wizards/padron_santafe_upload_wizard_view.xml",
        "views/padron_santafe_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
