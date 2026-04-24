# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Data extractor for Yavin payment terminal."""

import logging

logger = logging.getLogger(__name__)


class YavinDataExtractor:
    """Extractor for customer and session data."""

    def __init__(self, env):
        """
        Initialize the data extractor.

        :param env: Odoo environment
        """
        self.env = env

    def extract_customer_data(self, partner_id):
        """
        Extract customer data from partner for Yavin API.

        :param partner_id: ID of res.partner (can be False/None)
        :return: Dictionary with customer data (firstName, lastName, email, phone) or None
        """
        if not partner_id:
            return None

        partner = self.env["res.partner"].browse(partner_id)
        if not partner.exists():
            return None

        # Split name into firstName and lastName
        name = partner.name or ""
        name_parts = name.strip().split() if name.strip() else []
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        # Get phone (prefer phone over mobile)
        phone = partner.phone or partner.mobile or ""
        email = partner.email or ""

        # Only create customer_data if at least one field has a value
        if not (first_name or last_name or email or phone):
            return None

        customer_data = {}
        if first_name:
            customer_data["firstName"] = first_name
        if last_name:
            customer_data["lastName"] = last_name
        if email:
            customer_data["email"] = email
        if phone:
            customer_data["phone"] = phone

        return customer_data

    def extract_cashier_name(self, session_id):
        """
        Extract cashier name from POS session.

        :param session_id: ID of pos.session
        :return: Cashier name (string) or empty string
        """
        if not session_id:
            return ""

        session = self.env["pos.session"].browse(session_id)
        if not session.exists():
            logger.warning("POS session %s not found for cashier name extraction", session_id)
            return ""

        user = session.user_id
        if not user or not user.exists():
            logger.warning("No user found in POS session %s", session_id)
            return ""

        return user.name or ""
