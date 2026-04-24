# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Pos Payment Method inheritance for Yavin integration."""

import base64
import logging
import os
import uuid

from odoo import api, fields, models, _
from odoo.modules.module import get_module_resource
from odoo.exceptions import ValidationError

from .yavin import (
    YavinPaymentOrchestrator,
    YavinRefundTransactionResolver,
    YavinTerminalDiscoverer,
    YAVIN_DEFAULT_TIMEOUT_MS,
    YAVIN_REVERSAL_TIMEOUT_MS,
    ZEROCONF_AVAILABLE,
    is_valid_cloud_api_key,
    normalize_secret,
)
from .yavin_hosting import yavin_is_odoo_sh_environment

logger = logging.getLogger(__name__)

_YAVIN_METHOD_DEFAULT_IMAGE_B64_CACHE = []


def _yavin_default_method_image_base64():
    """Load once: default art for pos.payment.method.image.

    Prefer ``yavin_method_default.png`` (752x752 RGBA, same canvas style as Odoo
    POS icons such as ``money.png`` / ``pay-later.png``). Fall back to the SVG
    source if the PNG is not shipped.
    """
    if not _YAVIN_METHOD_DEFAULT_IMAGE_B64_CACHE:
        data_b64 = False
        for fname in ("yavin_method_default.png", "yavin_method_default.svg"):
            path = get_module_resource("pos_yavin", "static/src/img", fname)
            if path and os.path.isfile(path):
                with open(path, "rb") as fhandle:
                    data_b64 = base64.b64encode(fhandle.read()).decode("ascii")
                break
        if data_b64:
            _YAVIN_METHOD_DEFAULT_IMAGE_B64_CACHE.append(data_b64)
        else:
            logger.warning("Yavin default payment method image file is missing")
            _YAVIN_METHOD_DEFAULT_IMAGE_B64_CACHE.append(False)
    val = _YAVIN_METHOD_DEFAULT_IMAGE_B64_CACHE[0]
    return val if val else False


class PosPaymentMethod(models.Model):
    """Inherit Pos Payment Method to handle Yavin terminal configuration."""

    _inherit = "pos.payment.method"

    def _get_payment_terminal_selection(self):
        res = super()._get_payment_terminal_selection()
        res.append(("yavin", _("Yavin")))
        return res

    def _is_write_forbidden(self, field_names):
        """Allow modifying Yavin configuration fields even with open sessions."""
        res = super()._is_write_forbidden(field_names)
        fields_set = set(field_names or [])
        allowed_fields = {
            "image",
            "yavin_ip_address",
            "yavin_display_tip",
            "yavin_connection_mode",
            "yavin_terminal_serial",
            "yavin_cloud_api_key",
            "yavin_webhook_token",
        }
        if fields_set and fields_set.issubset(allowed_fields):
            return False
        return res

    yavin_connection_mode = fields.Selection(
        [
            ("auto", "Automatic (Odoo.sh uses Cloud, otherwise Local API)"),
            ("local", "Local API (LAN terminal)"),
            ("cloud", "Cloud API (HTTPS)"),
        ],
        string="Yavin Connection",
        default="auto",
        help=(
            "Automatic uses the Yavin Cloud API with Odoo.sh, and the Yavin "
            "Local API with On-Premise."
        ),
    )
    yavin_effective_connection_mode = fields.Selection(
        [
            ("local", "Local"),
            ("cloud", "Cloud"),
        ],
        string="Yavin Effective Connection",
        compute="_compute_yavin_effective_connection_mode",
        help="Resolved connection type used for Yavin requests.",
    )

    yavin_ip_address = fields.Char(
        string="Yavin Terminal Address",
        help=(
            "IP address (e.g. 192.168.1.50) or DNS/Bonjour name "
            "(e.g. yavin_NCB700856023) of the Yavin terminal (Local API only). "
            "You can leave it empty while you use Discover; it must be set before "
            "the Point of Sale can reach the terminal."
        ),
    )
    yavin_terminal_serial = fields.Char(
        string="Yavin Terminal Serial Number",
        help="Terminal serial number from Yavin Services (Cloud API only).",
    )
    yavin_cloud_api_key = fields.Char(
        string="Yavin Cloud API Key",
        copy=False,
        groups="point_of_sale.group_pos_manager",
        help="API secret sent as the Yavin-Secret HTTP header (Cloud API only).",
    )
    yavin_webhook_token = fields.Char(
        string="Yavin Webhook Token",
        copy=False,
        groups="point_of_sale.group_pos_manager",
        help="Secret path segment for the Yavin Cloud webhook URL.",
    )
    yavin_webhook_url = fields.Char(
        string="Yavin Webhook URL",
        compute="_compute_yavin_webhook_url",
        readonly=True,
        help="HTTPS URL to configure in Yavin for asynchronous payment results.",
    )

    yavin_display_tip = fields.Boolean(
        string="Display Tip",
        default=True,
        help="If enabled, the tip will be displayed as an order line (in POS interface and "
        "receipt) and included in the total and payment amount. If disabled, the tip will "
        "not be displayed and will not be included in the total or payment amount (but will "
        "still be in the payment amount from the terminal).\n\n"
        "Note: Tips must be enabled in the POS configuration (Point of Sale > Configuration "
        "> Settings) for this option to work.",
    )
    yavin_timeout_ms = fields.Integer(
        string="Payment Timeout (ms)",
        compute="_compute_yavin_timeouts",
        help="Timeout in milliseconds for payment requests to the Yavin terminal",
    )
    yavin_reversal_timeout_ms = fields.Integer(
        string="Reversal Timeout (ms)",
        compute="_compute_yavin_timeouts",
        help="Timeout in milliseconds for reversal requests to the Yavin terminal",
    )
    yavin_zeroconf_available = fields.Boolean(
        string="Zeroconf Available",
        compute="_compute_yavin_zeroconf_available",
        help="Whether the zeroconf library is available for terminal discovery",
    )

    @api.depends("yavin_connection_mode")
    def _compute_yavin_effective_connection_mode(self):
        """Resolve auto mode using ODOO_STAGE (Odoo.sh)."""
        for record in self:
            mode = record.yavin_connection_mode
            if mode == "local":
                record.yavin_effective_connection_mode = "local"
            elif mode == "cloud":
                record.yavin_effective_connection_mode = "cloud"
            else:
                record.yavin_effective_connection_mode = (
                    "cloud" if yavin_is_odoo_sh_environment() else "local"
                )

    @api.depends("yavin_webhook_token")
    def _compute_yavin_webhook_url(self):
        """Build the public webhook URL from web.base.url."""
        icp = self.env["ir.config_parameter"].sudo()
        base = (icp.get_param("web.base.url") or "").rstrip("/")
        for record in self:
            if record.yavin_webhook_token and base:
                record.yavin_webhook_url = (
                    f"{base}/pos_yavin/payment/notify/{record.yavin_webhook_token}"
                )
            else:
                record.yavin_webhook_url = False

    @api.onchange("use_payment_terminal", "yavin_connection_mode")
    def _onchange_yavin_ensure_webhook_token(self):
        """Assign a webhook token in the UI before first save (so the URL is visible)."""
        logo_b64 = _yavin_default_method_image_base64()
        for rec in self:
            if rec.use_payment_terminal == "yavin" and not rec.yavin_webhook_token:
                rec.yavin_webhook_token = str(uuid.uuid4())
            if rec.use_payment_terminal == "yavin" and logo_b64 and not rec.image:
                rec.image = logo_b64

    @api.model
    def _get_yavin_default_method_image_base64(self):
        """Public wrapper for tests and optional callers."""
        return _yavin_default_method_image_base64()

    @api.model
    def _yavin_fill_missing_method_images(self):
        """Set the standard payment method image when Yavin is selected and image is empty."""
        b64 = _yavin_default_method_image_base64()
        if not b64:
            return
        methods = self.search(
            [("use_payment_terminal", "=", "yavin"), ("image", "=", False)]
        )
        if methods:
            methods.write({"image": b64})

    @api.model_create_multi
    def create(self, vals_list):
        logo_b64 = _yavin_default_method_image_base64()
        for vals in vals_list:
            if "yavin_cloud_api_key" in vals:
                vals["yavin_cloud_api_key"] = normalize_secret(vals.get("yavin_cloud_api_key"))
            if "yavin_terminal_serial" in vals:
                vals["yavin_terminal_serial"] = normalize_secret(vals.get("yavin_terminal_serial"))
            if (
                vals.get("use_payment_terminal") == "yavin"
                and not vals.get("yavin_webhook_token")
            ):
                vals["yavin_webhook_token"] = str(uuid.uuid4())
            if (
                vals.get("use_payment_terminal") == "yavin"
                and not vals.get("image")
                and logo_b64
            ):
                vals["image"] = logo_b64
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if "yavin_cloud_api_key" in vals:
            vals["yavin_cloud_api_key"] = normalize_secret(vals.get("yavin_cloud_api_key"))
        if "yavin_terminal_serial" in vals:
            vals["yavin_terminal_serial"] = normalize_secret(vals.get("yavin_terminal_serial"))
        res = super().write(vals)
        for method in self:
            if method.use_payment_terminal == "yavin" and not method.yavin_webhook_token:
                super(PosPaymentMethod, method).write(
                    {"yavin_webhook_token": str(uuid.uuid4())}
                )
        if vals.get("use_payment_terminal") == "yavin":
            logo_b64 = _yavin_default_method_image_base64()
            if logo_b64:
                missing = self.filtered(
                    lambda m: m.use_payment_terminal == "yavin" and not m.image
                )
                if missing:
                    super(PosPaymentMethod, missing).write({"image": logo_b64})
        return res

    @api.depends()
    def _compute_yavin_timeouts(self):
        """Expose timeout constants to the POS JS frontend."""
        for record in self:
            record.yavin_timeout_ms = YAVIN_DEFAULT_TIMEOUT_MS
            record.yavin_reversal_timeout_ms = YAVIN_REVERSAL_TIMEOUT_MS

    @api.depends()
    def _compute_yavin_zeroconf_available(self):
        """Compute whether zeroconf is available for terminal discovery."""
        for record in self:
            record.yavin_zeroconf_available = ZEROCONF_AVAILABLE

    @api.constrains("yavin_webhook_token")
    def _check_yavin_webhook_token_unique(self):
        for rec in self:
            token = (rec.yavin_webhook_token or "").strip()
            if not token:
                continue
            dup = self.search_count(
                [
                    ("yavin_webhook_token", "=", token),
                    ("id", "!=", rec.id),
                ]
            )
            if dup:
                raise ValidationError(
                    _("Yavin webhook token must be unique (duplicate detected)."),
                )

    @api.constrains(
        "use_payment_terminal",
        "yavin_connection_mode",
        "yavin_terminal_serial",
        "yavin_cloud_api_key",
    )
    def _check_yavin(self):
        for method in self:
            if method.use_payment_terminal != "yavin":
                continue
            # Local API terminal address is optional here; it is validated when
            # processing payments (see YavinPaymentValidator.resolve_ip_address) so
            # terminal discovery can run before the address is known.
            if method.yavin_effective_connection_mode == "cloud":
                if not (method.yavin_terminal_serial or "").strip():
                    raise ValidationError(
                        _(
                            "Yavin terminal serial number is not set on "
                            "payment method '%(method)s'.",
                            method=method.display_name,
                        )
                    )
                if not (method.yavin_cloud_api_key or "").strip():
                    raise ValidationError(
                        _(
                            "Yavin Cloud API key is not set on payment method '%(method)s'.",
                            method=method.display_name,
                        )
                    )
                if not is_valid_cloud_api_key(method.yavin_cloud_api_key):
                    raise ValidationError(
                        _(
                            "Yavin Cloud API key on payment method '%(method)s' is invalid. "
                            "Use the real key from Yavin Services.",
                            method=method.display_name,
                        )
                    )

    def _get_yavin_orchestrator(self):
        """Get the Yavin backend orchestrator."""
        return YavinPaymentOrchestrator(self.env)

    def _call_yavin_orchestrator(self, method_name, data):
        """Delegate RPC payload handling to the orchestrator."""
        orchestrator = self._get_yavin_orchestrator()
        return getattr(orchestrator, method_name)(data)

    def _get_yavin_refund_transaction_resolver(self):
        """Get the refund transaction resolver service."""
        return YavinRefundTransactionResolver(self.env)

    @api.model
    def yavin_send_payment(self, data):
        """Method called by the JS code of this module"""
        return self._call_yavin_orchestrator("send_payment", data)

    @api.model
    def yavin_cloud_start(self, data):
        """Start a Yavin Cloud payment; POS must poll ``yavin_cloud_status``."""
        return self._call_yavin_orchestrator("start_payment", data)

    @api.model
    def yavin_cloud_status(self, data):
        """Poll or expire a pending Yavin Cloud transaction (short RPC)."""
        return self._call_yavin_orchestrator("cloud_status", data)

    @api.model
    def yavin_abort_payment(self, data):
        """Method called by the JS code to abort a payment transaction."""
        return self._call_yavin_orchestrator("abort_payment", data)

    @api.model
    def yavin_send_reversal(self, data):
        """Method called by the JS code to reverse a payment transaction."""
        return self._call_yavin_orchestrator("send_reversal", data)

    @api.model
    def yavin_get_original_transactions(self, data):
        """
        Get all original Yavin transactions from the order when processing a refund.

        This method is called by the frontend when a refund order is loaded to automatically
        generate payment lines matching the original Yavin transactions.

        :param dict data: Dictionary containing:
            - order_uid (str): UID of the refund order (Legacy/Fallback)
            - session_id (int): POS session ID for filtering
            - refunded_orderline_ids (list[int]): IDs of original orderlines being refunded
        :return: List of dictionaries with keys:
            - transaction_id (str): Original transaction ID
            - amount (float): Original transaction amount
            Returns empty list if no matching transactions found.
        :rtype: list[dict]
        """
        return self._get_yavin_refund_transaction_resolver().resolve_original_transactions(
            data
        )

    @api.model
    def yavin_discover_terminals(self, timeout=5):
        """
        Discover Yavin payment terminals via Bonjour/mDNS.

        Delegates to YavinTerminalDiscoverer to respect Single Responsibility Principle.

        :param timeout: Discovery timeout in seconds (default: 5)
        :return: List of dictionaries with discovered terminals
        """
        return YavinTerminalDiscoverer(self.env).discover_terminals(timeout=timeout)

    def yavin_discover_terminals_action(self):
        """
        Action called by the discovery button in the view.
        Opens the discovery wizard that will automatically start the search.
        """
        self.ensure_one()
        if self.use_payment_terminal != "yavin":
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": _(
                        "This action is only available for Yavin payment methods."
                    ),
                    "type": "danger",
                },
            }
        if self.yavin_effective_connection_mode == "cloud":
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Not available"),
                    "message": _(
                        "Terminal discovery is only available for the Local Yavin API."
                    ),
                    "type": "warning",
                },
            }

        # Create wizard (discovery starts automatically on creation)
        wizard = self.env["yavin.discover.wizard"].with_context(
            active_model="pos.payment.method",
            active_id=self.id,
        ).create({"payment_method_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Yavin Terminal Discovery"),
            "res_model": "yavin.discover.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }
