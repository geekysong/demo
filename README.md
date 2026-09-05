# Relay — Steps 5–7 real settlement (round 2, self-audit fixes + live UI)

> Current local setup / 换机与启动说明：见 [LOCAL_SETUP.md](LOCAL_SETUP.md)。
> 下文包含历史迭代记录；当前启动命令为 `sh start.sh`，看板地址为 http://127.0.0.1:8000/。

## Round 3: Screen 1 UI now drives the real flow

**Answer to the question that started this round: no, it's not showing fake
states anymore.** Every phase the UI displays — Shopping, Quote, Settling,
Delivered — comes from polling a real backend (`orchestrator.py`) that
actually performs Steps 5-8 against XRPL Testnet, not a `setTimeout` timeline.

### New architecture

`orchestrator.py` merges the merchant (require_payment) and the Relay Agent
(payer) into one FastAPI app so a browser can drive and observe the flow:

- `GET /` — serves `relay-screen1-live.html`
- `POST /run` — kicks off `run_real_flow()` in a background thread
- `GET /status` — the UI polls this every 400ms; every field is written at
  the moment a real event happens (see `orchestrator.py` comments for exactly
  which network/chain call triggers each state write)
- `GET /income-verification` — the actual protected endpoint (unchanged from round 2)

`run_real_flow()` does NOT call the convenience `x402_requests` wrapper used
in round 2's `client.py` — that wrapper is a single opaque call with no
hooks for intermediate state. Instead it replicates the same steps manually
using the library's lower-level pieces (`XRPLPresignedPaymentPayer`,
`PaymentRequirements`) so each real network call can update `STATE` between
steps: raw unpaid GET → real 402 body → sign real XRPL tx → retry with
signature → facilitator verifies+settles → **independent on-chain
confirmation via a separate `Tx` RPC lookup** (same self-audit method as
round 2, now built into the live flow instead of a manual check afterward).

### Verified end-to-end via curl (i.e., exactly what the browser does)

```
POST /run  -> {"started":true,"run_id":1}
GET /status polled every 0.5s:
  candidates -> paying -> settling -> confirming -> delivered
```

Resulting transaction, independently confirmed:
- tx hash: `4D8048BF8282D945086FB754E60DBBB61466C4FB191FA4287D0BAFA79455FD35`
- explorer: https://testnet.xrpl.org/transactions/4D8048BF8282D945086FB754E60DBBB61466C4FB191FA4287D0BAFA79455FD35
- `TransactionResult: tesSUCCESS`, `validated: true`, `delivered_amount: 5000`, `Destination` matches your address
- balance moved `99974930 → 99969920` drops (confirmed via a second, separate `account_info` query — not the facilitator's word)

### What the UI now shows vs what it showed before

| | Round 1 (static prototype) | Round 3 (this) |
|---|---|---|
| Candidate reveal | `setTimeout`, fixed 750ms | Real `policy_filter.py` output, rendered when `/status` reports it |
| 402 quote | hardcoded string in HTML | Actual 402 response body from a real HTTP call, parsed and shown |
| "Settling" state | `setTimeout`, fixed 1200ms | Held open for however long the real facilitator verify+settle call actually takes |
| tx hash | `randHex()` — literally fake | From the facilitator's real `PAYMENT-RESPONSE` header |
| "confirmed" badge | didn't exist | Result of a live, separate `Tx` RPC call the browser can also make itself — link is right there in the receipt |
| Balance before/after | didn't exist | Two real `account_info` queries, shown with the delta |

### Running it

```bash
cd x402_poc
cp .env.server .env; cat .env.client >> .env   # orchestrator needs both merchant + buyer config
python3 orchestrator.py
# open http://localhost:8000/ and click "Run flow"
```

### Known limitation carried over from round 2 (not re-fixed here)

Client-side polling degrades gracefully if `/status` 404s or the fetch
throws (a red `status poll error` line appears), but the browser has no way
to know if the *backend* thread silently died without ever writing
`phase: "failed"` — it would just poll forever. Worth a timeout guard if
this goes further than a demo.

---


## Fixes applied after self-audit

1. **Steps 2-4 → Step 5 handoff (was: hardcoded vendor).** Added `policy_filter.py`,
   which runs the actual Policy Matrix filter (trust min 70, freshness max 30d,
   category whitelist) against the same 3 mock candidates round 1's UI used.
   `server.py` now imports this and configures its price/vendor/description from
   whatever the filter selects, instead of a hand-typed string. Verified: server
   startup log shows the real selection (`PayrollPing API` accepted, other two
   rejected with reasons), `selection.json` is written at startup, and a fresh
   on-chain settlement (`8D073D2EBB566B23FA205923EC2C43C3E474E5CA66FDD2C971938A67238990FF`,
   confirmed `tesSUCCESS` via independent `tx` RPC lookup) used the filter's price.
2. **Silent payment failure (was: exit 0 on failure).** `client.py` now checks
   `status_code == 200` explicitly; anything else raises `PaymentFailed` and the
   process exits non-zero. Verified against the same insufficient-funds scenario
   as before — client now exits with code 1 and prints a `❌ PAYMENT FAILED` line
   to stderr with a traceback, instead of quietly printing "not settled" and
   returning 0.

Not fixed, on purpose (deferred as demo-acceptable, per earlier discussion):
RLUSD untested, ~8s measured latency vs. PRD's "3-5s", non-production
facilitator, audit log fields incomplete relative to PRD Section 5's full
schema. See the self-audit report in conversation for the full breakdown.

---


Scope: only PRD Section 4, Steps 5–7 (quote → pay → settle). Vendor selection,
Policy Matrix filtering, and the UI stay exactly as built in round 1 — this
does not touch that HTML prototype.

## What's real vs. what's still mocked

| Piece | Status |
|---|---|
| Vendor discovery, candidate list, Policy Matrix filter (Steps 2–4) | still mocked — server.py hardcodes one already-selected vendor ("PayrollPing API"), same as the round-1 prototype |
| HTTP 402 + payment requirements (Step 5) | **real** — served by `x402-xrpl`'s FastAPI middleware |
| Wallet signs & submits XRPL Payment (Step 6) | **real** — signed with `xrpl-py`, submitted to XRPL Testnet |
| Facilitator verify + settle (Step 7) | **real** — calls T54's public testnet facilitator (`xrpl-facilitator-testnet.t54.ai`) |
| Data delivery (Step 8) | **real** — merchant returns the payload only after the facilitator confirms settlement |

## Proof this actually ran (not a mock)

- **tx hash**: `08C4D5A9CD9282DF8312F3EA9B1F400B218C1633A290FEC7C58DC58ECE7E7683`
- **explorer**: https://testnet.xrpl.org/transactions/08C4D5A9CD9282DF8312F3EA9B1F400B218C1633A290FEC7C58DC58ECE7E7683
- Independently confirmed via a direct `tx` RPC call (not just trusting the facilitator's word): `TransactionResult: tesSUCCESS`, `validated: true`, 5000 drops moved from the throwaway Relay Agent wallet to your address.
- Full receipt: `last_receipt.json` in this folder.

## Accounts used

- **Merchant / vendor payTo** (`XRPL_PAY_TO`): `rwZTWDscjAfmyToDtmP7ZQk4sBG4HFWEPB` — your address from round 1. It received the 5000 drops.
- **Relay Agent / payer**: `rENbfkn1B9Nx8DsBsvd5Pscc3yRXkuypEs` — a throwaway wallet generated and funded by me via the testnet faucet, specifically so I never needed your seed. Its seed lives only in the container this ran in, not in anything handed to you. Treat this wallet as disposable — regenerate it yourself if you keep working on this.

## Files

- `server.py` — merchant side. Protects `/income-verification` with `require_payment`. This stands in for "PayrollPing API," the vendor round 1's mock Policy Matrix filter selected.
- `client.py` — Relay Agent side. Loads a wallet from `XRPL_BUYER_SEED`, uses `x402_requests` to handle the 402 → sign → settle → retry flow transparently.
- `.env.server` / `.env.client` — config each side reads. `.env.client` has a seed in it — **do not commit this file or paste its contents anywhere.**
- `last_receipt.json` — output of the run above.

## Running it yourself

```bash
pip install fastapi uvicorn x402-xrpl python-dotenv requests xrpl-py

# terminal 1
cp .env.server .env
python3 server.py

# terminal 2 (separate shell, same folder)
cp .env.client .env
python3 client.py
```

If you swap in your own buyer wallet, generate a **fresh** one via the faucet
UI rather than reusing anything from this conversation, and put the seed only
in `.env.client` — never in a chat message.

## One infra note for later

The public XRPL testnet RPC host from the official docs
(`s.altnet.rippletest.net:51234`) was unreachable from this container —
non-standard port, timed out. Used `https://testnet.xrpl-labs.com/` (port
443, full rippled node) instead, which worked. If you deploy this somewhere
with different egress rules, that substitution might not be necessary — or a
different one might be, depending on what ports are open.

## What this does NOT cover

- Screens 2/3 (still out of scope per round 1)
- RLUSD pricing (still XRP — PRD's dollar figures aren't wired to a real FX rate anywhere in this skeleton)
- Mainnet — this is `xrpl:1` (testnet) throughout; moving to mainnet needs a funded real wallet, the mainnet facilitator URL, and `network="xrpl:0"`
- Audit log persistence — `last_receipt.json` is a one-off file, not wired into any ledger/DB
