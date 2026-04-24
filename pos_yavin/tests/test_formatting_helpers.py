# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin amount and card formatting helpers."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,too-few-public-methods

from types import SimpleNamespace

from odoo.tests.common import TransactionCase
from odoo.addons.pos_yavin.models.yavin.formatting.amount_converter import (
    YavinAmountConverter,
)
from odoo.addons.pos_yavin.models.yavin.formatting.card_info_formatter import (
    YavinCardInfoFormatter,
)


class TestYavinAmountConverter(TransactionCase):
    """Tests for :class:`YavinAmountConverter`."""

    def test_convert_amount_to_cents_uses_absolute_value(self):
        currency = SimpleNamespace(decimal_places=2)

        self.assertEqual(YavinAmountConverter.convert_amount_to_cents(-10.25, currency), 1025)

    def test_convert_amount_to_cents_rounds_to_currency_precision(self):
        currency = SimpleNamespace(decimal_places=2)

        self.assertEqual(YavinAmountConverter.convert_amount_to_cents(10.235, currency), 1024)

    def test_convert_amount_to_cents_supports_zero_decimal_currency(self):
        currency = SimpleNamespace(decimal_places=0)

        self.assertEqual(YavinAmountConverter.convert_amount_to_cents(10.6, currency), 11)

    def test_convert_cents_to_amount_supports_zero_and_decimal_currency(self):
        decimal_currency = SimpleNamespace(decimal_places=2)
        zero_decimal_currency = SimpleNamespace(decimal_places=0)

        self.assertEqual(YavinAmountConverter.convert_cents_to_amount(250, decimal_currency), 2.5)
        self.assertEqual(YavinAmountConverter.convert_cents_to_amount(0, decimal_currency), 0)
        self.assertEqual(YavinAmountConverter.convert_cents_to_amount(12, zero_decimal_currency), 0)


class TestYavinCardInfoFormatter(TransactionCase):
    """Tests for :class:`YavinCardInfoFormatter`."""

    def test_get_scheme_display_name_uses_mapping_and_fallback(self):
        self.assertEqual(YavinCardInfoFormatter.get_scheme_display_name("visa"), "Visa")
        self.assertEqual(YavinCardInfoFormatter.get_scheme_display_name("VISA"), "Visa")
        self.assertEqual(YavinCardInfoFormatter.get_scheme_display_name("custom"), "custom")
        self.assertIsNone(YavinCardInfoFormatter.get_scheme_display_name(""))

    def test_get_issuer_display_name_uses_mapping_and_fallback(self):
        self.assertEqual(YavinCardInfoFormatter.get_issuer_display_name("swile"), "Swile")
        self.assertEqual(YavinCardInfoFormatter.get_issuer_display_name("SWILE"), "Swile")
        self.assertEqual(YavinCardInfoFormatter.get_issuer_display_name("custom"), "custom")
        self.assertIsNone(YavinCardInfoFormatter.get_issuer_display_name(None))

    def test_build_card_info_string_combines_scheme_and_issuer(self):
        payment = SimpleNamespace(card_type="visa", yavin_issuer="swile")

        self.assertEqual(
            YavinCardInfoFormatter.build_card_info_string(payment),
            "Visa / Swile",
        )

    def test_build_card_info_string_returns_single_part_or_none(self):
        scheme_only = SimpleNamespace(card_type="cb", yavin_issuer=None)
        empty_payment = SimpleNamespace(card_type=None, yavin_issuer=None)

        self.assertEqual(YavinCardInfoFormatter.build_card_info_string(scheme_only), "CB")
        self.assertIsNone(YavinCardInfoFormatter.build_card_info_string(empty_payment))

    def test_build_card_info_string_handles_missing_issuer_attribute(self):
        payment = SimpleNamespace(card_type="mastercard")
        self.assertEqual(YavinCardInfoFormatter.build_card_info_string(payment), "Mastercard")

    def test_build_card_info_string_with_issuer_only(self):
        payment = SimpleNamespace(card_type=None, yavin_issuer="edenred")
        self.assertEqual(YavinCardInfoFormatter.build_card_info_string(payment), "Edenred")
