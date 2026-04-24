# Running the Test Suite

For module layout and design rules, see ``docs/ARCHITECTURE.md`` in this addon.

## Python tests

1. Create or reuse a test database.
2. Install or upgrade the module (dependencies such as ``pos_self_order`` are pulled from the manifest):

```bash
docker compose run --rm odoo odoo --stop-after-init -d <database> -i pos_yavin
```

3. Run the test suite (use a free HTTP port if another Odoo instance is already bound, e.g. on 8069):

```bash
docker compose run --rm odoo odoo --test-enable --stop-after-init --http-port=8079 -d <database> -u pos_yavin
```

On an **existing** database that predates the ``pos_self_order`` dependency, install it once if needed:

```bash
docker compose run --rm odoo odoo --stop-after-init -d <database> -i pos_self_order
```

This executes the transaction-based unit tests under ``tests/``. Prefer **sequential** test runs with **distinct HTTP ports** when you automate several jobs in parallel.

### Cloud polling (Python)

Run only the Cloud start/status + webhook recovery tests:

```bash
docker compose run --rm odoo odoo --test-enable --stop-after-init --http-port=8079 -d <database> -u pos_yavin --test-tags /pos_yavin/tests/test_cloud_polling.py
```

## Pylint (optional)

From the addon directory, with Odoo and this addon on ``PYTHONPATH``:

**Without** ``pylint-odoo`` (no extra pip package):

```bash
cd addons/pos_yavin
python3 -m pylint --rcfile=.pylintrc models wizard tests
```

**With** ``pylint-odoo`` (OCA-style, includes translation and Odoo-specific rules):

```bash
pip install pylint pylint-odoo
cd addons/pos_yavin
python3 -m pylint --rcfile=pylintrc.odoo models wizard tests
```

The ``pylintrc.odoo`` file loads the plugin and silences ``import-error`` and
``duplicate-code`` for this addon-level run.

## JavaScript tests

There are three ways to run JavaScript tests:

### Option 1: Automated via Python test (Recommended)

Run the Python test that automatically executes JavaScript tests in a headless browser:

```bash
docker compose run --rm odoo odoo --test-enable --stop-after-init --http-port 8071 -d <database> -u pos_yavin --test-tags /pos_yavin/tests/test_js.py
```

This uses the `YavinJSTestSuite` class in `tests/test_js.py` which sets up the required POS environment and runs the QUnit tests (including ``static/tests/payment_yavin_polling_tests.js`` for the Cloud polling RPC flow).

### Option 2: Manual browser execution

1. Start Odoo with development mode:

```bash
docker compose up odoo
```

2. Open `/pos/ui/tests?mod=pos_yavin` in a browser to run the POS QUnit tests interactively.

### Option 3: Command line only

Run only the JS wrapper test without the rest of the module test suite:

```bash
docker compose run --rm odoo odoo --test-enable --stop-after-init --http-port 8072 -d <database> -i pos_yavin --test-tags /pos_yavin/tests/test_js.py
```

Use a dedicated HTTP port for browser-based tests to avoid conflicts with a running Odoo instance on `8069`.

## Translations / i18n checks

Before releasing translated user-facing changes:

1. Regenerate ``i18n/pos_yavin.pot`` with your standard Odoo export workflow.
2. Sync ``i18n/fr.po`` and ``i18n/es.po`` from the updated POT.
3. Verify each PO entry keeps a ``#. module: pos_yavin`` marker (required by Odoo parser).

