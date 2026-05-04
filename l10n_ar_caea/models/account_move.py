# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Extensiones a `account.move` para soporte CAEA.

* `l10n_ar_caea_id`: link al `l10n_ar.caea` que se usó al emitir.
* `l10n_ar_caea_rendido`: True si el comprobante ya fue informado a AFIP
  vía `FECAEARegInformativo`.
* Override de `_l10n_ar_request_cae_wsfe` con fallback CAEA — si WSFEv1
  da timeout o `TransportError`, usa el CAEA vigente.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.l10n_ar_afip_ws.lib import errors as ws_errors
from odoo.addons.l10n_ar_afip_ws.lib import transport as ws_transport
from odoo.addons.l10n_ar_afip_ws.lib import wsfe_caea as ws_caea

_logger = logging.getLogger(__name__)


def _safe(b):
    """bytes → str (utf-8 safe). None si vacío."""
    if not b:
        return None
    if isinstance(b, bytes):
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:
            return b.decode("latin-1", errors="replace")
    return str(b)


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ar_caea_id = fields.Many2one(
        "l10n_ar.caea",
        string="CAEA usado",
        copy=False,
        readonly=True,
        index=True,
    )
    l10n_ar_caea_rendido = fields.Boolean(
        string="CAEA rendido",
        copy=False,
        readonly=True,
        help="True si el comprobante ya fue informado a AFIP vía "
             "FECAEARegInformativo. Los moves con CAEA pendientes de "
             "rendir se procesan por cron diario antes de la fecha tope.",
    )
    l10n_ar_caea_rendido_date = fields.Datetime(
        string="Fecha rendición CAEA",
        copy=False,
        readonly=True,
    )

    def _l10n_ar_request_cae_wsfe(self):
        """Override con fallback a CAEA si WSFE no responde."""
        self.ensure_one()
        try:
            return super()._l10n_ar_request_cae_wsfe()
        except ws_errors.TransportError as e:
            # Solo intentamos fallback si la company habilita CAEA.
            if not self.company_id.l10n_ar_caea_enabled:
                raise
            _logger.warning(
                "WSFEv1 transport error en %s — intentando fallback CAEA: %s",
                self.name, e,
            )
            caea = self.env["l10n_ar.caea"].find_active(
                self.company_id,
                target_date=self.invoice_date or fields.Date.context_today(self),
            )
            if not caea:
                raise UserError(_(
                    "WSFEv1 no respondió y no hay CAEA vigente para %s. "
                    "Solicitá un CAEA desde Configuración → Localización "
                    "Argentina → 'Solicitar CAEA' antes del próximo período."
                ) % self.company_id.name) from e
            self.env["l10n_ar.caea.log"]._record_event(
                self.env, self.company_id, "solicitar", success=True,
                caea=caea,
                message="Fallback CAEA aplicado a %s tras error WSFE: %s" % (self.name, e),
                triggered_by="post_fallback",
            )
            self._l10n_ar_apply_caea(caea)

    def _l10n_ar_apply_caea(self, caea):
        """Asigna el CAEA al move como auth_code, sin pegarle a AFIP.

        Genera el doc_number con la próxima secuencia local (Odoo se
        encarga de eso al postear normalmente). El comprobante queda
        emitido off-line; se rinde después con el cron.
        """
        self.ensure_one()
        self.write({
            "l10n_ar_afip_auth_mode": "CAEA",
            "l10n_ar_afip_auth_code": caea.code,
            "l10n_ar_afip_auth_code_due": caea.fch_vig_hasta,
            "l10n_ar_afip_result": "A",  # asumido — se confirma al rendir
            "l10n_ar_caea_id": caea.id,
            "l10n_ar_caea_rendido": False,
            "l10n_ar_afip_observations": _(
                "Comprobante emitido en modo CAEA por contingencia. "
                "Pendiente de rendición a AFIP (FECAEARegInformativo)."
            ),
        })
        self.message_post(body=_(
            "📦 Emitido con CAEA <b>%s</b> (modo contingencia). "
            "Pendiente de rendición."
        ) % caea.code)
        _logger.info(
            "Move %s emitido con CAEA %s — pendiente rendición.",
            self.name, caea.code,
        )

    # ------------------------------------------------------------------
    # Rendición informativa
    # ------------------------------------------------------------------
    @api.model
    def _cron_caea_rendir(self):
        """Cron diario: rinde a AFIP los CAEA — comprobantes emitidos
        con `FECAEARegInformativo` y CAEA sin uso con
        `FECAEASinMovimientoInformar`.

        Sólo corre para companies con `l10n_ar_caea_enabled=True`.
        """
        Company = self.env["res.company"].sudo()
        active_companies = Company.search([("l10n_ar_caea_enabled", "=", True)])
        if not active_companies:
            return True

        # Por cada company habilitada, procesar CAEAs cuyo cierre haya
        # pasado (fch_vig_hasta < hoy) y aún estén en estado active.
        today = fields.Date.context_today(self)
        Caea = self.env["l10n_ar.caea"]
        for company in active_companies:
            caeas_a_rendir = Caea.search([
                ("company_id", "=", company.id),
                ("state", "=", "active"),
                ("fch_vig_hasta", "<", today),
            ])
            for caea in caeas_a_rendir:
                try:
                    self._l10n_ar_caea_rendir_caea(caea)
                except Exception as e:
                    _logger.exception(
                        "Cron CAEA rendir — error caea=%s: %s", caea.code, e,
                    )

            # También rendimos comprobantes con CAEA aún vigente si están
            # cerca del tope informativo (próximos 3 días) — para no
            # acumular hasta el último día.
            pending_close = self.search([
                ("company_id", "=", company.id),
                ("l10n_ar_afip_auth_mode", "=", "CAEA"),
                ("l10n_ar_caea_rendido", "=", False),
                ("state", "=", "posted"),
                ("l10n_ar_caea_id", "!=", False),
            ])
            if pending_close:
                self._l10n_ar_caea_rendir_pending(pending_close)
        return True

    @api.model
    def _l10n_ar_caea_rendir_caea(self, caea):
        """Rinde un CAEA específico: si tiene moves pendientes →
        FECAEARegInformativo. Si no → FECAEASinMovimientoInformar
        por cada punto de venta. Marca como `reported` al final."""
        moves = self.search([
            ("company_id", "=", caea.company_id.id),
            ("l10n_ar_afip_auth_mode", "=", "CAEA"),
            ("l10n_ar_caea_id", "=", caea.id),
            ("l10n_ar_caea_rendido", "=", False),
            ("state", "=", "posted"),
        ])
        if moves:
            self._l10n_ar_caea_rendir_pending(moves)
            # Si ya quedaron todos rendidos → marcar caea reported
            still_pending = moves.filtered(lambda m: not m.l10n_ar_caea_rendido)
            if not still_pending:
                caea.write({"state": "reported"})
        else:
            # Sin movimiento — informar por cada punto de venta
            # potencial (los que tenga la company configurados).
            self._l10n_ar_caea_sin_movimiento(caea)
            caea.write({"state": "reported"})

    @api.model
    def _l10n_ar_caea_rendir_pending(self, moves):
        """Agrupa moves por (journal, cbte_tipo) y manda batches."""
        grouped = {}
        for m in moves:
            key = (m.journal_id.id, int(m.l10n_latam_document_type_id.code or 0))
            grouped.setdefault(key, self.browse())
            grouped[key] |= m
        for (journal_id, cbte_tipo), batch in grouped.items():
            try:
                batch._l10n_ar_caea_rendir_batch()
            except Exception as e:
                _logger.exception(
                    "Error rindiendo batch CAEA journal=%s tipo=%s: %s",
                    journal_id, cbte_tipo, e,
                )

    @api.model
    def _l10n_ar_caea_sin_movimiento(self, caea):
        """Informa a AFIP que `caea` se cierra sin movimientos.

        Hay que informar 1 vez por cada punto de venta de la company
        que esté habilitado para WSFEv1 (típicamente solo 1).
        """
        Log = self.env["l10n_ar.caea.log"]
        company = caea.company_id
        environment = company.l10n_ar_afip_ws_environment or "testing"
        Journal = self.env["account.journal"].sudo()
        # Detectar puntos de venta WSFEv1 de la company.
        journals = Journal.search([
            ("company_id", "=", company.id),
            ("l10n_ar_afip_pos_number", "!=", False),
        ])
        if not journals:
            Log._record_event(
                self.env, company, "sin_movimiento", success=False,
                caea=caea, message="No hay journals con punto de venta",
                triggered_by="cron",
            )
            return

        connection = self.env["l10n_ar.afip.ws.connection"]._get_or_create(
            company, "wsfe", environment,
        )
        auth = connection.get_auth()
        for journal in journals:
            tr = ws_transport.CapturingTransport(
                session=ws_transport.build_afip_session(), timeout=60,
            )
            try:
                response = ws_caea.caea_sin_movimiento_informar(
                    auth=auth, pto_vta=journal.l10n_ar_afip_pos_number,
                    caea=caea.code,
                    environment=environment, transport=tr,
                )
                Log._record_event(
                    self.env, company, "sin_movimiento", success=True,
                    caea=caea, message="Sin movimiento informado POS=%s — %s" % (
                        journal.l10n_ar_afip_pos_number, response.get("resultado") or "(sin resultado)",
                    ),
                    xml_request=_safe(tr.last_request),
                    xml_response=_safe(tr.last_response),
                    triggered_by="cron",
                )
            except Exception as e:
                Log._record_event(
                    self.env, company, "sin_movimiento", success=False,
                    caea=caea, message="Error sin movimiento POS=%s" % journal.l10n_ar_afip_pos_number,
                    error_msg=str(e),
                    xml_request=_safe(tr.last_request),
                    xml_response=_safe(tr.last_response),
                    triggered_by="cron",
                )
                _logger.warning(
                    "FECAEASinMovimientoInformar falló POS=%s caea=%s: %s",
                    journal.l10n_ar_afip_pos_number, caea.code, e,
                )

    def _l10n_ar_caea_rendir_batch(self):
        """Manda este recordset (mismo company+journal+cbte_tipo) a
        `FECAEARegInformativo` y loguea en `l10n_ar.caea.log`."""
        if not self:
            return
        Log = self.env["l10n_ar.caea.log"]
        first = self[0]
        company = first.company_id
        journal = first.journal_id
        cbte_tipo = int(first.l10n_latam_document_type_id.code or 0)
        caea = first.l10n_ar_caea_id
        environment = company.l10n_ar_afip_ws_environment or "testing"
        connection = self.env["l10n_ar.afip.ws.connection"]._get_or_create(
            company, "wsfe", environment,
        )
        auth = connection.get_auth()
        tr = ws_transport.CapturingTransport(
            session=ws_transport.build_afip_session(), timeout=60,
        )

        det_list = []
        for m in self:
            base = m._l10n_ar_get_wsfe_payload()
            det = base["FeDetReq"][0]["FECAEDetRequest"].copy()
            det["CAEA"] = m.l10n_ar_afip_auth_code
            if m.invoice_date:
                det["CbteFchHsGen"] = m.invoice_date.strftime("%Y%m%d") + "080000"
            det_list.append({"FECAEADetRequest": det})

        req = {
            "FeCabReq": {
                "CantReg": len(det_list),
                "PtoVta": journal.l10n_ar_afip_pos_number,
                "CbteTipo": cbte_tipo,
            },
            "FeDetReq": det_list,
        }

        try:
            response = ws_caea.caea_reg_informativo(
                auth=auth, fe_caea_reg_inf_req=req,
                environment=environment, transport=tr,
            )
        except Exception as e:
            Log._record_event(
                self.env, company, "rendir", success=False,
                caea=caea, message="Error rindiendo batch journal=%s tipo=%s" % (journal.name, cbte_tipo),
                error_msg=str(e),
                affected_count=len(self),
                xml_request=_safe(tr.last_request),
                xml_response=_safe(tr.last_response),
                triggered_by="cron",
            )
            raise

        result_by_nro = {
            d["CbteDesde"]: d["Resultado"]
            for d in response.get("detalle") or []
            if d.get("CbteDesde")
        }
        rendidos = self.browse()
        for m in self:
            try:
                nro = m._l10n_ar_get_cbte_nro()
            except Exception:
                continue
            if result_by_nro.get(nro) == "A":
                rendidos |= m

        rendidos.write({
            "l10n_ar_caea_rendido": True,
            "l10n_ar_caea_rendido_date": fields.Datetime.now(),
        })
        for m in rendidos:
            m.message_post(body=_(
                "📤 Rendición CAEA confirmada por AFIP (FECAEARegInformativo)."
            ))

        Log._record_event(
            self.env, company, "rendir",
            success=(len(rendidos) == len(self)),
            caea=caea,
            message="Rendidos %s/%s — journal=%s tipo=%s" % (
                len(rendidos), len(self), journal.name, cbte_tipo,
            ),
            affected_count=len(rendidos),
            xml_request=_safe(tr.last_request),
            xml_response=_safe(tr.last_response),
            triggered_by="cron",
        )
        _logger.info(
            "Batch CAEA rendido: %s/%s comprobantes aprobados",
            len(rendidos), len(self),
        )
