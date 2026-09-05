# Relay

**An on-demand data procurement agent for lenders.**

A lender requests missing data. Relay selects a resource under the lender's procurement rules, reads the quote, handles payment, and returns data with a traceable purchase receipt. One Relay integration provides access to multiple data sources; lending decisions remain with the lender.

This repository is a hackathon demo using **real XRP Testnet settlement, local vendor mirrors, and sample data delivery**. It is not a production lending system.

See [submission guide, architecture and checklist](SUBMISSION.md) for the integrated Ripple challenge materials and current acceptance behavior.

## Customer payment

The demo now supports a GemWallet / manual **XRPL Testnet** checkout and a separate **mock fiat card checkout**. Pay first, then run procurement. See [checkout flow and API changes](CHECKOUT_DEMO.md); default `/run` now requires a paid `checkout_id`.

## What the demo shows

The dashboard has three tabs:

| Screen | Contents |
| --- | --- |
| Live Shopping | Request details, vendor declarations, filtering, HTTP 402 quotes, payment status, delivered data, and on-chain receipts |
| Policy Config | Read-only display of effective budget and category rules |
| Audit Ledger | Purchase records, candidates and rejection reasons, transaction links, and CSV export |

Two data products are available:

| Product | Data category | Demo output |
| --- | --- | --- |
| CompliancePulse · Global LEI lookup | Business registration status | Sample legal name, entity status, registration status, and related fields |
| MacroPulse · BLS wage benchmarks | Industry income benchmarks | Historical BLS wage sample for US legal services (May 2023) |

A successful run follows this flow:

> Structured request → Source discovery → Policy filtering → HTTP 402 quote → Signed payment → Testnet settlement → Independent on-chain confirmation → Data and audit receipt

Relay checks the final quote before signing and independently verifies the payer, recipient and exact delivered amount on-chain. Payment and data acceptance are separate: `delivered` requires confirmed payment and accepted data. Current samples end at `delivery_needs_review`: LEI provenance/freshness remains unknown, and historical wages fail freshness. See [submission guide](SUBMISSION.md).

## Quick start

These commands target macOS / Linux and require **Python 3.11+** (verified locally with 3.12), Git, and internet access. Access to a private GitHub repository requires permission; a signed-out browser may show a 404 page.

```sh
git clone git@github.com:geekysong/demo.git
cd demo
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python setup_testnet.py
sh start.sh
```

If you already downloaded the repository, enter its directory and start with the virtual environment step. Replace `python3.12` with your installed Python 3.11+ command if needed.

Open the **[local dashboard](http://127.0.0.1:8000/)**, choose a data category, and click **Run flow**. Run one request at a time during the demo.

The setup script creates disposable payer and merchant Testnet wallets, requests test XRP from the faucet, and saves their configuration in a Git-ignored `.env` file with permissions `600`. It preserves existing wallet configuration. No real funds or Mainnet wallet are required. Do not commit or share `.env`.

For subsequent starts, run this from the repository directory:

```sh
sh start.sh
```

The backend listens only on `127.0.0.1:8000` and serves both the dashboard and business API. Restart it after closing the terminal or rebooting. See the [local setup guide](LOCAL_SETUP.md) (Chinese) for additional environment details.

## View the presentations

- **[Product story v2](relay-business-deck-v2.html)**: a 10-slide presentation covering the product, customer scenario, delivered result, reasons to pay, business model, and technical mechanism.
- [Original presentation](relay-business-deck.html): the earlier version, retained for reference.

GitHub displays HTML files as source code. After cloning, open a file directly in your browser, or run a static server from the repository directory in another terminal:

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

Open the **[local v2 presentation](http://127.0.0.1:8765/relay-business-deck-v2.html)** and use the arrow keys to navigate. Port 8765 serves static content; purchases still require the business backend on port 8000. These localhost links point to the viewer's own computer, not a public deployment.

## What is real and what is simulated

| Component | Current implementation |
| --- | --- |
| Vendor discovery | Live, unpaid HTTP 402 probes of two configured resources; no dynamic search across the entire Bazaar directory |
| Unavailable sources | Each resource can fall back independently to a fixture, labeled as fallback in the dashboard; mirror purchases remain available |
| Policy checks | Server-side checks of price, cumulative spend, category, trust threshold, and freshness fields; trust and freshness values include demo assumptions |
| Payment | A local payer wallet sends XRP Testnet funds to the local mirror's merchant account |
| Original vendors | Their declarations advertise Mainnet `xrpl:0`; the demo does not pay them |
| Data delivery | LEI returns a stored vendor sample; the wage mirror returns a cited historical BLS wage sample. Neither verifies the current applicant |
| Receipts | Real transaction hashes, independent on-chain confirmation, and balance lookups; audit records are appended to local JSONL |
| Platform billing | Demo ledger calculations only; no actual collection from lenders |

One verified purchase paid **20,000 drops (0.02 XRP)** and returned `delivered / tesSUCCESS`: [Testnet transaction](https://testnet.xrpl.org/transactions/B92C9FC50F57E81F0814B46E55A9E59AE789DDABB73E2A8484C1D7EB8318C138). This verifies payment and sample delivery, not real data quality or production performance.

See [MARKETPLACE_TESTNET.md](MARKETPLACE_TESTNET.md) for source and mirror details.

## Business model

The proposed product charges lending institutions per completed data purchase, pays the supplier, and retains procurement service revenue. Its value lies in unified source access, procurement rules, and payment records.

The presentation proposes **US$0.50 per query and US$10 in trial credit**, subject to validation. The current `billing.py` instead models **vendor cost plus a 17.5% platform fee and a nominal US$50 trial credit**. For accepted legacy purchases, trial credit covers vendor data cost only and platform fees are recorded. Current sample orders require review and do not add a legacy platform fee; confirmed supplier spend still counts toward the applicant cap. Billing switches automatically to pay-as-you-go when credit is exhausted.

The running ledger uses a fixed conversion assumption, not live exchange rates. USD collection, USDT settlement, and currency conversion are not implemented; on-chain payments currently use XRP Testnet. The two pricing models have not been reconciled and should not be used to infer real profit margins.

## API example

With the backend running, complete [checkout](CHECKOUT_DEMO.md) first, then use the paid checkout ID to start procurement:

```sh
curl -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"checkout_id":"YOUR_PAID_CHECKOUT_ID","applicant_score":612,"data_type":"business_registration_status","applicant_region":"US","freshness_requirement_days":30}'

curl http://127.0.0.1:8000/status
```

`POST /run` returns a run ID asynchronously. `GET /status` reports the current global run state; it does not provide isolated task lookup by ID.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Backend status and Testnet identifier |
| `GET /marketplace/candidates` | Refresh both vendors' unpaid declarations |
| `GET /policy.json` | Effective policy |
| `GET /billing` | Demo billing balance |
| `GET /audit` | Audit records as JSON |
| `GET /audit.csv` | CSV export |

`POST /run` also accepts `scenario: "over_cap"`, `"blacklist"`, or `"no_candidate"` for policy tests without payment. The frontend stops polling on these terminal states; inspect their reasons through the status API or audit ledger.

## Current limitations

- Policy configuration is read-only. Candidate selection uses deterministic rules and demo trust/freshness proxies. Delivery checks required fields, explicit observation dates and region, but cannot certify provenance. Category-specific freshness policy and LLM-based goal interpretation are not implemented.
- No-candidate outcomes produce status and audit records, without an actionable human-review queue. PDF export is not implemented.
- Final quote binding and terminal-state handling are implemented. Persistent recovery of an unknown supplier payment and automatic refunds still need work.
- Run state is global, with no multi-tenancy, authentication, or complete concurrency and idempotency protection.
- Billing and cumulative spend are held in memory and reset on restart. JSONL audit records persist but are not tamper-proof.

See [PRD v2.1](relay-prd-v2-gap-execution-plan.md) (Chinese) for the full gap review, priorities, and acceptance criteria. [README_AUDIT.md](README_AUDIT.md) contains historical test records; some completion claims are outdated, so use the current PRD review as the implementation baseline.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `failed to start run` or a JSON/SyntaxError | Run `sh start.sh` and use the dashboard on port 8000. Refresh old pages after code changes. |
| No compatible `x402-xrpl` installation found | Check that the virtual environment uses Python 3.11+, rather than system Python 3.9. |
| Missing or inactive wallets | Run `setup_testnet.py` in the virtual environment. Existing `.env` configuration is preserved; test funds are requested only for wallets that have not been activated. |
| RPC request fails | Check internet connectivity and `XRPL_TESTNET_RPC_URL` in `.env`. The setup script configures `https://s.altnet.rippletest.net:51234/`. |
| GitHub repository returns 404 | Sign in to a GitHub account with repository access in the browser. Git SSH authentication and browser sign-in are separate. |

## Code structure

| File | Responsibility |
| --- | --- |
| `orchestrator.py` | FastAPI service, mirror routes, purchase flow, state, and audit records |
| `marketplace.py` | Resource declaration adapter and fallback samples |
| `policy_filter.py` | Policies, filtering, and test fixtures |
| `billing.py` | Trial credit and platform fee ledger |
| `relay-screen1-live.html` | Dashboard with three tabs |
| `setup_testnet.py` / `start.sh` | Wallet configuration and local startup |
| `requirements.txt` | Dependency versions from the verified environment |

## Wallet visualization

Open **Wallets** from the dashboard or visit `/wallets` to explore a master wallet funding two independent purchasing wallets. Create wallets, allocate funds, purchase sample data, and recover a lost delivery without paying again. This page uses real signatures with **offline simulated settlement**, separate from the Testnet checkout flow. See [WALLET_VISUALIZATION.md](WALLET_VISUALIZATION.md).
