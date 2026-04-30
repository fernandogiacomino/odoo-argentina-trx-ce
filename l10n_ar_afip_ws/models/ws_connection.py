# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Modelo de conexión a AFIP WS — token/sign cacheados por (empresa, ws, env).

¿Por qué un modelo de cache en vez de un `ir.attachment` o un diccionario en
memoria? Tres razones:

1. **Multi-worker**: Odoo en producción corre con varios workers; un dict en
   memoria se duplica por worker y no sirve.
2. **Persistencia entre restarts**: el TA dura 12h, sería tonto tirarlo al
   reiniciar el server.
3. **Auditoría**: guardar fecha de generación y expiración permite responder
   preguntas como "¿qué TA usé cuando emití la factura 123?".

El modelo guarda **un registro por** (company_id, ws, environment). El flujo
es: `get_auth()` → si hay TA vigente, devolverlo; si no, generar uno nuevo,
guardarlo y devolverlo.
"""
import logging
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import transport, urls, wsaa

_logger = logging.getLogger(__name__)

#: margen de seguridad: si le quedan menos minutos al TA, lo renuevo.
TA_RENEWAL_MARGIN_MINUTES = 10


class L10nArAfipWsConnection(models.Model):
    _name = "l10n_ar.afip.ws.connection"
    _description = "Token cacheado de WSAA por empresa / WS / entorno"
    _rec_name = "display_name"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        index=True,
    )
    ws = fields.Selection(
        [
            ("wsfe", "WSFEv1 (Factura Electrónica)"),
            ("wsfex", "WSFEX (Exportación)"),
            ("wsbfe", "WSBFE (Bono Fiscal Electrónico)"),
            ("wscdc", "WSCDC (Constatación de Comprobantes)"),
            ("wsmtxca", "WSMTXCA (con detalle de items)"),
            ("ws_sr_padron_a13", "Padrón AFIP A13 (mínimo)"),
            ("ws_sr_constancia_inscripcion", "Padrón AFIP A5 (Constancia de Inscripción completa)"),
        ],
        required=True,
        string="Servicio",
    )
    environment = fields.Selection(
        [
            ("testing", "Homologación"),
            ("production", "Producción"),
        ],
        required=True,
    )
    token = fields.Text(readonly=True)
    sign = fields.Text(readonly=True)
    generation_time = fields.Datetime(readonly=True)
    expiration_time = fields.Datetime(readonly=True)
    last_login_xml_request = fields.Text(readonly=True, string="Último XML enviado")
    last_login_xml_response = fields.Text(readonly=True, string="Último XML recibido")
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        (
            "uniq_company_ws_env",
            "unique(company_id, ws, environment)",
            "Ya existe una conexión para esa combinación empresa/WS/entorno.",
        ),
    ]

    @api.depends("company_id", "ws", "environment")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s · %s · %s" % (
                rec.company_id.name or "",
                rec.ws or "",
                rec.environment or "",
            )

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    @api.model
    def _get_or_create(self, company, ws, environment):
        """Devuelve (o crea) el registro de conexión para esa combinación."""
        rec = self.search([
            ("company_id", "=", company.id),
            ("ws", "=", ws),
            ("environment", "=", environment),
        ], limit=1)
        if rec:
            return rec
        return self.create({
            "company_id": company.id,
            "ws": ws,
            "environment": environment,
        })

    def _is_token_valid(self):
        """Dice si el token actual sirve o hay que renovarlo."""
        self.ensure_one()
        if not (self.token and self.sign and self.expiration_time):
            return False
        margin = timedelta(minutes=TA_RENEWAL_MARGIN_MINUTES)
        return datetime.utcnow() + margin < self.expiration_time

    def get_auth(self):
        """Devuelve dict {cuit, token, sign} listo para mandar a los WS.

        Renueva automáticamente si el TA expiró (o está por expirar).
        """
        self.ensure_one()
        if not self._is_token_valid():
            self._renew_token()
        cuit = self._get_cuit()
        return {
            "cuit": cuit,
            "token": self.token,
            "sign": self.sign,
        }

    def _get_cuit(self):
        """Extrae el CUIT de la empresa (`res.partner.vat` para AR)."""
        self.ensure_one()
        partner = self.company_id.partner_id
        cuit = (partner.vat or "").replace("-", "").strip()
        if not (cuit.isdigit() and len(cuit) == 11):
            raise UserError(_(
                "La empresa %s no tiene un CUIT válido cargado (vat=%s). "
                "Poné el CUIT de 11 dígitos en el partner de la empresa."
            ) % (self.company_id.name, partner.vat))
        return cuit

    # ------------------------------------------------------------------
    # Renovación del token
    # ------------------------------------------------------------------
    def _renew_token(self):
        """Pide un TA nuevo a WSAA y lo guarda."""
        self.ensure_one()
        cert = self._get_certificate()
        # el transport lo creamos nuevo por llamada — no reutilizamos para
        # evitar estado compartido entre empresas/WS.
        tr = transport.CapturingTransport(
            session=transport.build_afip_session(),
            timeout=30,
        )

        def _sign_cms(message_bytes):
            return cert._l10n_ar_pkcs7_sign(message_bytes)

        # OJO: `self.ws` es la KEY del Selection (descriptiva, p.ej.
        # `ws_sr_constancia_inscripcion`), pero el nombre técnico que
        # AFIP espera en `<service>` del LoginTicketRequest puede ser
        # otro (p.ej. `ws_sr_padron_a13`). El mapping vive en `urls.py`
        # como `login_service_name`.
        login_service_name = urls.get_login_service_name(self.ws, self.environment)
        try:
            ticket = wsaa.get_ticket(
                service_name=login_service_name,
                environment=self.environment,
                sign_cms=_sign_cms,
                transport=tr,
            )
        except Exception as e:
            # Persistimos el XML aunque falle, para debugging.
            self.write({
                "last_login_xml_request": _decode_safe(tr.last_request),
                "last_login_xml_response": _decode_safe(tr.last_response),
            })
            raise

        self.write({
            "token": ticket["token"],
            "sign": ticket["sign"],
            "generation_time": ticket["generation_time"],
            "expiration_time": ticket["expiration_time"],
            "last_login_xml_request": _decode_safe(tr.last_request),
            "last_login_xml_response": _decode_safe(tr.last_response),
        })
        _logger.info(
            "WSAA: TA renovado para %s (expira %s)",
            self.display_name, self.expiration_time,
        )

    def _get_certificate(self):
        """Devuelve el `certificate.certificate` a usar para esta conexión.

        Busca el cert configurado en la compañía. Si no hay, error claro.
        La relación company → certificate la define `l10n_ar_edi_base`
        (campo `l10n_ar_afip_ws_environment` + `l10n_ar_afip_ws_cert_id`).
        """
        self.ensure_one()
        cert = self.company_id.l10n_ar_afip_ws_cert_id
        if not cert:
            raise UserError(_(
                "La empresa %s no tiene un certificado AFIP configurado. "
                "Andá a Configuración → Compañías → pestaña Argentina y "
                "cargá el certificado."
            ) % self.company_id.name)
        # sanity: si el certificate está marcado como production pero la
        # conexión es testing (o viceversa), avisamos.
        expected_env = self.company_id.l10n_ar_afip_ws_environment
        if expected_env and expected_env != self.environment:
            _logger.warning(
                "La empresa %s tiene environment=%s pero se está pidiendo TA para %s",
                self.company_id.name, expected_env, self.environment,
            )
        return cert


def _decode_safe(maybe_bytes):
    """Devuelve un str para guardar en un campo Text, sin explotar por encoding."""
    if maybe_bytes is None:
        return False
    if isinstance(maybe_bytes, bytes):
        try:
            return maybe_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return maybe_bytes.decode("latin-1", errors="replace")
    return str(maybe_bytes)
