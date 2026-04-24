# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Public HTTP endpoint for Yavin Cloud payment webhooks."""

import json
import logging

from odoo import http
from odoo.http import request

logger = logging.getLogger(__name__)


class YavinWebhookController(http.Controller):
    """Receive asynchronous payment results from Yavin Cloud."""

    @http.route(
        "/pos_yavin/payment/notify/<string:token>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def yavin_payment_notify(self, token, **_kwargs):
        logger.info(
            "Yavin webhook: POST /pos_yavin/payment/notify/... token_prefix=%s",
            (token or "")[:8],
        )
        try:
            payload = json.loads(request.httprequest.get_data(cache=False, as_text=True) or "{}")
        except ValueError:
            logger.warning("Yavin webhook: invalid JSON for token prefix=%s", (token or "")[:8])
            return request.make_json_response({"ok": True}, status=200)

        request.env["yavin.cloud.transaction"].sudo()._yavin_process_webhook(token, payload)
        request.env.cr.commit()  # pylint: disable=invalid-commit
        return request.make_json_response({"ok": True}, status=200)
