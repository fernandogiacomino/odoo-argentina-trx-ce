# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""AbstractModel del reporte QWeb del Subdiario IVA.

Odoo dispatchea el reporte buscando un modelo cuyo ``_name`` matchea
``report.<modulo>.<template_id>``. Este modelo expone
``_get_report_values(docids, data)`` que QWeb va a recibir como contexto.
"""
from odoo import api, fields, models


class SubdiarioIvaReport(models.AbstractModel):
    _name = "report.l10n_ar_libro_iva_digital.report_subdiario_iva"
    _description = "Subdiario IVA Compras/Ventas — datos para QWeb"

    @api.model
    def _get_report_values(self, docids, data=None):
        """`docids` es la lista de IDs del wizard que disparó el reporte.

        Devolvemos un dict que QWeb usa como contexto. La lógica pesada
        (build_row, totals) la delega al wizard para no duplicar.
        """
        Wiz = self.env["l10n_ar.subdiario.iva.wizard"]
        if docids:
            wiz = Wiz.browse(docids[:1])
        elif data:
            # Caso: reportes disparados por data dict, sin record persistido.
            wiz = Wiz.create({
                "company_id": data.get("company_id"),
                "date_from": data.get("date_from"),
                "date_to": data.get("date_to"),
                "include_sales": data.get("include_sales", True),
                "include_purchases": data.get("include_purchases", True),
            })
        else:
            wiz = Wiz.browse()

        report_data = wiz.get_report_data() if wiz else {}
        return {
            "doc_ids": docids or [],
            "doc_model": Wiz._name,
            "docs": wiz,
            "data": data or {},
            "report": report_data,
        }
