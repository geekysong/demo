# Customer checkout demo

The live shopping page now starts with customer payment. Select the data product,
choose a payment method, finish checkout, return to Relay, then click **Run paid
procurement**. The customer pays Relay; Relay separately pays the vendor mirror.

- **Wallet:** GemWallet API 3.8.0, vendored with its license. Connect a funded
  XRPL Testnet account in the browser that has GemWallet installed. The app checks
  Testnet again before requesting approval. Customer price is **0.10 test XRP**
  plus network fee. No wallet seed is requested or stored.
- **Other wallets:** the checkout exposes the recipient, required destination
  tag, exact amount and a transaction-hash verification form. The backend queries
  a fixed Testnet RPC and checks validated success, destination, tag, delivered
  amount, and rejects partial payments and reused hashes.
- **Fiat:** a separate **$0.50 USD mock** checkout provides success, decline,
  retry and cancellation. Fixed card details are display-only. No processor is
  contacted and no real card information is accepted. The two prices are
  illustrative alternatives, not a live exchange-rate quote.
- No external wallet extension is available inside the Codex in-app browser;
  use the mock path there, or open the local URL in your GemWallet browser.

## Run locally

The regular `sh start.sh` serves port 8000. If another demo is already running,
start this version alongside it:

```sh
RELAY_SELF_URL=http://127.0.0.1:8001 .venv/bin/python -m uvicorn orchestrator:app --host 127.0.0.1 --port 8001
```

Use the same port for the page and backend. The self URL must match the server so
supplier mirror requests reach the updated instance.

## API change

Default `POST /run` now requires a paid `checkout_id`. Previous CLI examples that
omit it receive HTTP 402. Non-default policy-only test scenarios remain available
without payment. A minimal local mock sequence is:

1. `POST /checkout` with `{"method":"fiat","data_type":"business_registration_status"}`.
2. `POST /checkout/{id}/mock` with `{"outcome":"paid"}`.
3. `POST /run` with `{"checkout_id":"<id>","data_type":"business_registration_status"}`.

A checkout is bound to its data product and can start one procurement. Repeating
step 3 returns the original request ID. Concurrent runs are rejected without
consuming the second paid checkout. The default UI is still a single-user local
terminal, not a multi-tenant payment service.

Customer orders and unique transaction hashes persist in ignored
`.checkout.sqlite3`; checkout IDs are unguessable bearer capabilities. Session
storage retains the current checkout and any returned wallet transaction hash.
Payment details are in `GET /checkout/{id}`, including procurement status. These
paid UI orders bypass the older simulated trial-credit billing math, so the old
17.5% ledger is not presented as a second customer charge.

Failures retain the payment record and mark procurement `needs_review`. No
automatic blockchain refunds, fiat conversion, or production accounting are
implemented. After a process interruption, a claimed order is not automatically
restarted: preserve the payment and reconcile manually before attempting another
purchase. Only one backend instance should operate on this checkout database.

## Verification

- Nine Python tests passed (`test_customer_checkout`, `test_marketplace`), including
  unpaid gating, decline/retry/cancel, invalid recipient/tag/amount, partial and
  unvalidated transactions, hash reuse, product binding and single procurement.
- Both inline JavaScript bundles passed `node --check`.
- Browser-tested mock decline → retry → successful payment → return → procurement
  → sample delivery. Supplier Testnet transaction:
  `EC06E000AA77CA6E534CF88B38405B93B547575BE191532185875AAE80DA69AE`.
- Independently submitted a 0.10 test XRP payment between existing disposable demo
  wallets and confirmed HTTP 200 / paid through the new verification endpoint:
  `2390181A64D6F33572281A41DDE6D9DFD9D1282C4E7ADC232CCC1530BE10CF8E`.
- GemWallet extension approval itself still requires a user browser with the
  extension and funded Testnet account; it was not impersonated during testing.

SDK reference: https://gemwallet.app/docs/api/gemwallet-api-reference
