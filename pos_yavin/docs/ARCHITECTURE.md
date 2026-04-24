# `pos_yavin` Architecture

## Python layout

```text
models/
  pos_payment_method.py    # Yavin configuration and payment RPC endpoints
  pos_session.py           # POS session extensions
  pos_payment.py           # Stored payment metadata
  pos_order.py             # POS order extensions
  yavin_cloud_transaction.py # Persisted Cloud polling transaction lifecycle

  yavin/
    __init__.py            # Public service exports
    constants.py           # Shared constants (endpoints, currencies)
    validation.py          # Payload and configuration validation

    application/
      payment_orchestrator.py # Shared entry point for Local/Cloud payment flows
      cloud_payment.py        # Cloud start/status/webhook orchestration and persistence

    api/
      client.py            # HTTP client for the terminal Local API
      payload_builder.py   # Outgoing payload builders
      response_parser.py   # Terminal response normalization

    network/
      address_resolver.py  # IP / hostname resolution
      service_listener.py  # Zeroconf service listener
      terminal_discoverer.py # Terminal discovery orchestration

    formatting/
      amount_converter.py  # Amount <-> cents conversion
      card_info_formatter.py # Card metadata formatting
      data_extractor.py    # Customer and POS data extraction

    version/
      provider.py          # POS version information provider
```

## JavaScript layout

```text
static/src/
  payment/
    payment_yavin.js       # Facade around payment sub-services
    payment_state.js       # Payment line state management helpers
    payment_cancel.js      # Abort/cancel flow
    payment_request.js     # Payment request flow + response handlers
    payment_reversal.js    # Reversal flow
    tip_handler.js         # Tip synchronization and hidden-tip persistence
    lifecycle_utils.js     # Shared recovery and stale-status rules

  overrides/
    models/
      models.js            # POS model patches and shared Yavin helpers
    components/
      order_widget/
        order_widget.js    # Tip-line filtering in the order summary
        order_widget.xml   # Matching template extension
      payment_screen/
        payment_screen.js  # Recovery and refund-line automation

  wizard/
    discover_wizard.js     # Backend discovery wizard controller
```

## Design rules

### 1. Keep Yavin business logic in services

Python service classes under `models/yavin/` own validation, formatting, transport, and discovery.
Odoo model files should remain thin integration layers.

### 2. Share frontend rules instead of duplicating them

Common POS behaviors such as stale transaction recovery or tip visibility should live in reusable helpers.
Component overrides should only adapt Odoo screens to those shared rules.

### 3. Keep Cloud transaction transitions explicit

Cloud polling flows should move through explicit states (``pending`` -> ``done`` / ``error``)
with idempotent transaction identifiers. Late webhooks must be treated as normal recovery events,
not as exceptional control flow.

### 4. Avoid coupling to Odoo private frontend APIs

When possible, rely on explicit order data such as refunded order lines instead of private helpers or transient properties that may change across Odoo updates.

### 5. Keep documentation aligned with the code

Examples in this file should match the current module structure and exported helper names so the document stays useful during maintenance.

## Testing strategy

- Use `TransactionCase` for backend logic so tests run through Odoo's standard `--test-enable` pipeline.
- Keep API/network behavior deterministic with `unittest.mock.patch` around `requests.post` and resolver services.
- Prefer targeted suites per service (`api`, `network`, `validation`, `wizard`) before running broader coverage passes.
- Current targeted backend campaign reached ~95% total coverage with strong coverage on critical Yavin flows.
