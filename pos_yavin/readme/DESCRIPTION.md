This module adds support for **Yavin payment terminals** in the Odoo Point of Sale.

Yavin payment terminals communicate via a **Local API** (HTTP REST API) that runs
directly on the terminal. This API allows the point of sale to send payment
requests and receive payment responses over HTTP/JSON.

This module supports a bi-directional link with the payment terminal:

1.  it sends the payment amount and order information to the payment terminal via HTTP API
2.  it waits for the payment transaction to complete
3.  it parses the response from the payment terminal which gives the payment
    status: in case of success, the payment line is automatically validated;
    in case of failure, an error message is displayed and the Odoo user can
    retry or delete the payment line

The Yavin Local API uses HTTP REST over TCP/IP. The communication is done via
JSON payloads sent over HTTP POST requests. The terminal acts as an HTTP server
listening on port 16125 by default.

Key features:

* **Terminal Discovery**: Automatic discovery of Yavin terminals on the local
  network using Bonjour/NSD (mDNS) service discovery
* **IP Address Resolution**: Support for both IP addresses and Bonjour/NSD names
* **Tip Management**: Configurable display of tips in the POS interface and receipts
* **Multi-currency Support**: Supports EUR, CHF, and GBP currencies
* **Payment Abort**: Ability to cancel ongoing payment transactions
* **Error Handling**: Comprehensive error handling with user-friendly messages
