# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Extensiones al modelo `certificate.certificate` de Community.

El módulo `certificate` de Community 19 expone `_sign(message)` que firma
raw (SHA-256 + padding). AFIP pide un sobre **CMS/PKCS#7 signed-data**
con el contenido embebido — una estructura ASN.1 que incluye el
certificado del firmante. Para eso extendemos el modelo y agregamos:

- `_l10n_ar_pkcs7_sign(message)`: envuelve `message` en CMS y devuelve
  los bytes DER del sobre firmado.
- `_l10n_ar_create_csr(subject_dict)`: genera una CSR (Certificate Signing
  Request) lista para subir a WSASS o al portal AFIP. Útil cuando el
  usuario no tiene acceso fácil a openssl en su máquina.

Diseño:
- **No copiamos** el código de enterprise. Lo de enterprise usa
  `pkcs7.PKCS7SignatureBuilder` de la librería `cryptography`; nosotros
  usamos la misma API porque es la única vía canónica en Python — el
  "código" no es original de nadie, es el uso de la librería. Lo que
  sí es nuestro es el wrapper, el manejo de errores y los hints.
"""
import base64
import logging

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class Certificate(models.Model):
    _inherit = "certificate.certificate"

    def _l10n_ar_pkcs7_sign(self, message):
        """Firma `message` (bytes) con CMS/PKCS#7 signed-data.

        :param message: bytes a firmar (el XML del LoginTicketRequest).
        :return: bytes DER del sobre CMS firmado. Es lo que AFIP espera en
                 `loginCms(in0=base64(esto))`.
        :raises UserError: si el certificado no está cargado/vigente o no
                           tiene private key asociada.
        """
        self.ensure_one()
        if not self.private_key_id:
            raise UserError(_(
                "El certificado %s no tiene una clave privada asociada. "
                "No se puede firmar contra AFIP.",
            ) % self.name)

        # `certificate.certificate.pem_certificate` es un `fields.Binary`
        # cuyo valor real es **base64 del PEM**. Dos consecuencias:
        #
        # 1. Por default el ORM devuelve el tamaño (int) en lugar del
        #    contenido — hay que leer con `with_context(bin_size=False)`.
        # 2. El contenido es base64 que hay que decodear ANTES de pasarlo
        #    a `load_pem_x509_certificate`, que espera el PEM crudo.
        #
        # El mismo patrón usa el propio módulo `certificate` en su
        # `_get_der_certificate_bytes` / `_get_fingerprint_bytes`.
        try:
            pem_b64 = self.with_context(bin_size=False).pem_certificate
            if not pem_b64:
                raise ValueError("pem_certificate vacío (¿cert no cargado?)")
            cert_obj = x509.load_pem_x509_certificate(base64.b64decode(pem_b64))
        except Exception as e:
            raise UserError(_(
                "No pude cargar el certificado %s: %s"
            ) % (self.name, e))

        # La private key sigue el mismo patrón: `pem_key` es base64 del PEM
        # y hay que leerlo con `bin_size=False` + `b64decode`.
        try:
            key_rec = self.private_key_id.with_context(bin_size=False)
            pem_key_b64 = key_rec.pem_key
            if not pem_key_b64:
                raise ValueError("pem_key vacío (¿clave no cargada o con password mal?)")
            key_obj = serialization.load_pem_private_key(
                base64.b64decode(pem_key_b64),
                password=None,
            )
        except Exception as e:
            raise UserError(_(
                "No pude desencriptar la clave privada de %s: %s"
            ) % (self.name, e))

        try:
            cms = (
                pkcs7.PKCS7SignatureBuilder()
                .set_data(message)
                .add_signer(cert_obj, key_obj, hashes.SHA256())
                .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
            )
        except Exception as e:
            raise UserError(_(
                "Falla al firmar CMS con %s: %s"
            ) % (self.name, e))
        return cms

    @api.model
    def _l10n_ar_create_csr(self, common_name, organization, cuit, country="AR"):
        """Genera una CSR RSA-2048 lista para WSASS.

        :param common_name: CN del certificado (alias, ej. 'odoo-edi-homolog').
        :param organization: razón social.
        :param cuit: 11 dígitos como string.
        :param country: default 'AR'.
        :return: dict con:
            - private_key_pem (bytes): clave privada en PEM sin passphrase.
            - csr_pem (bytes): CSR en PEM lista para pegar en WSASS.

        No guarda nada en la DB — el caller decide qué hacer con los bytes
        (típicamente: persistir la private_key_id en `certificate.key` y
        mostrar la CSR al usuario para que la copie a WSASS).
        """
        from cryptography.hazmat.primitives.asymmetric import rsa

        if not (isinstance(cuit, str) and len(cuit) == 11 and cuit.isdigit()):
            raise UserError(_(
                "El CUIT para la CSR debe ser un string de 11 dígitos sin guiones."
            ))

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            # AFIP busca el CUIT en serialNumber con formato "CUIT <11 dígitos>".
            x509.NameAttribute(NameOID.SERIAL_NUMBER, "CUIT %s" % cuit),
        ])
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(subject)
            .sign(key, hashes.SHA256())
        )
        return {
            "private_key_pem": key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            "csr_pem": csr.public_bytes(serialization.Encoding.PEM),
        }
