# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Jerga contable AR: etiqueta de campo (modelo, campo) -> término AR para es_419.
# Las columnas del Libro Diario/Mayor en Argentina son Debe / Haber / Saldo
# (no Débito / Crédito / Balance, que es el genérico es_419 de Odoo).
_AR_FIELD_LABELS = {
    ("account.move.line", "debit"): "Debe",
    ("account.move.line", "credit"): "Haber",
    ("account.move.line", "balance"): "Saldo",
    ("account.analytic.account", "debit"): "Debe",
    ("account.analytic.account", "credit"): "Haber",
}
_AR_LANG = "es_419"


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    @api.model
    def _l10n_ar_apply_accounting_terms(self):
        """Aplica la jerga contable argentina (Debe/Haber/Saldo + Movimientos
        contables) sobre el idioma activo es_419.

        Por qué así y no solo con el .po:
          * Odoo 19 Community no trae es_AR para `account`; la instancia corre en
            es_419, que rotula las columnas del mayor como Débito/Crédito/Balance.
          * "Debit"/"Credit" son msgid mixtos code+modelo en `account`. Durante un
            `-u`, el paso de reflexión de campos ("verifying fields for every
            extended model") re-deriva field_description de account.move.line
            traduciendo el string fuente vía el catálogo de código, revirtiendo
            cualquier override que hayamos hecho durante la carga de datos. Por eso
            el `<function>` de instalación no alcanza para esos dos campos.
          * En cambio, escribir field_description por ORM en el server ya levantado
            (post-carga) SÍ persiste. De ahí que esto se dispare además vía ir.cron
            (numbercall=1, nextcall en el pasado) que corre una vez apenas termina
            el update/restart. Es idempotente.

        Cubre dos caminos:
          1. Recarga i18n/es_419.po con overwrite=True (nombres de menú/acción
             "Journal Items" -> "Movimientos contables" y cuentas analíticas).
          2. Escritura directa por ORM de las etiquetas de los campos del mayor.
        """
        Field = self.env["ir.model.fields"].sudo()
        # Early-return idempotente: si la etiqueta clave ya está en AR, no hay nada
        # que hacer (evita trabajo en cada corrida diaria del cron).
        debit = Field._get("account.move.line", "debit")
        if debit and debit.with_context(lang=_AR_LANG).field_description == "Debe":
            return True
        self._load_module_terms(["l10n_ar_edi_base"], [_AR_LANG], overwrite=True)
        changed = []
        for (model_name, field_name), value in _AR_FIELD_LABELS.items():
            fld = Field._get(model_name, field_name)
            if not fld:
                continue
            current = fld.with_context(lang=_AR_LANG).field_description
            if current != value:
                fld.with_context(lang=_AR_LANG).field_description = value
                changed.append("%s.%s" % (model_name, field_name))
        if changed:
            _logger.info(
                "l10n_ar_edi_base: jerga contable AR aplicada (es_419) en %s",
                ", ".join(changed),
            )
        return True
