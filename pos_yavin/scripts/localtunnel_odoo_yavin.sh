#!/usr/bin/env bash
# Copyright 2026 Raphaël HUCK
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Exposes local Odoo over HTTPS on *.loca.lt (localtunnel).
# Requires Node.js. Usage: ./scripts/localtunnel_odoo_yavin.sh [PORT]
# Default PORT is 8069.
#
# Subdomain: LOCALTUNNEL_SUBDOMAIN env, else "odoo-yavin-$USER" (less collision than
# a fixed global name — loca.lt subdomains are shared worldwide).
#
# Then set Odoo web.base.url to https://<subdomain>.loca.lt (no trailing slash).

set -euo pipefail
PORT="${1:-8069}"
SUBDOMAIN="${LOCALTUNNEL_SUBDOMAIN:-odoo-yavin-${USER:-dev}}"
echo "Using https://${SUBDOMAIN}.loca.lt — set Odoo parameter web.base.url to that (no trailing slash)." >&2
echo "If you see someone else's site, that name is taken: export LOCALTUNNEL_SUBDOMAIN=my-unique-name" >&2
exec npx --yes localtunnel --port "${PORT}" --subdomain "${SUBDOMAIN}"
