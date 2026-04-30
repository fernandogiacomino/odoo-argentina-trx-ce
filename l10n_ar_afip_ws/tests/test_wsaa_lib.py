# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Tests de la capa pura `wsaa.py` — sin red, sin Odoo.

Validamos:
- LoginTicketRequest tiene la estructura XML que AFIP espera.
- parse_login_ticket_response extrae token/sign/tiempos correctamente.
- parse_login_ticket_response rompe con mensaje claro si falta un elemento.
"""
import unittest
from datetime import timedelta

from lxml import etree

from ..lib import errors, wsaa


class TestBuildLoginTicketRequest(unittest.TestCase):

    def test_structure(self):
        xml = wsaa.build_login_ticket_request("wsfe")
        root = etree.fromstring(xml)
        self.assertEqual(root.tag, "loginTicketRequest")
        self.assertEqual(root.get("version"), "1.0")
        self.assertIsNotNone(root.find("header/uniqueId"))
        self.assertIsNotNone(root.find("header/generationTime"))
        self.assertIsNotNone(root.find("header/expirationTime"))
        self.assertEqual(root.find("service").text, "wsfe")

    def test_expiration_is_after_generation(self):
        xml = wsaa.build_login_ticket_request("wsfe", ttl_minutes=60)
        root = etree.fromstring(xml)
        gen = root.find("header/generationTime").text
        exp = root.find("header/expirationTime").text
        # parse con fromisoformat — ambos deben tener tz
        from datetime import datetime
        gen_dt = datetime.fromisoformat(gen)
        exp_dt = datetime.fromisoformat(exp)
        self.assertEqual(exp_dt - gen_dt, timedelta(minutes=60))

    def test_unique_id_changes(self):
        xml1 = wsaa.build_login_ticket_request("wsfe")
        xml2 = wsaa.build_login_ticket_request("wsfe")
        u1 = etree.fromstring(xml1).find("header/uniqueId").text
        u2 = etree.fromstring(xml2).find("header/uniqueId").text
        # Podrían coincidir si caen en el mismo ms, pero random 0..999
        # hace que el choque sea muy improbable.
        self.assertNotEqual(u1, u2)


class TestParseLoginTicketResponse(unittest.TestCase):

    def _sample_response(self):
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<loginTicketResponse version="1">
    <header>
        <source>CN=wsaa, O=AFIP, C=AR, SERIALNUMBER=CUIT 33693450239</source>
        <destination>SERIALNUMBER=CUIT 20111111111, CN=test-cn, C=AR</destination>
        <uniqueId>1234</uniqueId>
        <generationTime>2026-04-23T10:00:00.000-03:00</generationTime>
        <expirationTime>2026-04-23T22:00:00.000-03:00</expirationTime>
    </header>
    <credentials>
        <token>PD94bWwgdmVyc2lvbj0iMS4wIj8+...</token>
        <sign>abcd1234==</sign>
    </credentials>
</loginTicketResponse>"""

    def test_happy_path(self):
        parsed = wsaa.parse_login_ticket_response(self._sample_response())
        self.assertEqual(parsed["token"], "PD94bWwgdmVyc2lvbj0iMS4wIj8+...")
        self.assertEqual(parsed["sign"], "abcd1234==")
        self.assertIsNotNone(parsed["generation_time"])
        self.assertIsNotNone(parsed["expiration_time"])
        # 12h de diferencia entre gen y exp
        delta = parsed["expiration_time"] - parsed["generation_time"]
        self.assertEqual(delta, timedelta(hours=12))

    def test_invalid_xml(self):
        with self.assertRaises(errors.WsaaError):
            wsaa.parse_login_ticket_response(b"<not-valid")

    def test_missing_token(self):
        xml = b"""<?xml version="1.0"?><loginTicketResponse version="1">
            <header><generationTime>2026-04-23T10:00:00-03:00</generationTime>
            <expirationTime>2026-04-23T22:00:00-03:00</expirationTime></header>
            <credentials><sign>abc</sign></credentials>
        </loginTicketResponse>"""
        with self.assertRaises(errors.WsaaError):
            wsaa.parse_login_ticket_response(xml)


class TestErrorHints(unittest.TestCase):

    def test_wsaa_known_code_returns_hint(self):
        desc, hint = errors.get_wsaa_hint("certificate.notAuthorized")
        self.assertIsNotNone(hint)

    def test_wsaa_unknown_code_returns_none(self):
        desc, hint = errors.get_wsaa_hint("totally.fake.code")
        self.assertIsNone(desc)
        self.assertIsNone(hint)

    def test_wsfe_int_and_string_code(self):
        desc_int, hint_int = errors.get_wsfe_hint(10015)
        desc_str, hint_str = errors.get_wsfe_hint("10015")
        self.assertEqual(desc_int, desc_str)
        self.assertEqual(hint_int, hint_str)

    def test_afip_ws_error_message_formatting(self):
        e = errors.WsfeError(code=10015, message="CUIT inválida", hint="Verificá el padrón")
        s = str(e)
        self.assertIn("10015", s)
        self.assertIn("CUIT inválida", s)
        self.assertIn("Verificá el padrón", s)


if __name__ == "__main__":
    unittest.main()
