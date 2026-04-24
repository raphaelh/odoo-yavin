"""Helpers to expose the canonical addon-level response contract."""


def build_operation_response(
    operation_status, error_message=None, yavin_tx_id=None, **extra
):
    """Build a response using the canonical addon status field.

    ``operation_status`` may include ``pending`` for Cloud polling start/status.
    ``yavin_tx_id`` is forwarded to the POS when a cloud row is created or reused.
    """
    response = {
        "operation_status": operation_status,
    }
    if error_message is not None:
        response["error_message"] = error_message
    if yavin_tx_id is not None:
        response["yavin_tx_id"] = yavin_tx_id
    response.update({key: value for key, value in extra.items() if value is not None})
    return response
