# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Amount converter for Yavin payment terminal."""


class YavinAmountConverter:
    """Converter for payment amounts to/from cents."""

    @staticmethod
    def convert_amount_to_cents(amount, currency):
        """
        Convert amount to cents based on currency decimal places.

        :param amount: Amount to convert (can be negative)
        :param currency: Currency record with decimal_places field
        :return: Amount in cents (positive integer)
        """
        # Ensure amount is positive
        if amount < 0:
            amount_positive = amount * -1
        else:
            amount_positive = amount

        # Convert to cents
        if currency.decimal_places:
            amount_cent = int(round(amount_positive * (10 ** currency.decimal_places)))
        else:
            amount_cent = int(round(amount_positive))

        return amount_cent

    @staticmethod
    def convert_cents_to_amount(amount_cent, currency):
        """
        Convert amount from cents to monetary unit based on currency decimal places.

        :param amount_cent: Amount in cents
        :param currency: Currency record with decimal_places field
        :return: Amount in monetary unit
        """
        if amount_cent and currency.decimal_places:
            amount = amount_cent / (10 ** currency.decimal_places)
        else:
            amount = 0

        return amount
