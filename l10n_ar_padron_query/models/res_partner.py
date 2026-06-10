# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Extensión de `res.partner`: autocomplete desde WS Padrón AFIP.

Dos puntos de entrada:

* :py:meth:`action_l10n_ar_padron_query` — botón "Consultar AFIP" en la
  vista del partner (``views/res_partner_view.xml``).
* :py:meth:`_onchange_vat_l10n_ar_padron` — onchange sobre ``vat``: al
  salir del campo, si el valor parece un CUIT/CUIL (11 dígitos con
  checksum válido), dispara la consulta automáticamente.

La empresa que consulta es ``self.env.company`` y debe tener:

1. Un certificado AFIP cargado y delegado para
   ``ws_sr_constancia_inscripcion`` en el portal AFIP. Ese trámite
   habilita el WSDL ``personaServiceA5``, que es el que usamos por
   defecto porque trae responsabilidad IVA + impuestos + actividades.
   (Si solo querés A13/mínimo, también está disponible — son
   delegaciones separadas, no apareadas.)
2. ``l10n_ar_afip_ws_environment`` configurado (testing | production).

Si la empresa no tiene cert configurado, el botón muestra un UserError
claro y el onchange falla en silencio (sólo ``_logger.warning``) — la
idea es no romper la edición del partner si Padrón está caído.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.l10n_ar_afip_ws.lib import errors as ws_errors
from odoo.addons.l10n_ar_afip_ws.lib import padron as padron_lib
from odoo.addons.l10n_ar_afip_ws.lib import transport as transport_lib

_logger = logging.getLogger(__name__)

#: Códigos AFIP de identification type que tienen sentido para Padrón.
#: 80 = CUIT, 86 = CUIL, 87 = CDI.
_AFIP_CODE_BY_TIPO_CLAVE = {
    "CUIT": "80",
    "CUIL": "86",
    "CDI": "87",
}

#: Multiplicadores para el dígito verificador del CUIT.
_CUIT_CHECKSUM_FACTORS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

#: AFIP idProvincia (int) → `res.country.state.code` (letra ISO 3166-2:AR)
#: en `l10n_ar`. El padrón A13/A5 devuelve `idProvincia` numérico según
#: SUPA. Tabla oficial AFIP "Código de provincias":
#: https://www.afip.gob.ar/inversiones-bienes-uso/documentos/codigo-provincia.pdf
#: Verificada además contra el ejemplo del manual ws_sr_padron_a13 v1.2
#: (11 = SAN LUIS) y respuesta real del WS prod (12 = SANTA FE).
#: OJO: el orden NO es alfabético — no "corregir" ordenando.
_AFIP_IDPROV_TO_STATE_CODE = {
    0: "C",   # Ciudad Autónoma de Buenos Aires
    1: "B",   # Buenos Aires
    2: "K",   # Catamarca
    3: "X",   # Córdoba
    4: "W",   # Corrientes
    5: "E",   # Entre Ríos
    6: "Y",   # Jujuy
    7: "M",   # Mendoza
    8: "F",   # La Rioja
    9: "A",   # Salta
    10: "J",  # San Juan
    11: "D",  # San Luis
    12: "S",  # Santa Fe
    13: "G",  # Santiago del Estero
    14: "T",  # Tucumán
    15: "H",  # Chaco
    16: "U",  # Chubut
    17: "P",  # Formosa
    18: "N",  # Misiones
    19: "Q",  # Neuquén
    20: "L",  # La Pampa
    21: "R",  # Río Negro
    22: "Z",  # Santa Cruz
    23: "V",  # Tierra del Fuego
}

#: Aliases por nombre (fallback si AFIP no manda idProvincia o manda 0
#: ambiguo). En `l10n_ar` v19 el state CABA se llama
#: "Ciudad Autónoma de Buenos Aires" — AFIP a veces lo escribe sin
#: tildes o como "CAPITAL FEDERAL".
_PROV_NAME_ALIASES = {
    "CIUDAD AUTONOMA BUENOS AIRES": "Ciudad Autónoma de Buenos Aires",
    "CIUDAD AUTONOMA DE BUENOS AIRES": "Ciudad Autónoma de Buenos Aires",
    "CIUDAD AUTÓNOMA DE BUENOS AIRES": "Ciudad Autónoma de Buenos Aires",
    "CAPITAL FEDERAL": "Ciudad Autónoma de Buenos Aires",
    "TIERRA DEL FUEGO ANTARTIDA E ISLAS DEL ATLANTICO SUR": "Tierra del Fuego",
    "TIERRA DEL FUEGO": "Tierra del Fuego",
    "ENTRE RIOS": "Entre Ríos",
    "RIO NEGRO": "Río Negro",
    "NEUQUEN": "Neuquén",
    "TUCUMAN": "Tucumán",
    "CORDOBA": "Córdoba",
}

#: ICP key para activar/desactivar `.title()` sobre name/street/city/street2.
#: AFIP devuelve todo en MAYÚSCULAS — feo en la UI. Default: True.
_ICP_TITLE_CASE = "l10n_ar_padron_query.use_title_case"


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # Helpers CUIT
    # ------------------------------------------------------------------
    @api.model
    def _l10n_ar_clean_cuit(self, value):
        """Devuelve el VAT limpio (sólo dígitos) o ``""`` si no parece CUIT."""
        if not value:
            return ""
        digits = "".join(c for c in str(value) if c.isdigit())
        return digits

    @api.model
    def _l10n_ar_cuit_checksum_ok(self, digits):
        """Valida el dígito verificador de un CUIT/CUIL de 11 dígitos."""
        if not (digits and digits.isdigit() and len(digits) == 11):
            return False
        s = sum(int(digits[i]) * f for i, f in enumerate(_CUIT_CHECKSUM_FACTORS))
        rem = s % 11
        check = 11 - rem
        if check == 11:
            check = 0
        elif check == 10:
            # Caso especial AFIP: si daría 10, el último dígito es 9.
            check = 9
        return check == int(digits[10])

    # ------------------------------------------------------------------
    # Botón
    # ------------------------------------------------------------------
    def action_l10n_ar_padron_query(self):
        """Botón "Consultar ARCA". Recorre los partners y SOBREESCRIBE
        razón social / cond IVA / domicilio con los datos del padrón.

        El botón es explícito (el user lo apretó), así que pisa todo
        — distinto al onchange (auto-fill al salir del campo VAT) que
        es gentle y solo completa si el partner está vacío.
        """
        for rec in self:
            digits = rec._l10n_ar_clean_cuit(rec.vat)
            if not digits or len(digits) != 11:
                raise UserError(_(
                    "El campo Identificación / VAT debe tener 11 dígitos "
                    "(CUIT/CUIL) para consultar el Padrón ARCA."
                ))
            if not rec._l10n_ar_cuit_checksum_ok(digits):
                raise UserError(_(
                    "El CUIT %s tiene dígito verificador inválido."
                ) % digits)
            rec._l10n_ar_padron_apply(
                digits, silent=False, persist=True, force_overwrite=True,
            )
        return True

    # ------------------------------------------------------------------
    # Onchange — auto-consulta al salir del campo VAT
    # ------------------------------------------------------------------
    @api.onchange("vat")
    def _onchange_vat_l10n_ar_padron(self):
        """Si el VAT pasa el checksum CUIT, consulta ARCA y sobreescribe.

        Comportamiento (decidido con Hector 2026-04-27): igual que el
        botón "Consultar ARCA" — al salir del campo trae todo del padrón
        y machaca razón social, domicilio, condición IVA, etc. ARCA es
        la fuente de verdad; si el user quería tipear algo distinto, lo
        edita después del auto-fill.

        Falla en silencio si el WS no está disponible: prefiero no
        molestar con un warning si el server de ARCA está caído. Sí
        muestro warning si el problema es de configuración (cert no
        delegado, environment desconocido, etc.) — eso es accionable.

        El persist=False hace que los cambios queden en el cache del
        onchange (la UI los muestra) pero no se escriban a DB hasta que
        el user salve el form. Si cancela, no se pierde nada.
        """
        if not self.vat:
            return
        digits = self._l10n_ar_clean_cuit(self.vat)
        if not digits or len(digits) != 11:
            return
        if not self._l10n_ar_cuit_checksum_ok(digits):
            return

        # Sanitizar el campo: si el user tipeó "27-32073281-1" o
        # "27.32073281.1", normalizamos a sólo los 11 dígitos. Solo
        # cuando es un CUIT válido (DV OK) — no pisamos VATs extranjeros.
        if self.vat != digits:
            self.vat = digits

        try:
            # force_overwrite=True igual que el botón — ARCA siempre
            # sobreescribe. persist=False para que solo cambie el cache
            # del form sin escribir a DB hasta el save.
            self._l10n_ar_padron_apply(
                digits, silent=True, persist=False, force_overwrite=True,
            )
        except UserError as e:
            # Errores de configuración → sí los mostramos.
            return {"warning": {
                "title": _("Padrón AFIP — configuración"),
                "message": str(e),
            }}
        except Exception as e:
            _logger.warning("Padrón onchange falló silenciosamente: %s", e)

    # ------------------------------------------------------------------
    # Núcleo
    # ------------------------------------------------------------------
    def _l10n_ar_padron_apply(self, digits, silent, persist, force_overwrite=False):
        """Llama al WS Padrón y aplica los datos al partner.

        :param digits: CUIT/CUIL ya validado (11 dígitos sin guiones).
        :param silent: si True, errores de transporte se relanzan como
            ``UserError`` solo si son de configuración; los demás se
            loggean. Si False (botón manual), todo error se relanza
            como ``UserError`` para que el user lo vea.
        :param persist: si True, hace ``write`` (persistencia DB). Si
            False (onchange), sólo asigna ``self.field = value`` para
            que Odoo refleje los cambios en el form sin guardar.
        :param force_overwrite: si True (botón explícito), sobreescribe
            todos los campos relevantes con los datos del padrón aunque
            el partner ya tenga valores cargados. Si False (onchange
            automático), solo completa campos vacíos para no pisar
            ediciones manuales del usuario.
        """
        self.ensure_one()
        company = self.env.company
        environment = company.l10n_ar_afip_ws_environment
        if not environment:
            raise UserError(_(
                "La empresa %s no tiene definido el entorno AFIP. "
                "Configurá Configuración → Compañías → pestaña Argentina."
            ) % company.name)

        # Usamos A5 (`ws_sr_constancia_inscripcion`) por defecto: trae
        # responsabilidad IVA + impuestos + actividades. A13 es la
        # versión liviana que solo trae metadata mínima — quedó como
        # opción en `urls.py` por si algún caller la quiere usar.
        conn = self.env["l10n_ar.afip.ws.connection"]._get_or_create(
            company, "ws_sr_constancia_inscripcion", environment,
        )
        try:
            auth = conn.get_auth()
        except UserError:
            raise
        except Exception as e:
            msg = _("No pude obtener TA WSAA para Padrón: %s") % e
            if silent:
                _logger.warning(msg)
                return
            raise UserError(msg)

        tr = transport_lib.CapturingTransport(
            session=transport_lib.build_afip_session(),
            timeout=30,
        )
        try:
            persona = padron_lib.get_persona(
                auth=auth, id_persona=int(digits),
                environment=environment, transport=tr,
            )
        except ws_errors.WsfeError as e:
            # CUIT no encontrado / fault SOAP — si es manual, mostrar.
            msg = _("Padrón AFIP: %s") % e
            if silent:
                _logger.info(msg)
                return
            raise UserError(msg)
        except Exception as e:
            msg = _("Padrón AFIP — error de red: %s") % e
            if silent:
                _logger.warning(msg)
                return
            raise UserError(msg)

        if not persona:
            if silent:
                return
            raise UserError(_(
                "AFIP no devolvió datos para el CUIT %s."
            ) % digits)

        vals = self._l10n_ar_padron_to_partner_vals(
            digits, persona, force_overwrite=force_overwrite,
        )
        if not vals:
            return

        if persist:
            self.write(vals)
        else:
            for f, v in vals.items():
                self[f] = v
        _logger.info(
            "Padrón AFIP aplicado a partner=%s cuit=%s campos=%s",
            self.id, digits, sorted(vals.keys()),
        )

    @api.model
    def _l10n_ar_padron_use_title_case(self):
        """Lee el ICP y devuelve True/False. Default True."""
        v = self.env["ir.config_parameter"].sudo().get_param(
            _ICP_TITLE_CASE, default="True",
        )
        return str(v).strip().lower() in ("1", "true", "yes", "si", "sí", "y", "t")

    @api.model
    def _l10n_ar_padron_titlecase(self, value):
        """`'AV. SAN MARTIN 123'` → `'Av. San Martin 123'` si está activado."""
        if not value:
            return value
        if not self._l10n_ar_padron_use_title_case():
            return value
        return str(value).strip().title()

    def _l10n_ar_padron_to_partner_vals(self, digits, persona, force_overwrite=False):
        """Mapea el dict del WS Padrón a `vals` para `res.partner.write()`.

        Política según ``force_overwrite``:

        * **True** (botón "Consultar ARCA" — el user lo apretó explícitamente):
          sobreescribe TODOS los campos del padrón aunque el partner ya
          tenga valores cargados.
        * **False** (onchange automático al salir del campo VAT):
          gentle, solo completa campos vacíos.

        En ambos casos:
        * VAT se normaliza (sólo dígitos).
        * Si el VAT pasa la validación de checksum CUIT, el
          ``l10n_latam_identification_type_id`` se fuerza a CUIT
          (l10n_ar_afip_code='80'), aunque el padrón devuelva otra cosa
          o no devuelva nada — porque la regla "VAT con DV válido = CUIT"
          es independiente del WS.
        """
        vals = {}

        def _should_set(field_name):
            """True si hay que setear el field — overwrite o vacío."""
            if force_overwrite:
                return True
            return not self[field_name]

        # ---- nombre / razón social ------------------------------------
        if persona.get("razon_social"):
            display = persona["razon_social"]
        elif persona.get("apellido") or persona.get("nombre"):
            ape = persona.get("apellido") or ""
            nom = persona.get("nombre") or ""
            display = ("%s %s" % (ape, nom)).strip()
        else:
            display = None
        if display:
            new_name = self._l10n_ar_padron_titlecase(display)
            # Caso onchange: solo si name vacío o == digits (placeholder).
            # Caso botón: pisa siempre.
            if force_overwrite or not self.name or self.name == digits:
                if self.name != new_name:
                    vals["name"] = new_name

        # ---- VAT ------------------------------------------------------
        if self.vat != digits:
            vals["vat"] = digits

        # ---- identification type -------------------------------------
        # 1) Si el VAT pasa el checksum CUIT, forzar a CUIT (código 80).
        #    Esto aplica SIEMPRE — la regla "DV válido = CUIT" es
        #    independiente del padrón. Hector lo pidió 2026-04-27.
        target_afip_code = None
        if self._l10n_ar_cuit_checksum_ok(digits):
            target_afip_code = "80"
        else:
            # Fallback al `tipo_clave` del padrón si no es CUIT.
            target_afip_code = _AFIP_CODE_BY_TIPO_CLAVE.get(
                (persona.get("tipo_clave") or "").upper()
            )
        if target_afip_code:
            id_type = self.env["l10n_latam.identification.type"].search([
                ("l10n_ar_afip_code", "=", target_afip_code),
            ], limit=1)
            if id_type and self.l10n_latam_identification_type_id != id_type:
                vals["l10n_latam_identification_type_id"] = id_type.id

        # ---- responsibility IVA --------------------------------------
        resp_code = persona.get("categoria_iva_codigo")
        if resp_code:
            resp = self.env["l10n_ar.afip.responsibility.type"].search([
                ("code", "=", resp_code),
            ], limit=1)
            if resp and self.l10n_ar_afip_responsibility_type_id != resp:
                # Solo overwrite si force=True; en onchange respeto lo cargado.
                if force_overwrite or not self.l10n_ar_afip_responsibility_type_id:
                    vals["l10n_ar_afip_responsibility_type_id"] = resp.id

        # ---- País: forzar AR para CUIT/CUIL --------------------------
        ar = self.env.ref("base.ar", raise_if_not_found=False)
        if ar and (force_overwrite or not self.country_id):
            if self.country_id != ar:
                vals["country_id"] = ar.id

        # ---- domicilio fiscal ----------------------------------------
        dom = persona.get("domicilio_fiscal") or {}
        # street: AFIP devuelve `calle` y `numero` separados, pero a veces
        # `calle` ya viene con el número al final ("DE LOS INCAS AV. 4030"
        # + numero=4030). Concateno solo si no se repite.
        calle = (str(dom.get("calle") or "")).strip()
        numero = dom.get("numero")
        numero_str = str(numero).strip() if numero not in (None, "", 0) else ""
        if numero_str and numero_str not in calle.split():
            street = ("%s %s" % (calle, numero_str)).strip() if calle else numero_str
        else:
            street = calle
        if street and _should_set("street"):
            vals["street"] = self._l10n_ar_padron_titlecase(street)
        if dom.get("datoAdicional") and _should_set("street2"):
            vals["street2"] = self._l10n_ar_padron_titlecase(
                str(dom["datoAdicional"]).strip()
            )
        if dom.get("localidad") and _should_set("city"):
            vals["city"] = self._l10n_ar_padron_titlecase(
                str(dom["localidad"]).strip()
            )
        if dom.get("codPostal") and _should_set("zip"):
            vals["zip"] = str(dom["codPostal"]).strip()

        # state: el WS da `idProvincia` (int) y `descripcionProvincia`.
        # En `l10n_ar` v19 el state.code es la letra ISO (A, B, C, ...).
        # Mapeamos idProvincia → letra y, si AFIP también manda
        # `descripcionProvincia` (1..1 según manual A13), resolvemos por
        # nombre como cross-check: ante discrepancia gana la descripción
        # (el texto es inequívoco; el id depende de esta tabla local).
        if ar and (force_overwrite or not self.state_id):
            State = self.env["res.country.state"]
            prov_id = dom.get("idProvincia")
            try:
                prov_id_int = int(prov_id) if prov_id is not None else None
            except (TypeError, ValueError):
                prov_id_int = None
            letter = (
                _AFIP_IDPROV_TO_STATE_CODE.get(prov_id_int)
                if prov_id_int is not None else None
            )
            state_by_id = State.browse()
            if letter:
                state_by_id = State.search([
                    ("country_id", "=", ar.id),
                    ("code", "=", letter),
                ], limit=1)
            state_by_name = State.browse()
            if dom.get("descripcionProvincia"):
                desc = str(dom["descripcionProvincia"]).strip()
                # 1) alias literal AFIP→l10n_ar
                alias = _PROV_NAME_ALIASES.get(desc.upper())
                if alias:
                    state_by_name = State.search([
                        ("country_id", "=", ar.id),
                        ("name", "=", alias),
                    ], limit=1)
                # 2) match insensible
                if not state_by_name:
                    state_by_name = State.search([
                        ("country_id", "=", ar.id),
                        ("name", "=ilike", desc),
                    ], limit=1)
            state = state_by_id or state_by_name
            if state_by_id and state_by_name and state_by_id != state_by_name:
                _logger.warning(
                    "Padrón AFIP: discrepancia provincia para CUIT %s: "
                    "idProvincia=%s → %s pero descripcionProvincia=%r → %s. "
                    "Se usa la descripción; revisar tabla "
                    "_AFIP_IDPROV_TO_STATE_CODE.",
                    self.vat, prov_id, state_by_id.name,
                    dom.get("descripcionProvincia"), state_by_name.name,
                )
                state = state_by_name
            if state:
                vals["state_id"] = state.id

        # ---- tipo (compañía vs persona) ------------------------------
        # tipoPersona = "JURIDICA" | "FISICA". Mapeamos a is_company.
        tipo = (persona.get("tipo_persona") or "").upper()
        if tipo == "JURIDICA":
            if force_overwrite or not self.is_company:
                if not self.is_company:
                    vals["is_company"] = True
        elif tipo == "FISICA" and force_overwrite:
            # Solo en el botón pisamos a False — el onchange respeta lo
            # que el usuario haya elegido.
            if self.is_company:
                vals["is_company"] = False

        return vals
