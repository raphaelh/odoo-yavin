# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Card information formatter for Yavin payment terminal."""

# Mapping of scheme codes to official display names
SCHEME_DISPLAY_NAMES = {
    'cb': 'CB',
    'visa': 'Visa',
    'electron': 'Electron',
    'mastercard': 'Mastercard',
    'maestro': 'Maestro',
    'amex': 'Amex',
    'discover': 'Discover',
    'cup': 'CUP',
    'conecs': 'Conecs',
}

# Mapping of issuer codes to official display names
ISSUER_DISPLAY_NAMES = {
    'edenred': 'Edenred',
    'bimpli': 'Bimpli',
    'updej': 'Updej',
    'sodexo': 'Sodexo',
    'swile': 'Swile',
    'benefiz': 'Benefiz',
    'wiismile': 'Wiismile',
}


class YavinCardInfoFormatter:
    """Formatter for card information (scheme and issuer)."""

    @staticmethod
    def get_scheme_display_name(scheme):
        """
        Convert scheme code to official display name.

        :param scheme: Scheme code (e.g., 'cb', 'visa')
        :return: Display name or original scheme if not found
        """
        if not scheme:
            return None
        return SCHEME_DISPLAY_NAMES.get(scheme.lower(), scheme)

    @staticmethod
    def get_issuer_display_name(issuer):
        """
        Convert issuer code to official display name.

        :param issuer: Issuer code (e.g., 'edenred', 'swile')
        :return: Display name or original issuer if not found
        """
        if not issuer:
            return None
        return ISSUER_DISPLAY_NAMES.get(issuer.lower(), issuer)

    @staticmethod
    def build_card_info_string(payment):
        """
        Build card information string with scheme and issuer for accounting line name.

        Returns format: "Scheme / Issuer" or "Scheme" if no issuer

        :param payment: Payment record with card_type and optionally yavin_issuer
        :return: Formatted string or None if no card info
        """
        card_info_parts = []

        # Add scheme (card type)
        if payment.card_type:
            scheme_display = YavinCardInfoFormatter.get_scheme_display_name(payment.card_type)
            if scheme_display:
                card_info_parts.append(scheme_display)

        # Add issuer if available
        if hasattr(payment, 'yavin_issuer') and payment.yavin_issuer:
            issuer_display = YavinCardInfoFormatter.get_issuer_display_name(payment.yavin_issuer)
            if issuer_display:
                card_info_parts.append(issuer_display)

        return ' / '.join(card_info_parts) if card_info_parts else None
