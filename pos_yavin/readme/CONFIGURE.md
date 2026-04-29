## Module dependencies

This module declares the following Odoo dependencies (see ``__manifest__.py``):

- **point_of_sale** — core POS integration.
- **pos_self_order** — extends ``pos.config`` with fields such as ``self_ordering_mode``,
  which is required on recent Odoo POS databases (NOT NULL column). Depending on this
  module keeps the ORM aligned with the database and avoids errors when creating POS
  configurations or running tests.

Python package **zeroconf** is optional and only required for Bonjour/mDNS terminal
discovery on on-prem LAN deployments (see below). It is not required for Cloud API
flows (typical on Odoo.sh).

---

In the menu *Point of Sale > Configuration > Payment Methods*, on the
payment method that corresponds to a payment by card:

- select the appropriate journal, which should be a bank journal (and
  not a cash journal, otherwise the field *Use a payment terminal* is
  invisible)
- field *Use a payment terminal*: select **Yavin**
- field *Yavin Connection*: **Automatic** uses the Cloud API when the
  environment variable ``ODOO_STAGE`` is set (typical on Odoo.sh), otherwise the
  Local API. Choose **Local API** or **Cloud API** to override this behaviour.
- **Local API** (LAN): field *Yavin Terminal Address* — terminal IP or Bonjour/NSD
  name (e.g. ``192.168.1.100`` or ``yavin_NCB700946013``).
- **Cloud API** (HTTPS): fields *Yavin Terminal Serial Number* and *Yavin API Key*.
  Copy the read-only *Yavin Webhook URL* into the Yavin dashboard. The webhook must be
  reachable over **HTTPS** with no redirect.
- API key safety: the key remains visible in the payment method form for operator checks,
  but validation rejects empty values and known placeholders. Error messages never include
  the key value.
- field *Display Tip*: enable to show tips as order lines in the POS interface and on
  receipts (tips must also be enabled in the POS configuration).

### Local development: Yavin API webhooks with localtunnel

Yavin calls your webhook from the public internet, so ``http://localhost:8069`` is
not enough. **localtunnel** exposes your local Odoo port over **HTTPS** so you can
paste a real URL into the Yavin dashboard.

#### Subdomain and **global name collisions**

On **loca.lt**, subdomains are **shared worldwide**. If you open ``https://odoo-yavin.loca.lt``
and see **another application** (not your Odoo), someone else’s tunnel is bound to that name,
or you are not running your tunnel yet. Always pick a **unique** ``--subdomain`` and set
``web.base.url`` to ``https://<that-subdomain>.loca.lt``.

The helper script defaults to ``odoo-yavin-$USER`` (Unix login), which reduces collisions.
Override with:

```bash
export LOCALTUNNEL_SUBDOMAIN=my-unique-yavin-tunnel
./scripts/localtunnel_odoo_yavin.sh 8069
```

1. **Start Odoo** on your usual port (default **8069**).

2. **Start localtunnel** from the addon directory (Node.js required):

   ```bash
   chmod +x scripts/localtunnel_odoo_yavin.sh   # once
   ./scripts/localtunnel_odoo_yavin.sh 8069
   ```

   Read the URL printed on stderr (``https://<subdomain>.loca.lt``). Or without the script:

   ```bash
   npx localtunnel --port 8069 --subdomain my-unique-yavin-tunnel
   ```

   Keep this process running while you test.

3. **Set ``web.base.url``** in Odoo to **exactly** that HTTPS origin **without** a trailing slash
   (same host the script printed):

   *Settings → Technical → Parameters → System Parameters* → key ``web.base.url``.

4. **Reload** the Yavin payment method form so *Yavin Webhook URL* recomputes, then
   copy the full webhook URL into the Yavin merchant configuration.

5. Set the payment method to **Cloud API** (or **Automatic** on Odoo.sh), enter the
   terminal serial and API key, and run a POS payment as usual.

**Optional:** if Odoo mis-detects the public host behind the tunnel, start the server
with ``--proxy-mode`` (see Odoo deployment docs) so generated URLs match the tunnel.

**Caveat:** ``*.loca.lt`` may show a browser interstitial on the first hit. If Yavin’s
server-side POST never reaches your controller, try **ngrok** or **Cloudflare Tunnel**,
or confirm the request is not answered with an HTML landing page instead of Odoo.

## Terminal Discovery

This module includes a wizard to automatically discover Yavin terminals on
your local network. To use it:

1. Go to *Point of Sale > Configuration > Payment Methods*
2. Create or edit a payment method with *Use a payment terminal* set to **Yavin**
3. Click on the button *Discover Yavin Terminals*
4. The wizard will search for available terminals on your network
5. Select a terminal from the list and click *Select* to automatically
   configure the IP address

**Note**: Terminal discovery requires the ``zeroconf`` Python library. This is mainly
useful for on-prem Local API setups. Cloud API setups (typical on Odoo.sh) do not
require ``zeroconf``. If needed, install it with:

```bash
pip install zeroconf
```

## Maintainer checklist (OCA / integrators)

Assign owners on the PR for **human** validation (this is not automated).

- [ ] **Dependencies** — Confirm that declaring **pos_self_order** is acceptable for your
  deployments (extra module install vs. alignment with current ``pos.config`` schemas / NOT NULL columns).
- [ ] **Manifest** — ``depends``, ``external_dependencies``, and version in ``__manifest__.py``
  match the intended release; bump version if behavior or dependencies changed.
- [ ] **README and App Store HTML** — After editing fragments under ``readme/``, regenerate
  from the **repository root** (paths relative to that root):

  ```bash
  pip install "git+https://github.com/OCA/maintainer-tools.git"
  oca-gen-addon-readme --org-name=raphaelh --repo-name=odoo-yavin --branch=17.0 \
    --addon-dir=pos_yavin --gen-html
  ```

  Commit the updated ``README.rst`` and ``static/description/index.html``. Do not edit
  ``README.rst`` by hand.

- [ ] **Tests** — Odoo test suite passes with dependencies installed (see ``readme/TESTS.md``).
- [ ] **Translations** — Regenerate ``.pot`` / sync Weblate if user-visible strings changed.
- [ ] **Release notes** — Mention notable changes (e.g. new hard dependency) for integrators
  and upgrade notes if applicable.
