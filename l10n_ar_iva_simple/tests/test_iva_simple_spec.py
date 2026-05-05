# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Tests del spec IVA Simple — cálculo de IVA, mappings ARCA, etc.

Lib pura — no necesita server Odoo. Se ejecuta con Odoo TransactionCase
pero sin tocar la DB.
"""
from odoo.tests.common import TransactionCase

from ..lib import iva_simple as spec


class TestIvaSimpleSpec(TransactionCase):
    """Verifica los mappings y cálculos de la spec ARCA IVA Simple."""

    def test_vat_amount_21pct(self):
        """IVA 21% sobre $1.000 = $210.00."""
        self.assertEqual(spec.vat_amount(1000.0, "5"), 210.0)

    def test_vat_amount_10_5pct(self):
        """IVA 10.5% sobre $1.000 = $105.00."""
        self.assertEqual(spec.vat_amount(1000.0, "4"), 105.0)

    def test_vat_amount_27pct(self):
        """IVA 27% sobre $1.000 = $270.00."""
        self.assertEqual(spec.vat_amount(1000.0, "6"), 270.0)

    def test_vat_amount_5pct(self):
        """IVA 5% sobre $1.000 = $50.00."""
        self.assertEqual(spec.vat_amount(1000.0, "8"), 50.0)

    def test_vat_amount_0pct_exempt(self):
        """Códigos 0/1/2/3 (no gravado/exento) → IVA = 0."""
        for code in ("0", "1", "2", "3"):
            self.assertEqual(spec.vat_amount(1000.0, code), 0.0,
                             "vat_amount('%s') debería ser 0" % code)

    def test_vat_amount_rounding(self):
        """Redondeo HALF_UP a 2 decimales."""
        # 100.005 * 0.21 = 21.00105 → round 21.00
        self.assertEqual(spec.vat_amount(100.005, "5"), 21.00)
        # 50.50 * 0.21 = 10.605 → round 10.61 (HALF_UP)
        self.assertEqual(spec.vat_amount(50.50, "5"), 10.61)

    def test_map_sale_operation_type_exenta(self):
        """vat_code='0' (exenta) → tipo de operación EXENTA."""
        self.assertEqual(
            spec.map_sale_operation_type("0", False),
            spec.OP_TYPE_EXENTA,
        )

    def test_map_sale_operation_type_fixed_asset(self):
        """vat_code IVA con tag 'fixed_asset' → tipo distinto."""
        # Si hay tag fixed_asset, debe identificar la operación como bien de uso
        op = spec.map_sale_operation_type("5", True)
        self.assertNotEqual(op, spec.OP_TYPE_EXENTA)

    def test_map_responsibility_to_buyer_type_known_codes(self):
        """Códigos AFIP de responsabilidad mapean correctamente."""
        # 1=RI, 4=Exento, 5=CF, 6=Monotributo
        for resp_code in ("1", "4", "5", "6"):
            buyer = spec.map_responsibility_to_buyer_type(resp_code)
            self.assertIsNotNone(buyer,
                                 "responsability_code=%s debería mapear" % resp_code)

    def test_map_responsibility_to_buyer_type_unknown(self):
        """Código desconocido → fallback razonable, no crash."""
        # No debe levantar excepción
        spec.map_responsibility_to_buyer_type("999")
        spec.map_responsibility_to_buyer_type(None)
        spec.map_responsibility_to_buyer_type("")

    def test_map_purchase_concept_service(self):
        """product_type='service' → concepto Servicio."""
        concept = spec.map_purchase_concept("service", False, False)
        self.assertIsNotNone(concept)

    def test_map_purchase_concept_fixed_asset(self):
        """tag 'fixed_asset' tiene prioridad sobre product_type."""
        concept_with_fa = spec.map_purchase_concept("consu", True, False)
        concept_without_fa = spec.map_purchase_concept("consu", False, False)
        self.assertNotEqual(concept_with_fa, concept_without_fa,
                            "El tag fixed_asset debe cambiar el concepto")

    def test_map_purchase_concept_leases_priority(self):
        """tag 'leases' tiene prioridad sobre 'fixed_asset'."""
        concept_leases = spec.map_purchase_concept("consu", True, True)
        concept_fa = spec.map_purchase_concept("consu", True, False)
        self.assertNotEqual(concept_leases, concept_fa,
                            "El tag leases debe priorizar sobre fixed_asset")
