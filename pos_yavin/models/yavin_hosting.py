# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Detect Odoo.sh-style hosting (injected environment variables)."""

import os


def yavin_is_odoo_sh_environment():
    """
    Return True when ODOO_STAGE is set (Odoo.sh / Odoo Cloud Platform convention).

    On typical on-premise installs this variable is absent, so Local API is used
    when the payment method is in ``auto`` mode.
    """
    return bool(os.environ.get("ODOO_STAGE"))
