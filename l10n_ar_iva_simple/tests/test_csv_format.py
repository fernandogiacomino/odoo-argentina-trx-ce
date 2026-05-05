# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Tests del formateador de CSV (encoding latin-1, separador ;, decimales coma)."""
from odoo.tests.common import TransactionCase

from ..lib import csv_format as cf


class TestCsvFormat(TransactionCase):
    """Verifica que el CSV cumpla con el spec ARCA: latin-1 + `;` + `,`."""

    def test_encoding_is_latin1(self):
        """El CSV se escribe en Latin-1 (ISO-8859-1), NO UTF-8.

        ARCA rechaza UTF-8 cuando hay tildes o ñ.
        """
        rows = [{"col": "Niño Pérez"}]
        content = cf.rows_to_csv_bytes(["col"], rows)
        # Debe poder decodificarse Latin-1
        decoded = content.decode("iso-8859-1")
        self.assertIn("Niño Pérez", decoded)
        # NO debe ser UTF-8 válido si tiene tildes (porque Latin-1 ñ = 0xF1)
        # En UTF-8, ñ sería 0xC3 0xB1 (2 bytes). Verificamos que es 1 byte.
        self.assertEqual(content.count(b"\xf1"), 1, "ñ debe ir como Latin-1 0xF1")

    def test_separator_is_semicolon(self):
        """Columnas separadas por `;` (no `,`)."""
        rows = [{"a": "1", "b": "2"}]
        content = cf.rows_to_csv_bytes(["a", "b"], rows).decode("iso-8859-1")
        # La línea de datos debe tener `;`
        data_line = content.splitlines()[1]  # 0=header, 1=datos
        self.assertIn(";", data_line)
        # Y ningún `,` que separe columnas (los decimales sí pueden tener)
        # Para este test no hay decimales

    def test_decimal_separator_is_comma(self):
        """Decimales con coma: `1234,56` (no `1234.56`)."""
        rows = [{"importe": 1234.56}]
        content = cf.rows_to_csv_bytes(["importe"], rows).decode("iso-8859-1")
        self.assertIn("1234,56", content)
        self.assertNotIn("1234.56", content)

    def test_decimal_two_digits(self):
        """Importes con 2 decimales fijos."""
        rows = [{"a": 100.0, "b": 100.5, "c": 100.999}]
        content = cf.rows_to_csv_bytes(["a", "b", "c"], rows).decode("iso-8859-1")
        self.assertIn("100,00", content)
        self.assertIn("100,50", content)
        # 100.999 → round HALF_UP → 101,00
        self.assertIn("101,00", content)

    def test_negative_to_abs(self):
        """Importes negativos se escriben como ABS (positivos)."""
        rows = [{"importe": -1234.56}]
        content = cf.rows_to_csv_bytes(["importe"], rows).decode("iso-8859-1")
        self.assertIn("1234,56", content)
        # No debe haber signo `-`
        self.assertNotIn("-1234", content)

    def test_empty_string_for_none(self):
        """Valores None / "" se escriben como string vacío."""
        rows = [{"a": None, "b": ""}]
        content = cf.rows_to_csv_bytes(["a", "b"], rows).decode("iso-8859-1")
        # Esperamos algo como `;` (sin valor entre separadores)
        data_line = content.splitlines()[1]
        # Con 2 columnas y ambas vacías, la línea es ";"
        self.assertEqual(data_line, ";")

    def test_header_row(self):
        """Primera línea del CSV son los headers."""
        rows = [{"a": "1"}]
        content = cf.rows_to_csv_bytes(["columna_a"], rows).decode("iso-8859-1")
        first_line = content.splitlines()[0]
        self.assertEqual(first_line, "columna_a")

    def test_line_terminator_lf(self):
        """Líneas terminadas con LF (no CRLF)."""
        rows = [{"a": "1"}, {"a": "2"}]
        content = cf.rows_to_csv_bytes(["a"], rows)
        # CRLF (\r\n) NO debe aparecer
        self.assertNotIn(b"\r\n", content)
        # LF sí
        self.assertIn(b"\n", content)
