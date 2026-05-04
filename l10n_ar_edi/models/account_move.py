# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Emisión electrónica de comprobantes argentinos sobre `account.move`.

Responsabilidades de este archivo:

1. Orquestar el flujo de emisión: mapear account.move a payload AFIP,
   llamar al WS, guardar CAE/vto/resultado/XML en el move.
2. Calcular el QR RG 4291 cuando hay CAE (compute override del campo que
   `l10n_ar_edi_base` declaró como stub).
3. Acción manual "Enviar a ARCA" para disparar emisión fuera del `_post`.
4. Hook en `_post` — por ahora *opt-in*: solo se solicita CAE si el
   journal está marcado como electrónico. No queremos romper moves no
   argentinos ni journals preimpresos.

**Lo que este archivo NO hace**:
- Crear el secuencial del número de comprobante: eso lo hará Odoo core
  o un override posterior que sincronice con `FECompUltimoAutorizado`.
  Por ahora usamos el número que ya trae el move.
- Post-procesar observaciones en UI: solo las guardamos en texto plano;
  el wizard de consulta AFIP es otro entregable.
"""
import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import payload as payload_lib
from ..lib import payload_fex as payload_fex_lib
from ..lib import qr_code as qr_lib

# Reutilizamos el cliente de WS del módulo afip_ws
from odoo.addons.l10n_ar_afip_ws.lib import transport as ws_transport
from odoo.addons.l10n_ar_afip_ws.lib import wsfe as ws_wsfe
from odoo.addons.l10n_ar_afip_ws.lib import wsfex as ws_wsfex

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    # Bandera UX: True si este move se va a emitir contra WSFEv1 al
    # postear. Sirve para que el view reemplace el botón "Confirmar"
    # estándar por uno con string "Validar en AFIP/ARCA", que es más
    # explícito para el operador (sabe que ese click pega contra AFIP,
    # no es solo un cambio de estado contable).
    l10n_ar_is_electronic_invoice = fields.Boolean(
        string="Es factura electrónica AFIP",
        compute="_compute_l10n_ar_is_electronic_invoice",
        help="True si el journal está configurado para WSFEv1 y el move "
             "es una factura/NC argentina.",
    )

    @api.depends(
        "country_code", "move_type",
        "journal_id.l10n_ar_afip_pos_system",
    )
    def _compute_l10n_ar_is_electronic_invoice(self):
        for move in self:
            j = move.journal_id
            move.l10n_ar_is_electronic_invoice = bool(
                move.country_code == "AR"
                and move.move_type in ("out_invoice", "out_refund")
                and j
                and j.l10n_ar_afip_pos_system in j._L10N_AR_WSFE_POS_SYSTEMS
            )

    # --------------------------------------------------------------
    # Campos derivados
    # --------------------------------------------------------------
    def _compute_l10n_ar_afip_qr_code(self):
        """Override del stub en l10n_ar_edi_base. Calcula la URL del QR RG 4291."""
        for move in self:
            if not (move.l10n_ar_afip_auth_code and move.l10n_ar_afip_auth_mode in ("CAE", "CAEA")):
                move.l10n_ar_afip_qr_code = False
                continue
            try:
                data = move._l10n_ar_get_qr_data()
                move.l10n_ar_afip_qr_code = qr_lib.build_qr_url(data)
            except Exception as e:  # pragma: no cover - defensivo
                _logger.warning("No pude calcular el QR para move %s: %s", move.id, e)
                move.l10n_ar_afip_qr_code = False

    # --------------------------------------------------------------
    # Mapeo account.move → payload AFIP
    # --------------------------------------------------------------
    def _l10n_ar_get_qr_data(self):
        """Datos para el QR (dict listo para `qr_code.build_qr_payload`)."""
        self.ensure_one()
        cuit = (self.company_id.partner_id.vat or "").replace("-", "")
        doc_tipo, doc_nro = self._l10n_ar_get_receptor_doc()
        return qr_lib.build_qr_payload(
            cae=self.l10n_ar_afip_auth_code,
            date=self.invoice_date or fields.Date.context_today(self),
            cuit=cuit,
            pto_vta=self.journal_id.l10n_ar_afip_pos_number or 0,
            cbte_tipo=int(self.l10n_latam_document_type_id.code or 0),
            cbte_nro=self._l10n_ar_get_cbte_nro(),
            importe=self.amount_total,
            moneda=self._l10n_ar_get_afip_moneda(),
            cotizacion=self._l10n_ar_get_afip_cotizacion(),
            doc_tipo_receptor=doc_tipo,
            doc_nro_receptor=doc_nro,
            auth_mode=self.l10n_ar_afip_auth_mode,
        )

    def _l10n_ar_get_cbte_nro(self):
        """Extrae el número de comprobante (la parte después del '-')."""
        self.ensure_one()
        # l10n_ar core guarda el nombre como "000X-00000123" o "FA-A 0001-00000123"
        # según el formato del documento. Tomamos el último bloque numérico.
        name = self.name or ""
        parts = [p for p in name.replace(" ", "-").split("-") if p.strip().isdigit()]
        if parts:
            return int(parts[-1])
        raise UserError(_(
            "No pude extraer el número de comprobante del nombre %r. "
            "Verificá que el move tenga un nombre con formato 'NNNN-NNNNNNNN'."
        ) % name)

    def _l10n_ar_get_receptor_doc(self):
        """Devuelve (tipo_doc_afip, nro_doc) del partner receptor.

        Tipos AFIP: 80=CUIT, 86=CUIL, 96=DNI, 99=Consumidor Final sin ID.
        """
        self.ensure_one()
        p = self.partner_id
        # l10n_ar provee `l10n_latam_identification_type_id`; usamos su código AFIP.
        identification = p.l10n_latam_identification_type_id
        if identification and identification.l10n_ar_afip_code:
            try:
                doc_tipo = int(identification.l10n_ar_afip_code)
            except (TypeError, ValueError):
                doc_tipo = 99
        else:
            doc_tipo = 99
        vat = (p.vat or "").replace("-", "").replace(" ", "") if p.vat else ""
        if doc_tipo == 99 or not vat:
            return 99, 0
        try:
            return doc_tipo, int(vat)
        except ValueError:
            return 99, 0

    def _l10n_ar_get_afip_moneda(self):
        """Convierte currency.name a código AFIP ('PES', 'DOL', ...)."""
        self.ensure_one()
        code = self.currency_id.name
        # l10n_ar en community trae `l10n_ar_afip_code` en res.currency.
        if hasattr(self.currency_id, "l10n_ar_afip_code") and self.currency_id.l10n_ar_afip_code:
            return self.currency_id.l10n_ar_afip_code
        mapping = {"ARS": "PES", "USD": "DOL", "EUR": "060"}
        return mapping.get(code, code)

    def _l10n_ar_get_afip_cotizacion(self):
        self.ensure_one()
        if self.currency_id == self.company_id.currency_id:
            return 1
        # Rate inverso: si 1 USD = 1000 ARS y currency_id=USD,
        # Odoo guarda rate=1/1000 para USD; cotización AFIP espera ARS/USD = 1000.
        rate = self.currency_id._convert(
            1, self.company_id.currency_id, self.company_id,
            self.invoice_date or fields.Date.context_today(self),
        )
        return float(rate)

    def _l10n_ar_get_condicion_iva_receptor_id(self):
        """Código AFIP de condición IVA del receptor (RG 5616).

        Mapeo por responsabilidad AFIP del partner. Los códigos oficiales son:
            1=RI, 4=Exento, 5=Consumidor Final, 6=Monotributo, 7=SujetoNoCategorizado,
            8=Proveedor del Exterior, 9=Cliente del Exterior, 10=IVA Liberado,
            13=Monotributo Social, 15=IVA No Alcanzado, ...
        """
        self.ensure_one()
        p = self.partner_id
        resp = p.l10n_ar_afip_responsibility_type_id
        if not resp or not resp.code:
            return 5  # Consumidor Final por defecto
        # El code de l10n_ar ya es el código AFIP de responsabilidad, pero
        # el código de CondicionIVAReceptorId es otro catálogo. AFIP publica
        # un CSV con la correspondencia — acá pongo los 5-6 casos frecuentes.
        resp_to_cond = {
            "1": 1,    # IVA Responsable Inscripto
            "4": 4,    # IVA Sujeto Exento
            "5": 5,    # Consumidor Final
            "6": 6,    # Responsable Monotributo
            "8": 8,    # Proveedor del Exterior
            "9": 9,    # Cliente del Exterior
            "10": 10,  # IVA Liberado - Ley 19.640
            "13": 13,  # Monotributista Social
            "15": 15,  # IVA no alcanzado
        }
        return resp_to_cond.get(resp.code, 5)

    def _l10n_ar_get_iva_items(self):
        """Devuelve la lista de alícuotas con base e importe para AFIP.

        En Odoo 19 community l10n_ar el código AFIP del IVA vive en
        `account.tax.group.l10n_ar_vat_afip_code` (no en `account.tax` —
        eso era enterprise antiguo). Catálogo AFIP `AlicIva/Id`:
            3=0%, 4=10.5%, 5=21%, 6=27%, 8=5%, 9=2.5%.

        Recorre las líneas agrupando por ese código. Si un tax no tiene
        código AFIP (ej. percepciones, que van en ImpTrib, no en iva_items)
        lo filtra.
        """
        self.ensure_one()
        from collections import defaultdict
        acc = defaultdict(lambda: {"base": 0.0, "importe": 0.0})
        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                code = tax.tax_group_id.l10n_ar_vat_afip_code if tax.tax_group_id else None
                # Fallback para compat: si en alguna variante de l10n_ar el
                # código quedó directo en account.tax, lo leemos ahí también.
                if not code:
                    code = getattr(tax, "l10n_ar_afip_code", None)
                if not code:
                    continue
                # `price_subtotal` es la base sin IVA. Recalculamos el importe
                # `base * percent / 100` para consolidar entre líneas — no
                # confiamos en el `tax_line_id` del move porque puede tener
                # redondeos por línea que no suman al total AFIP esperado.
                base = line.price_subtotal
                try:
                    percent = float(tax.amount or 0)
                except Exception:
                    percent = 0.0
                importe = base * percent / 100.0
                acc[int(code)]["base"] += base
                acc[int(code)]["importe"] += importe
        return [
            {"codigo": code, "base": v["base"], "importe": v["importe"]}
            for code, v in acc.items()
        ]

    def _l10n_ar_get_tributos(self):
        """Devuelve la lista de Tributos para el nodo `Tributos` del WSFE.

        AFIP separa el IVA (que va en `Iva.AlicIva`) de los demás tributos
        (que van en `Tributos.Tributo`): percepción IIBB provincial,
        impuestos municipales, internos, percepción IVA RG3337, etc.

        En l10n_ar (community 19.0) el código AFIP del tributo vive en
        `account.tax.group.l10n_ar_tribute_afip_code` (Selection con
        valores `'01'..'09', '99'`). El mapeo a los Ids de WSFE es 1:1
        (`int(code)`), validado contra `FEParamGetTiposTributos` el
        2026-04-25:

            01 → 1  Impuestos nacionales
            02 → 2  Impuestos provinciales
            03 → 3  Tributos municipales
            04 → 4  Impuestos Internos
            06 → 6  Percepción de IVA
            07 → 7  Percepción de IIBB
            08 → 8  Percepciones por Tributos Municipales
            09 → 9  Otras Percepciones
            99 → 99 Otro

        Agrupa por `tax.id` (cada tax = un Tributo distinto) y suma la
        base por línea. Recalcula `Importe = BaseImp * Alic / 100` —
        igual razonamiento que en `_l10n_ar_get_iva_items`.
        """
        self.ensure_one()
        from collections import defaultdict
        acc = defaultdict(lambda: {"tax": None, "base": 0.0})
        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                code = (
                    tax.tax_group_id.l10n_ar_tribute_afip_code
                    if tax.tax_group_id else None
                )
                if not code:
                    continue
                acc[tax.id]["tax"] = tax
                acc[tax.id]["base"] += line.price_subtotal
        items = []
        for tax_id, v in acc.items():
            tax = v["tax"]
            try:
                id_tributo = int(tax.tax_group_id.l10n_ar_tribute_afip_code)
            except Exception:
                continue
            try:
                alic = float(tax.amount or 0)
            except Exception:
                alic = 0.0
            base = v["base"]
            importe = base * alic / 100.0
            items.append({
                "Id": id_tributo,
                # AFIP recorta `Desc` a 80 chars en su validador.
                "Desc": (tax.name or "")[:80],
                "BaseImp": round(base, 2),
                "Alic": round(alic, 2),
                "Importe": round(importe, 2),
            })
        return items

    def _l10n_ar_get_cbtes_asoc(self):
        """Devuelve la lista de `CbteAsoc` para NC / ND.

        AFIP exige esto para NC (doc codes 3, 8, 13) y ND (2, 7, 12) cuando
        la factura original existe. El bloque `CbteAsoc` lleva Tipo, PtoVta,
        Nro; Cuit y CbteFch son opcionales pero recomendados porque AFIP
        los valida contra sus registros.

        - NC: core Odoo setea `reversed_entry_id` al invocar `_reverse_moves`.
        - ND: l10n_ar community (si está) expone `debit_origin_id`. Si el
          campo no existe, lo ignoramos silenciosamente.
        """
        self.ensure_one()
        origin = self.reversed_entry_id if self.reversed_entry_id else self.env["account.move"]
        if not origin and "debit_origin_id" in self._fields:
            origin = self.debit_origin_id or origin
        if not origin:
            return []
        if not origin.l10n_latam_document_type_id:
            return []
        if not origin.l10n_ar_afip_auth_code:
            # Origen sin CAE ⇒ no se puede asociar a AFIP todavía. Dejamos
            # que el builder arme el request sin CbtesAsoc; si AFIP lo
            # rechaza, el usuario verá el error claro y emite primero la FA.
            return []
        cbte_nro_str = (origin.l10n_latam_document_number or "").split("-")[-1]
        if not cbte_nro_str.isdigit():
            return []
        cbte = {
            "Tipo": int(origin.l10n_latam_document_type_id.code),
            "PtoVta": origin.journal_id.l10n_ar_afip_pos_number,
            "Nro": int(cbte_nro_str),
        }
        emisor_vat = (origin.company_id.vat or "").replace("-", "").replace(" ", "")
        if emisor_vat.isdigit():
            cbte["Cuit"] = emisor_vat
        if origin.invoice_date:
            cbte["CbteFch"] = origin.invoice_date.strftime("%Y%m%d")
        return [cbte]

    def _l10n_ar_get_wsfe_payload(self):
        """Construye el dict `FeCAEReq` para `FECAESolicitar`.

        :return: dict listo para pasar a `wsfe.cae_solicitar`.
        """
        self.ensure_one()
        doc_tipo, doc_nro = self._l10n_ar_get_receptor_doc()
        # Concepto: l10n_ar community ya lo computa según los tipos de
        # producto de las líneas (method `_compute_l10n_ar_afip_concept`
        # / `_get_concept`). Valores: '1'=Productos, '2'=Servicios,
        # '3'=Productos y Servicios. Si está vacío (no AR o sin docs),
        # caemos a productos.
        concepto_str = self.l10n_ar_afip_concept or str(payload_lib.CONCEPTO_PRODUCTOS)
        concepto = int(concepto_str)
        # Tributos (percepciones IIBB, municipales, etc.). amount_tax de
        # Odoo SUMA IVA + percepciones. Para WSFE necesitamos separar:
        #   imp_iva = solo IVA (taxes con `l10n_ar_vat_afip_code`)
        #   imp_trib = solo tributos (taxes con `l10n_ar_tribute_afip_code`)
        tributos = self._l10n_ar_get_tributos()
        imp_trib = sum(t["Importe"] for t in tributos)
        # imp_iva = amount_tax - imp_trib (lo que sobra es IVA puro).
        imp_iva = round((self.amount_tax or 0.0) - imp_trib, 2)

        kwargs = dict(
            pto_vta=self.journal_id.l10n_ar_afip_pos_number,
            cbte_tipo=int(self.l10n_latam_document_type_id.code),
            concepto=concepto,
            cbte_fecha=self.invoice_date,
            doc_tipo=doc_tipo,
            doc_nro=doc_nro,
            cbte_nro=self._l10n_ar_get_cbte_nro(),
            imp_neto=self.amount_untaxed,
            imp_iva=imp_iva,
            imp_trib=imp_trib,
            imp_op_ex=0,
            imp_tot_conc=0,
            mon_id=self._l10n_ar_get_afip_moneda(),
            mon_cotiz=self._l10n_ar_get_afip_cotizacion(),
            cond_iva_receptor_id=self._l10n_ar_get_condicion_iva_receptor_id(),
            iva_items=self._l10n_ar_get_iva_items(),
        )
        if tributos:
            kwargs["tributos"] = tributos
        # Para servicios/mixto AFIP exige el período y vto de pago.
        if concepto in (payload_lib.CONCEPTO_SERVICIOS, payload_lib.CONCEPTO_MIXTO):
            kwargs["fch_serv_desde"] = self.l10n_ar_afip_service_start or self.invoice_date
            kwargs["fch_serv_hasta"] = self.l10n_ar_afip_service_end or self.invoice_date
            kwargs["fch_vto_pago"] = self.invoice_date_due or self.invoice_date
        # NC / ND: adjuntar comprobantes asociados si los hay.
        cbtes_asoc = self._l10n_ar_get_cbtes_asoc()
        if cbtes_asoc:
            kwargs["cbtes_asoc"] = cbtes_asoc
        # Opcionales (FCE Id=27 SCA/ADC, Id=2101 CBU, Id=22 cancelación, etc.)
        # — el método base devuelve [], los módulos hijos lo extienden.
        opcionales = self._l10n_ar_get_opcionales()
        if opcionales:
            kwargs["opcionales"] = opcionales
        # Política RG 5616 — pago en moneda extranjera.
        if self.currency_id != self.company_id.currency_id:
            kwargs["can_mis_mon_ext"] = self._l10n_ar_get_can_mis_mon_ext()
        return payload_lib.build_fecae_request(**kwargs)

    def _l10n_ar_get_opcionales(self):
        """Hook extensible: devuelve lista de dicts {Id, Valor} para `Opcionales`.

        Base vacío; FCE MiPyME (`account_move_fce.py`) lo extiende para
        agregar Id=27 (SCA/ADC), Id=2101 (CBU), Id=22 (es cancelación).
        Otros features pueden agregar más en sus propios overrides.
        """
        self.ensure_one()
        return []

    def _l10n_ar_get_can_mis_mon_ext(self):
        """Hook extensible: devuelve 'S' o 'N' para CanMisMonExt (RG 5616).

        Base devuelve 'N'; el override de moneda extranjera lo computa según
        la política de la empresa y la moneda del comprobante.
        """
        self.ensure_one()
        return "N"

    # --------------------------------------------------------------
    # Emisión
    # --------------------------------------------------------------
    def action_l10n_ar_request_cae(self):
        """Botón manual: solicita CAE para los moves seleccionados."""
        for move in self:
            move._l10n_ar_request_cae()

    def action_l10n_ar_validar_arca(self):
        """Wrapper UX para `action_post()` en facturas electrónicas.

        El override de `_post` ya emite el CAE automáticamente — este
        método existe solo para que el botón de la UI tenga un `name`
        distinto a `action_post` y no colisione con el botón estándar
        de Odoo en la misma vista (cuando hay dos `<button>` con el
        mismo `name`, el `position="attributes"` no discrimina bien).
        """
        return self.action_post()

    def _l10n_ar_request_cae(self):
        """Dispatcher CAE — decide si va por WSFEv1 o WSFEX según el journal."""
        self.ensure_one()

        if self.l10n_ar_afip_result == "A" and self.l10n_ar_afip_auth_code:
            raise UserError(_(
                "El comprobante %s ya tiene CAE %s. Si querés reenviar, "
                "consultá primero con AFIP (FECompConsultar)."
            ) % (self.name, self.l10n_ar_afip_auth_code))

        ws = self.journal_id._l10n_ar_afip_ws_for_emission
        if ws == "wsfe":
            return self._l10n_ar_request_cae_wsfe()
        if ws == "wsfex":
            return self._l10n_ar_request_cae_wsfex()
        raise UserError(_(
            "El diario %s no está configurado para emisión electrónica "
            "(sistema AFIP actual = %s; soportados: WSFEv1 (RLI_RLM) y "
            "WSFEXv1 (FEERCEL/FEERCELP))."
        ) % (
            self.journal_id.name,
            self.journal_id.l10n_ar_afip_pos_system or "∅",
        ))

    def _l10n_ar_request_cae_wsfe(self):
        """Flujo WSFEv1 — mercado interno."""
        self.ensure_one()
        company = self.company_id
        environment = company.l10n_ar_afip_ws_environment or "testing"
        connection = self.env["l10n_ar.afip.ws.connection"]._get_or_create(
            company, "wsfe", environment,
        )
        auth = connection.get_auth()

        fe_req = self._l10n_ar_get_wsfe_payload()

        tr = ws_transport.CapturingTransport(
            session=ws_transport.build_afip_session(), timeout=60,
        )
        try:
            response = ws_wsfe.cae_solicitar(
                auth=auth, fe_cae_req=fe_req,
                environment=environment, transport=tr,
            )
        finally:
            # siempre guardamos XML, incluso si hubo excepción
            self.l10n_ar_afip_xml_request = _decode_safe(tr.last_request)
            self.l10n_ar_afip_xml_response = _decode_safe(tr.last_response)

        self._l10n_ar_apply_cae_response(response)

    def _l10n_ar_request_cae_wsfex(self):
        """Flujo WSFEXv1 — Factura Electrónica de Exportación.

        Diferencias vs WSFEv1:
          1. Usa cache TA distinto (`wsfex`).
          2. Pide `FEXGetLast_ID` para incrementar el Id de transacción
             (independiente del Cbte_nro).
          3. Pide `FEXGetLast_CMP` para saber el siguiente Cbte_nro
             (community no rota la secuencia automática como hace para WSFE).
          4. Llama a `FEXAuthorize` con un payload distinto.
          5. La respuesta tiene otra estructura (`FEXResultAuth`).
        """
        self.ensure_one()

        # Pre-flight: si el journal no tiene default_account_id, Odoo va
        # a fallar al armar las account.move.line DESPUÉS de obtener el
        # CAE → quedaría un CAE huérfano en AFIP sin contraparte en
        # Odoo. Mejor abortar antes y levantar UserError clara.
        if not self.journal_id.default_account_id:
            raise UserError(_(
                "El diario %s no tiene 'Cuenta predeterminada' configurada. "
                "Si emitimos sin esto, AFIP va a tomar el CAE pero Odoo no "
                "va a poder asentar el comprobante (queda CAE huérfano). "
                "Configurá la cuenta contable en el journal antes de emitir."
            ) % self.journal_id.name)

        company = self.company_id
        environment = company.l10n_ar_afip_ws_environment or "testing"
        connection = self.env["l10n_ar.afip.ws.connection"]._get_or_create(
            company, "wsfex", environment,
        )
        auth = connection.get_auth()

        # 1) Construir el payload (necesita last_id y cbte_nro).
        tr = ws_transport.CapturingTransport(
            session=ws_transport.build_afip_session(), timeout=60,
        )
        try:
            last_id = ws_wsfex.get_last_id(
                auth=auth, environment=environment, transport=tr,
            )
            last_cmp = ws_wsfex.get_last_cmp(
                auth=auth,
                pto_vta=self.journal_id.l10n_ar_afip_pos_number,
                cbte_tipo=int(self.l10n_latam_document_type_id.code or 0),
                environment=environment, transport=tr,
            )
            next_cbte_nro = int((last_cmp or {}).get("cbte_nro") or 0) + 1

            cmp_dict = self._l10n_ar_get_wsfex_payload(last_id, next_cbte_nro)

            # 2) Emitir.
            response = ws_wsfex.authorize(
                auth=auth, cmp_dict=cmp_dict,
                environment=environment, transport=tr,
            )
        finally:
            self.l10n_ar_afip_xml_request = _decode_safe(tr.last_request)
            self.l10n_ar_afip_xml_response = _decode_safe(tr.last_response)

        self._l10n_ar_apply_fex_response(response, next_cbte_nro)

    def _l10n_ar_apply_fex_response(self, response, expected_cbte_nro):
        """Vuelca el dict devuelto por `wsfex.authorize` al move."""
        self.ensure_one()
        resultado = response.get("resultado")  # 'A' o 'R'
        cae = response.get("cae")
        fch_vto_raw = response.get("cae_fecha_vto")
        cbte_nro = response.get("cbte_nro")
        motivos = response.get("motivos_obs") or ""
        reproc = response.get("reproceso") or ""

        vals = {"l10n_ar_afip_result": resultado}
        if resultado == "A":
            vals["l10n_ar_afip_auth_mode"] = "CAE"
            vals["l10n_ar_afip_auth_code"] = cae
            if fch_vto_raw:
                try:
                    vals["l10n_ar_afip_auth_code_due"] = datetime.strptime(
                        str(fch_vto_raw), "%Y%m%d"
                    ).date()
                except (TypeError, ValueError):
                    pass
            if cbte_nro and int(cbte_nro) != int(expected_cbte_nro):
                _logger.warning(
                    "WSFEX devolvió Cbte_nro=%s pero esperaba %s — posible reproceso",
                    cbte_nro, expected_cbte_nro,
                )
        elif resultado == "R":
            raise UserError(_(
                "AFIP rechazó la FA-E %s: %s"
            ) % (self.name, motivos or _("(sin detalle)")))

        if motivos:
            vals["l10n_ar_afip_observations"] = str(motivos)
        if reproc and reproc != "N":
            vals["l10n_ar_afip_observations"] = (
                (vals.get("l10n_ar_afip_observations") or "")
                + " [Reproceso=%s]" % reproc
            )
        self.write(vals)

    def _l10n_ar_get_wsfex_payload(self, last_id, cbte_nro):
        """Mapea este account.move al dict que espera `wsfex.authorize`.

        Reusa la lib pura `payload_fex.build_fex_request` — toda la lógica
        de redondeos/formato vive ahí. Acá solo hacemos el extract de
        Odoo → dict denormalizado.
        """
        self.ensure_one()
        partner = self.commercial_partner_id
        country = partner.country_id

        if not country:
            raise UserError(_(
                "El cliente '%s' no tiene país configurado — WSFEX lo exige."
            ) % partner.name)
        country_afip_code = getattr(country, "l10n_ar_afip_code", None)
        if not country_afip_code:
            raise UserError(_(
                "El país '%s' no tiene `l10n_ar_afip_code`. "
                "Cargalo desde Configuración → Países, o instalá l10n_ar."
            ) % country.name)

        # Cuit_pais_cliente: legal entity vs natural según is_company.
        if partner.is_company:
            cuit_pais = getattr(country, "l10n_ar_legal_entity_vat", None) or 0
        else:
            cuit_pais = getattr(country, "l10n_ar_natural_vat", None) or 0

        # Moneda y cotización.
        cur = self.currency_id
        company_cur = self.company_id.currency_id
        moneda_id = getattr(cur, "l10n_ar_afip_code", None) or "PES"
        if cur == company_cur:
            moneda_ctz = 1.0
        else:
            inv_rate = self.invoice_currency_rate or 1.0
            moneda_ctz = (1.0 / inv_rate) if inv_rate else 1.0

        # Items: uno por línea de factura (no agrupamos).
        # En Odoo 19 `display_type` puede ser 'product' (líneas reales),
        # 'line_section' o 'line_note'. Solo saltamos secciones y notas.
        items = []
        for line in self.invoice_line_ids:
            if line.display_type in ("line_section", "line_note"):
                continue
            uom_code = getattr(line.product_uom_id, "l10n_ar_afip_code", None) or "7"
            try:
                uom_int = int(uom_code)
            except (TypeError, ValueError):
                uom_int = 7
            items.append({
                "Pro_codigo": (line.product_id.default_code or "")[:50],
                "Pro_ds": (line.name or line.product_id.display_name or "")[:4000],
                "Pro_qty": line.quantity or 0,
                "Pro_umed": uom_int,
                "Pro_precio_uni": line.price_unit or 0,
                "Pro_total_item": line.price_subtotal or 0,
                "Pro_bonificacion": 0,  # community no separa el descuento por linea
            })

        if not items:
            raise UserError(_(
                "La factura %s no tiene líneas de producto — WSFEX exige "
                "al menos un ítem."
            ) % self.name)

        # Domicilio cliente combinado.
        domicilio_parts = [
            partner.name or "",
            partner.street or "",
            partner.street2 or "",
            partner.zip or "",
            partner.city or "",
        ]
        domicilio_cliente = " - ".join([p for p in domicilio_parts if p])

        # Tipo expo: usar concepto AFIP si está, sino default Productos.
        tipo_expo_str = self.l10n_ar_afip_concept or "1"
        try:
            tipo_expo = int(tipo_expo_str)
        except (TypeError, ValueError):
            tipo_expo = 1
        if tipo_expo not in (1, 2, 4):
            tipo_expo = 1  # AFIP solo acepta 1/2/4 en Tipo_expo

        cbte_tipo_int = int(self.l10n_latam_document_type_id.code or 19)

        # Cmps_asoc para NC/ND (refund).
        cmps_asoc = None
        if cbte_tipo_int in (20, 21):
            ref = self._l10n_ar_get_wsfex_related_invoice()
            if ref:
                cmps_asoc = [ref]

        # Incoterm — community lo trae como `account.incoterm`.
        incoterm = self.invoice_incoterm_id if hasattr(self, "invoice_incoterm_id") else None
        incoterms_code = (incoterm.code if incoterm else None) or None
        incoterms_ds = (incoterm.name if incoterm else None) or None

        # Forma de pago — usamos el name del payment_term si está.
        forma_pago = self.invoice_payment_term_id.name if self.invoice_payment_term_id else None

        return payload_fex_lib.build_fex_request(
            last_id=last_id,
            fecha_cbte=self.invoice_date,
            cbte_tipo=cbte_tipo_int,
            pto_vta=self.journal_id.l10n_ar_afip_pos_number,
            cbte_nro=cbte_nro,
            tipo_expo=tipo_expo,
            dst_cmp=country_afip_code,
            cliente=partner.name or "",
            domicilio_cliente=domicilio_cliente,
            id_impositivo=partner.vat or "",
            cuit_pais_cliente=cuit_pais,
            moneda_id=moneda_id,
            moneda_ctz=moneda_ctz,
            imp_total=self.amount_total,
            items=items,
            incoterms=incoterms_code,
            incoterms_ds=incoterms_ds,
            forma_pago=forma_pago,
            obs_comerciales=forma_pago,  # mismo string en ambos
            fecha_pago=self.invoice_date_due,
            cmps_asoc=cmps_asoc,
        )

    def _l10n_ar_get_wsfex_related_invoice(self):
        """Para NC/ND-E, devuelve el dict Cmp_asoc apuntando a la FA-E original."""
        self.ensure_one()
        # community guarda la relación en `reversed_entry_id` (refunds) o en
        # `debit_origin_id` (debits).
        related = self.reversed_entry_id or getattr(self, "debit_origin_id", False)
        if not related:
            return None
        try:
            related_cbte_tipo = int(related.l10n_latam_document_type_id.code or 0)
        except (TypeError, ValueError):
            return None
        # Cbte_nro: parsear de l10n_latam_document_number "01234-00000001" → 1.
        s = related.l10n_latam_document_number or ""
        nro = 0
        if "-" in s:
            try:
                nro = int(s.split("-")[-1])
            except (ValueError, IndexError):
                pass
        if not nro:
            return None
        return payload_fex_lib.build_cmp_asoc(
            cbte_tipo=related_cbte_tipo,
            pto_vta=related.journal_id.l10n_ar_afip_pos_number or 0,
            cbte_nro=nro,
            cuit_emisor=(related.company_id.partner_id.vat or "").replace("-", "").strip() or "0",
        )

    def _l10n_ar_apply_cae_response(self, response):
        """Vuelca el dict devuelto por `wsfe.cae_solicitar` al move."""
        self.ensure_one()
        detalle = response.get("detalle") or []
        if not detalle:
            raise UserError(_(
                "AFIP no devolvió detalle en la respuesta. XML crudo en el "
                "campo l10n_ar_afip_xml_response."
            ))
        det = detalle[0]
        resultado = det.get("Resultado")  # 'A', 'R', 'O'
        cae = det.get("CAE")
        fecha_vto_raw = det.get("CAEFchVto")  # YYYYMMDD como str
        observaciones = det.get("Observaciones")

        vals = {"l10n_ar_afip_result": resultado}
        if resultado == "A":
            vals["l10n_ar_afip_auth_mode"] = "CAE"
            vals["l10n_ar_afip_auth_code"] = cae
            if fecha_vto_raw:
                vals["l10n_ar_afip_auth_code_due"] = datetime.strptime(
                    str(fecha_vto_raw), "%Y%m%d"
                ).date()
        elif resultado == "R":
            # Rechazado — re-levantamos con el mensaje para que el usuario
            # sepa qué corregir. No dejamos el move en estado "posted con
            # auth_code vacío", cancelamos lo escrito al move.
            msg = _extract_observations_text(observaciones) or _("(sin detalle)")
            raise UserError(_(
                "AFIP rechazó el comprobante %s: %s"
            ) % (self.name, msg))
        # resultado == 'O' → observado: CAE igual se devuelve pero con
        # advertencias. Guardamos los mensajes y seguimos.

        if observaciones:
            vals["l10n_ar_afip_observations"] = _extract_observations_text(observaciones)

        self.write(vals)

    # --------------------------------------------------------------
    # Hook en _post
    # --------------------------------------------------------------
    def _post(self, soft=True):
        """Después del post estándar, dispara CAE si el journal es electrónico.

        Si AFIP rechaza, el post *ya fue hecho* y el move queda 'posted'
        sin CAE. Esto deja el move en un estado inconsistente; mejor
        pedir CAE *antes* de postear. Sin embargo el flujo Odoo clásico
        es postear → luego emitir, y hacer lo contrario requiere mover
        la numeración, tributos, etc. Para MVP: pedir CAE después, pero
        si falla levantar y dejar que el usuario vea el error. El move
        queda posted pero con `l10n_ar_afip_result='R'` y XML guardado.
        """
        posted = super()._post(soft=soft)
        for move in posted:
            if move.country_code != "AR":
                continue
            if move.move_type not in ("out_invoice", "out_refund", "out_receipt"):
                continue
            if not move.journal_id._l10n_ar_afip_ws_for_emission:
                # Journal no es electrónico (WSFE/WSFEX) — no disparar CAE.
                continue
            if move.l10n_ar_afip_auth_code:
                # Ya tiene CAE (p.ej. consulta previa al post).
                continue
            try:
                move._l10n_ar_request_cae()
            except UserError:
                # UserError se burbujea — el usuario la ve y puede
                # corregir y reintentar con el botón manual.
                raise
        return posted


def _decode_safe(maybe_bytes):
    if maybe_bytes is None:
        return False
    if isinstance(maybe_bytes, bytes):
        try:
            return maybe_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return maybe_bytes.decode("latin-1", errors="replace")
    return str(maybe_bytes)


def _extract_observations_text(obs):
    """Serializa el nodo `Observaciones` de WSFE a texto plano."""
    if not obs:
        return ""
    # zeep nos lo da como objeto con atributo Obs (lista de {Code, Msg}).
    items = getattr(obs, "Obs", None)
    if items is None and isinstance(obs, dict):
        items = obs.get("Obs")
    if not items:
        return str(obs)
    lines = []
    for it in items:
        code = getattr(it, "Code", None) or (it.get("Code") if isinstance(it, dict) else None)
        msg = getattr(it, "Msg", None) or (it.get("Msg") if isinstance(it, dict) else None)
        lines.append("[%s] %s" % (code, msg))
    return "\n".join(lines)
