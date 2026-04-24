# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Pos Payment inheritance to store Yavin issuer."""

from odoo import fields, models


class PosPayment(models.Model):
    """Inherit Pos Payment to store Yavin issuer information."""
    # pylint: disable=too-few-public-methods
    _inherit = "pos.payment"

    yavin_issuer = fields.Char(
        help="Issuer of the payment card (e.g., Edenred, Swile, etc.)",
    )

    def _export_for_ui(self, payment):
        res = super()._export_for_ui(payment)
        res['yavin_issuer'] = payment.yavin_issuer
        return res
