# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Extensión de `account.tax` para taxes que computan su alícuota desde
el padrón ARBA.

Decisión de diseño: en lugar de mantener un `account.tax` por cada
alícuota posible (0.5%, 1%, 1.5%, ..., 4.5% → ~10 taxes), tenemos UN
tax con `l10n_ar_padron_jurisdiction='arba'`. Su `amount` se setea
dinámicamente en `account.move._onchange_partner_id` (o en un nuevo
compute de la línea) según la alícuota vigente para el partner.

Esto evita explosión combinatoria y mantiene la auditoría limpia.
"""
from odoo import fields, models


class AccountTax(models.Model):
    _inherit = "account.tax"

    l10n_ar_padron_jurisdiction = fields.Selection(
        [("arba", "ARBA (Buenos Aires)")],
        string="Padrón IIBB",
        help="Si está seteado, este tax es de tipo 'percepción/retención IIBB' "
             "y su alícuota se determina dinámicamente según el padrón "
             "indicado, consultando por CUIT del partner.",
    )
