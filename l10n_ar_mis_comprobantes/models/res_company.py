# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Configuración por empresa para el cotejo Mis Comprobantes."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ar_mc_default_product_id = fields.Many2one(
        "product.product",
        string="Producto genérico Mis Comprobantes",
        domain="[('purchase_ok', '=', True)]",
        help=(
            "Producto que se usa al auto-crear facturas de proveedor desde "
            "un batch de Mis Comprobantes. Tiene que tener `purchase_ok=True` "
            "y un impuesto de compra (IVA) en `supplier_taxes_id` — el "
            "wizard reemplaza el tax si el % no coincide con el de la línea "
            "del XLS."
        ),
    )
    l10n_ar_mc_default_purchase_journal_id = fields.Many2one(
        "account.journal",
        string="Diario compras Mis Comprobantes",
        domain="[('type', '=', 'purchase'), ('company_id', '=', id)]",
        help=(
            "Diario donde se crean las facturas IN auto-importadas. Si está "
            "vacío, el wizard usa el primer journal `type=purchase` de la "
            "empresa."
        ),
    )
