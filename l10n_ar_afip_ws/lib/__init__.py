# Part of l10n-ar-edi-community. See LICENSE file for full copyright and licensing details.
"""Capa pura (sin imports de `odoo.`) para los WS de AFIP.

Este subpaquete existe para que la lógica del cliente SOAP/XML pueda
testearse con `pytest` fuera de Odoo — separa el "cómo hablar con AFIP"
del "cómo integrarlo con account.move".
"""
