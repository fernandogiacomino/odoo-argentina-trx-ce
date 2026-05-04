# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina IIBB — Padrón Rentas Córdoba (LUA)",
    "version": "19.0.1.3.0",
    "category": "Accounting/Localizations",
    "summary": "Listado Único de Alícuotas DGR Córdoba (LUA Percepción + LUA Retención)",
    "description": """
Importa el LUA (Listado Único de Alícuotas) de la DGR de Córdoba y aplica
la percepción automáticamente al emitir facturas.

Córdoba publica DOS listados separados:
  * LUA Percepción (alícuotas a aplicar al cliente cuando se emite factura)
  * LUA Retención (alícuotas a aplicar al pagar a un proveedor)

Funcionalidades:

* Modelos: `l10n_ar.padron.cordoba.import` (batch) +
  `l10n_ar.padron.cordoba.alicuota` (CUIT, vigencia, alic perc/ret, grupo).
* Parser flexible TXT con separador `;` o longitud fija. Encoding
  Latin-1.
* Override `account.move._onchange_partner_id` para auto-aplicar
  percepción si el partner está en LUA Percepción.

Periodicidad: publicado el día 22 de cada mes, aplica al mes siguiente.
Marco normativo: Resolución Normativa DGR 1/2023.

NOTA OPERATIVA: el archivo crudo de DGR puede requerir pre-procesamiento
por el operador para obtener el formato `;` separado que espera el
parser. Si DGR cambia el formato, ajustar `lib/padron_cordoba.py`.
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
        "wizards/padron_cordoba_upload_wizard_view.xml",
        "views/padron_cordoba_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
