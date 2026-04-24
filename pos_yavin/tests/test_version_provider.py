# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for POS version provider used in Yavin payloads."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,too-few-public-methods

from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.addons.pos_yavin.models.yavin.version.provider import (
    YavinVersionProvider,
)


class TestYavinVersionProvider(TransactionCase):
    """Tests for :class:`YavinVersionProvider`."""

    def test_get_pos_version_from_manifest(self):
        with patch("odoo.modules.get_manifest", return_value={"version": "17.0.custom"}):
            self.assertEqual(YavinVersionProvider.get_pos_version(), "17.0.custom")

    def test_get_pos_version_falls_back_on_manifest_error(self):
        with patch("odoo.modules.get_manifest", side_effect=AttributeError("missing")):
            self.assertEqual(YavinVersionProvider.get_pos_version(), "17.0.1.0.0")

    def test_get_pos_version_falls_back_on_import_error(self):
        with patch("odoo.modules.get_manifest", side_effect=ImportError("missing")):
            self.assertEqual(YavinVersionProvider.get_pos_version(), "17.0.1.0.0")

    def test_get_pos_version_falls_back_on_key_error(self):
        with patch("odoo.modules.get_manifest", side_effect=KeyError("missing")):
            self.assertEqual(YavinVersionProvider.get_pos_version(), "17.0.1.0.0")
