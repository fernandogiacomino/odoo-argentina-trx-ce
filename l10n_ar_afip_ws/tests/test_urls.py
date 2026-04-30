# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Tests de la tabla de URLs — sin red, sin Odoo, ejecutables con pytest puro.

Estos tests existen para evitar errores tontos tipo "pusiste la URL de
homologación en producción" (bug clásico en integraciones AFIP).
"""
import unittest

from ..lib import urls


class TestUrls(unittest.TestCase):

    def test_wsaa_testing_vs_production(self):
        """WSAA homologación debe tener 'homo' en el dominio, producción no."""
        t = urls.get_wsdl_url("wsaa", "testing")
        p = urls.get_wsdl_url("wsaa", "production")
        self.assertIn("homo", t)
        self.assertNotIn("homo", p)
        self.assertTrue(t.endswith("?WSDL"))
        self.assertTrue(p.endswith("?WSDL"))

    def test_wsfe_urls_are_different_per_env(self):
        t = urls.get_wsdl_url("wsfe", "testing")
        p = urls.get_wsdl_url("wsfe", "production")
        self.assertNotEqual(t, p)

    def test_unknown_ws_raises(self):
        with self.assertRaises(ValueError):
            urls.get_wsdl_url("wsnonexistent", "testing")

    def test_unknown_environment_raises(self):
        with self.assertRaises(ValueError):
            urls.get_wsdl_url("wsfe", "sandbox")

    def test_login_service_name_wsaa_is_none(self):
        # WSAA no se autentica contra sí mismo; get_login_service_name debe explotar.
        with self.assertRaises(ValueError):
            urls.get_login_service_name("wsaa", "testing")

    def test_login_service_name_wsfe(self):
        self.assertEqual(urls.get_login_service_name("wsfe", "testing"), "wsfe")
        self.assertEqual(urls.get_login_service_name("wsfe", "production"), "wsfe")


if __name__ == "__main__":
    unittest.main()
