# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Campos AFIP/ARCA sobre `res.company`.

El diseño aquí busca balance entre:
- Multi-empresa: cada compañía tiene su propio certificado y entorno.
- Simplicidad: un solo cert + environment por compañía; si en el futuro
  una compañía necesita certs distintos por servicio, se agrega un modelo
  relación en vez de reescribir esto.

Los campos que definimos acá son los que `l10n_ar_afip_ws` necesita para
saber qué cert usar y contra qué entorno hablar. La pantalla de edición
(vista XML) vive en este módulo, para que el usuario los pueda cargar
incluso antes de instalar los módulos de emisión.
"""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ar_afip_ws_environment = fields.Selection(
        selection=[
            ("testing", "Homologación (AFIP Testing)"),
            ("production", "Producción"),
        ],
        string="Entorno AFIP",
        default="testing",
        help=(
            "Determina contra qué servidores de AFIP emite esta empresa. "
            "Homologación para probar; Producción para facturar en serio. "
            "El cambio a Producción requiere un certificado distinto."
        ),
    )
    l10n_ar_afip_ws_cert_id = fields.Many2one(
        "certificate.certificate",
        string="Certificado AFIP",
        domain="[('company_id', 'in', (False, id))]",
        help=(
            "Certificado X.509 emitido por AFIP (homologación o producción, "
            "según el entorno). Subilo al módulo de Certificados antes de "
            "seleccionarlo acá."
        ),
    )
    # CUIT ya lo provee `l10n_ar` vía `partner_id.vat` — no duplicamos.
