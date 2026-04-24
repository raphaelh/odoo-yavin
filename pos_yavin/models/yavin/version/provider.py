# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Version provider for Odoo Point of Sale module."""

import logging

import odoo.modules

logger = logging.getLogger(__name__)


class YavinVersionProvider:
    """Provider for Odoo Point of Sale module version."""
    # pylint: disable=too-few-public-methods

    @staticmethod
    def get_pos_version():
        """
        Get the Odoo Point of Sale module version.

        :return: Version string (default: "17.0.1.0.0")
        """
        try:
            pos_manifest = odoo.modules.get_manifest("point_of_sale")
            return pos_manifest.get("version", "17.0.1.0.0")
        except (ImportError, KeyError, AttributeError) as e:
            logger.warning("Could not get point_of_sale version: %s", e)
            return "17.0.1.0.0"
