# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina EDI — CAEA",
    "version": "19.0.1.2.0",
    "category": "Accounting/Localizations/EDI",
    "summary": "CAEA — Código de Autorización Electrónico Anticipado (régimen de contingencia)",
    "description": """
Soporte CAEA (RG 2926) para emisión electrónica argentina en Odoo 19
Community. Régimen de contingencia: el contribuyente solicita un código
por anticipado para una quincena, y lo usa cuando WSFEv1 está caído /
hay problemas de red.

Funcionalidades:

* Modelo `l10n_ar.caea` con un registro por (company, periodo, orden).
* Botón "Solicitar CAEA" en Configuración → Localización Argentina.
* Cron diario que marca CAEA vencidos.
* Cron diario que rinde a AFIP los comprobantes emitidos con CAEA
  pendientes (`FECAEARegInformativo`).
* Override `_l10n_ar_request_cae_wsfe` con fallback CAEA cuando WSFEv1
  da `TransportError`.

Periodos:
  * Q1 (orden=1): 1 al 15 del mes.
  * Q2 (orden=2): 16 al fin del mes.

Plazos AFIP:
  * Solicitud: hasta 5 días previos al inicio de la quincena.
  * Rendición: hasta 8 días corridos después del cierre.
    """,
    "author": "Trixocom",
    "website": "https://trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar_edi",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/l10n_ar_caea_views.xml",
        "views/l10n_ar_caea_log_views.xml",
        "views/res_config_settings_view.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
