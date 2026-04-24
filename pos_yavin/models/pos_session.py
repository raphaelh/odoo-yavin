# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Pos Session inheritance for Yavin integration."""

from odoo import models

from .yavin import YavinCardInfoFormatter


class PosSession(models.Model):
    """Inherit Pos Session to handle Yavin specific parameters."""
    # pylint: disable=too-few-public-methods

    _inherit = "pos.session"

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result["search_params"]["fields"].append("yavin_ip_address")
        result["search_params"]["fields"].append("yavin_connection_mode")
        result["search_params"]["fields"].append("yavin_effective_connection_mode")
        result["search_params"]["fields"].append("yavin_display_tip")
        result["search_params"]["fields"].append("yavin_timeout_ms")
        result["search_params"]["fields"].append("yavin_reversal_timeout_ms")
        return result

    def _get_split_receivable_vals(self, payment, amount, amount_converted):
        """Override to include card_type and issuer in accounting line name"""
        result = super()._get_split_receivable_vals(payment, amount, amount_converted)

        # Format consistent with pos_online_payment: Session - Method (Scheme / Issuer)
        card_info = YavinCardInfoFormatter.build_card_info_string(payment)
        if card_info:
            result['name'] = f"{self.name} - {payment.payment_method_id.name} ({card_info})"

        return result

    def _get_combine_receivable_vals(self, payment_method, amount, amount_converted):
        """Override to include card_type and issuer info for combined payments"""
        result = super()._get_combine_receivable_vals(payment_method, amount, amount_converted)

        if payment_method.use_payment_terminal == 'yavin':
            payments = self.order_ids.payment_ids.filtered(
                lambda p: p.payment_method_id == payment_method and p.card_type
            )
            if payments:
                # Build a list of all unique scheme/issuer combinations
                unique_card_infos = set()
                for payment in payments:
                    card_info = YavinCardInfoFormatter.build_card_info_string(payment)
                    if card_info:
                        unique_card_infos.add(card_info)

                if unique_card_infos:
                    # Sort to have a consistent order
                    sorted_card_infos = sorted(unique_card_infos)
                    # Consistent format: Session - Method (Types/Issuers)
                    card_infos_str = ' / '.join(sorted_card_infos)
                    result['name'] = f"{self.name} - {payment_method.name} ({card_infos_str})"

        return result
