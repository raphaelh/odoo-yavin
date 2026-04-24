# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Pos Order inheritance for Yavin integration."""

from odoo import models


class PosOrder(models.Model):
    """Inherit Pos Order to handle Yavin payment fields."""
    # pylint: disable=too-few-public-methods
    _inherit = "pos.order"

    def _payment_fields(self, order, ui_paymentline):
        fields = super()._payment_fields(order, ui_paymentline)
        fields['yavin_issuer'] = ui_paymentline.get('yavin_issuer')
        return fields
