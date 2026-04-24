# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Discovery wizard for Yavin payment terminals."""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

logger = logging.getLogger(__name__)


class YavinDiscoverWizard(models.TransientModel):
    """Wizard to discover Yavin payment terminals."""

    _name = "yavin.discover.wizard"
    _description = "Wizard to discover Yavin payment terminals"

    payment_method_id = fields.Many2one(
        "pos.payment.method",
        required=True,
        readonly=True,
    )
    discovered_terminals = fields.One2many(
        "yavin.discover.wizard.terminal",
        "wizard_id",
    )

    is_discovering = fields.Boolean(
        string="Discovering",
        default=True,
        readonly=True,
    )
    discovery_message = fields.Text(
        string="Status",
        default="Search in progress...",
        readonly=True,
    )
    discovery_progress = fields.Float(
        default=0.0,
        readonly=True,
        help="Progress of the discovery process (0-100%)",
    )

    @api.model
    def default_get(self, fields_list):
        """Set default payment method and translated discovery message from context."""
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") == "pos.payment.method":
            res["payment_method_id"] = self.env.context.get("active_id")
            res["discovery_message"] = _("Search in progress...")
        return res

    def action_start_discovery(self):
        """
        Synchronous action to discover terminals.

        To be called by the client controller.
        """
        self.ensure_one()
        timeout = 3  # 3 seconds is usually enough for local mDNS

        try:
            payment_method = self.payment_method_id
            if not payment_method.exists():
                raise UserError(_("Payment method no longer exists."))

            # Perform discovery (blocking)
            discovered = payment_method.yavin_discover_terminals(timeout=timeout)

            # Sort terminals by IP address for consistent ordering
            discovered = sorted(discovered, key=lambda t: t.get("ip_address", ""))

            terminal_vals = []
            for terminal in discovered:
                terminal_vals.append((0, 0, {
                    "name": terminal["name"],
                    "ip_address": terminal["ip_address"],
                    "port": terminal.get("port", 0),
                }))

            if discovered:
                if len(discovered) == 1:
                    message = _("Search completed: 1 terminal found.")
                else:
                    message = _(
                        "Search completed: %(count)d terminals found.",
                        count=len(discovered),
                    )
            else:
                message = _(
                    "No terminal found. Please check that the terminals "
                    "are powered on and connected to the network."
                )

            self.write(
                {
                    "discovered_terminals": [(5, 0, 0)] + terminal_vals,
                    "is_discovering": False,
                    "discovery_progress": 100.0,
                    "discovery_message": message.replace("\n", " "),
                }
            )
            return True

        except (UserError, ValidationError) as e:
            self.write(
                {
                    "is_discovering": False,
                    "discovery_progress": 0.0,
                    "discovery_message": _(
                        "Error during search: %(error)s", error=str(e)
                    ),
                }
            )
            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error during terminal discovery: %s", e, exc_info=True)
            self.write(
                {
                    "is_discovering": False,
                    "discovery_progress": 0.0,
                    "discovery_message": _(
                        "Error during search: %(error)s", error=str(e)
                    ),
                }
            )
            return False

    def action_retry_discovery(self):
        """
        Retry the discovery process.

        Resets the wizard state and starts a new discovery via client action.
        """
        self.ensure_one()
        if not self.payment_method_id:
            raise UserError(_("No payment method selected"))

        # Reset wizard state
        self.write({
            "is_discovering": True,
            "discovery_message": _("Search in progress..."),
            "discovery_progress": 0.0,
            "discovered_terminals": [(5, 0, 0)],
        })

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }


class YavinDiscoverWizardTerminal(models.TransientModel):
    """Discovered Yavin terminal in wizard."""
    # pylint: disable=too-few-public-methods

    _name = "yavin.discover.wizard.terminal"
    _description = "Discovered Yavin terminal in wizard"

    wizard_id = fields.Many2one(
        "yavin.discover.wizard",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(readonly=True)
    ip_address = fields.Char(string="IP Address", readonly=True)
    port = fields.Integer(readonly=True)

    def action_select(self):
        """
        Select this terminal and update the payment method.

        This method is called from the tree view button.
        """
        self.ensure_one()
        wizard = self.wizard_id
        if not wizard.payment_method_id:
            raise UserError(_("No payment method selected"))

        if not wizard.payment_method_id.exists():
            raise UserError(_("The payment method no longer exists."))

        # Validate terminal data
        if not self.name:
            raise UserError(_("Selected terminal has no name."))
        if not self.ip_address:
            raise UserError(_("Selected terminal has no IP address."))

        # Update payment method with Bonjour hostname for resilience to IP changes
        # (YavinAddressResolver handles resolution at payment time)
        payment_method = wizard.payment_method_id
        payment_method.write({"yavin_ip_address": self.name})

        logger.info(
            "Terminal '%s' (Bonjour) selected for payment method %s",
            self.name,
            payment_method.display_name,
        )

        return {"type": "ir.actions.act_window_close"}
