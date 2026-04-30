# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
{
    "name": "Argentina EDI — Consulta Padrón AFIP",
    "version": "19.0.0.1.0",
    "category": "Accounting/Localizations/EDI",
    "summary": "Autocompleta partner desde el WS Padrón AFIP (constancia de inscripción)",
    "description": """
Integra el WS Padrón AFIP (`ws_sr_constancia_inscripcion`) con
`res.partner`:

* Botón **Consultar AFIP** en el formulario del partner. Tira de
  `getPersona` y completa razón social, responsabilidad IVA, tipo de
  identificación y domicilio fiscal.
* `onchange` sobre `vat`: cuando el usuario sale del campo VAT y el
  valor parece un CUIT (11 dígitos con checksum válido), dispara la
  misma consulta automáticamente. Pensado para cuando vendedores cargan
  un cliente nuevo y quieren cero fricción.

Requisitos:

* La empresa que consulta debe tener un certificado AFIP delegado para
  el servicio `ws_sr_constancia_inscripcion` (además del WSFE).
* El módulo `l10n_ar_afip_ws` provee el cliente SOAP y el cache de TA.
    """,
    "author": "Trixocom",
    "website": "https://trixocom.com",
    "license": "LGPL-3",
    "depends": [
        "l10n_ar_afip_ws",
        "l10n_ar",
    ],
    "data": [
        "views/res_partner_view.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
