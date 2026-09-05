"""
Relay PRD v2 — orchestrator for wiring Screen 1's UI to the real flow, plus
Screen 2 (Policy Configuration, read-only) and Screen 3 (Audit Ledger).

This does NOT introduce a new payment mechanism. It's the same require_payment
middleware and the same underlying XRPLPresignedPaymentPayer signing code that
client.py/server.py used in round 2 — just split into its individual real
network calls instead of one opaque session.get(), so each call can update a
STATE object the browser polls. Every field the UI reads comes from an actual
network response (the 402 body, the signed-payment retry's response, an
independent XRPL account_info lookup) — nothing here is a timer-driven fake.

Round 4 additions (see README_AUDIT.md for the full honest write-up):
  - Policy Matrix filtering (Section 4 Step 4 / Section 5) now runs FRESH on
    every /run trigger, in run_real_flow(), instead of once at import time.
    A NoQualifyingCandidate escalation halts the flow before any payment is
    attempted — it does not crash the process anymore.
  - POST /run accepts an optional {"scenario": ...} to exercise the Section-5
    guardrail test fixtures in policy_filter.TEST_SCENARIOS without spending
    real testnet XRP (those scenarios stop right after the filter step).
  - Every trigger — real purchase, policy-test-only, or escalation — appends
    one record to audit_log.jsonl (Screen 3) with: timestamp, request_id,
    trigger_reason, candidates_considered, final_selection, price,
    XRPL transaction hash, delivery_status.
  - GET /audit-ledger (Screen 3, HTML), GET /audit (JSON), GET /audit.csv
    (CSV export). GET /policy-config (Screen 2, HTML, read-only).

Round 5 additions:
  - Section 4 Step 1 is now a real structured request, not a fixed display
    string: POST /run accepts applicant_score, data_type, applicant_region,
    freshness_requirement_days. Screen 1's "Run flow" button sends the exact
    values shown in its intake panel (612 / selected marketplace category / US / 30)
    instead of an empty body, so what's displayed and what's evaluated are
    finally the same thing.
  - Section 5 "Trigger threshold": applicant_score is checked against
    policy_filter.in_gray_zone() BEFORE any discovery/filtering happens. Out
    of band -> the Agent never fires, logged as its own delivery_status.
  - Section 4 Steps 2-3: data_type now scopes discovery via
    policy_filter.discover_candidates() before Step 4's Policy Matrix runs
    over the results. A candidate whose category doesn't match the
    requested data_type was never "returned" by discovery — a different,
    earlier rejection than failing the Policy Matrix.
  - freshness_requirement_days (per-request, from the lender) tightens
    (never loosens) the server's configured freshness_max_days for that run.
  - Section 3 (Pricing): billing.py applies the $50 trial credit + platform
    fee to every completed purchase; result is attached to STATE and the
    audit record, and exposed at GET /billing.
"""
import csv
import io
import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
import requests
from xrpl.wallet import Wallet
from xrpl.clients import JsonRpcClient

from x402_xrpl.server import require_payment
from x402_xrpl.client import XRPLPresignedPaymentPayer, XRPLPresignedPaymentPayerOptions
from x402_xrpl.clients.base import decode_payment_response, X402Client
from x402_xrpl.types import PaymentRequirements

import billing
import customer_checkout
import wallet_visualization
import marketplace
import policy_filter
from relay_payment import add_relay_comment
from policy_filter import filter_candidates, NoQualifyingCandidate

load_dotenv()

PAY_TO = os.environ["XRPL_PAY_TO"]
FACILITATOR_URL = os.getenv("XRPL_FACILITATOR_URL", "https://xrpl-facilitator-testnet.t54.ai")
SOURCE_TAG = int(os.getenv("XRPL_SOURCE_TAG", "20260904"))
BUYER_SEED = os.environ["XRPL_BUYER_SEED"]
RPC_URL = os.getenv("XRPL_TESTNET_RPC_URL", "https://testnet.xrpl-labs.com/")
SELF_URL_BASE = os.getenv("RELAY_SELF_URL", "http://localhost:8000")

app = FastAPI()
app.include_router(customer_checkout.router)
app.include_router(wallet_visualization.router)
RUN_START_LOCK = threading.Lock()
RUN_ACTIVE = False
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MIRROR_CANDIDATES = {candidate["id"]: candidate for candidate in marketplace.fallback_candidates()}

# The real marketplace resources advertise xrpl:0. These two local mirrors
# deliberately settle through t54's xrpl:1 facilitator, at the same nominal
# XRP amount, and return the sample output declared by the real resource.
for mirror in MIRROR_CANDIDATES.values():
    app.middleware("http")(
        require_payment(
            path=mirror["testnet_path"],
            price=str(mirror["price_drops"]),
            pay_to_address=PAY_TO,
            facilitator_url=FACILITATOR_URL,
            network="xrpl:1",
            asset="XRP",
            description=f"Testnet mirror of {mirror['name']} — {mirror['category']}",
            extra={"sourceTag": SOURCE_TAG, "candidateId": mirror["id"], "mirror": True},
        )
    )


def _mirror_payload(candidate_id: str) -> dict:
    candidate = MIRROR_CANDIDATES[candidate_id]
    return {
        "vendor": candidate["name"],
        "data_type": candidate["category"],
        "delivery_mode": candidate["delivery_mode"],
        "sample_label": candidate["sample_label"],
        "sample_note": candidate["sample_note"],
        "source_marketplace": candidate["marketplace"],
        "source_url": candidate["source_url"],
        "source_network": candidate["source_network"],
        "settlement_network": "xrpl:1",
        "result": candidate["sample_data"],
    }


@app.get("/testnet-mirror/lei")
async def testnet_mirror_lei():
    return _mirror_payload("T54-LEI")


@app.get("/testnet-mirror/bls")
async def testnet_mirror_bls():
    return _mirror_payload("T54-BLS")


# ---------------------------------------------------------------------------
# State the UI polls. Every write below is triggered by a real event
# (a real HTTP response, a real chain query) — see comments at each site.
# ---------------------------------------------------------------------------
STATE_LOCK = threading.Lock()
STATE = {"run_id": 0, "phase": "idle"}


def set_state(**kwargs):
    with STATE_LOCK:
        STATE.update(kwargs)


def get_state():
    with STATE_LOCK:
        return dict(STATE)


# ---------------------------------------------------------------------------
# Section 5: "Per-applicant cumulative cap ... Hard limit + counter". In-memory
# running total per applicant_id. Resets on server restart — a real deployment
# would persist this alongside the audit ledger.
# ---------------------------------------------------------------------------
APPLICANT_SPEND_LOCK = threading.Lock()
APPLICANT_SPEND_DROPS: dict[str, int] = {}


def get_applicant_spent(applicant_id: str) -> int:
    with APPLICANT_SPEND_LOCK:
        return APPLICANT_SPEND_DROPS.get(applicant_id, 0)


def add_applicant_spend(applicant_id: str, drops: int) -> None:
    with APPLICANT_SPEND_LOCK:
        APPLICANT_SPEND_DROPS[applicant_id] = APPLICANT_SPEND_DROPS.get(applicant_id, 0) + drops


# ---------------------------------------------------------------------------
# Screen 3 — Audit Ledger. Append-only JSONL, one record per trigger.
# Fields match Section 5 "Audit logging" + Section 6 Screen 3 exactly:
# timestamp, request_id, trigger_reason, candidates_considered,
# final_selection, price, XRPL transaction hash, delivery_status.
# ---------------------------------------------------------------------------
AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.jsonl")
AUDIT_LOCK = threading.Lock()


def append_audit(record: dict) -> None:
    with AUDIT_LOCK:
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")


def read_audit() -> list:
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    with AUDIT_LOCK:
        with open(AUDIT_LOG_PATH) as f:
            lines = f.readlines()
    out = []
    for line in lines:
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def build_candidates_considered(input_candidates, selected, rejected):
    """Merge the filter's accept/reject verdicts back onto the original
    candidate list, in original order, for the audit record."""
    rejected_by_id = {r["id"]: r for r in rejected}
    keys = (
        "id", "name", "price_drops", "price_label", "category", "trust_score",
        "freshness_days", "source_url", "source_network", "payment_mode",
    )
    out = []
    for c in input_candidates:
        base = {k: c[k] for k in keys if k in c}
        if selected is not None and c["id"] == selected["id"]:
            out.append({**base, "passed": True, "rejection_reasons": []})
        else:
            r = rejected_by_id.get(c["id"])
            out.append({**base, "passed": False, "rejection_reasons": r["rejection_reasons"] if r else ["not evaluated"]})
    return out


def build_not_discovered_entries(not_discovered, data_type):
    """Candidates the Bazaar discovery query (Section 4 Steps 2-3) never
    returned in the first place — a different, earlier rejection than
    failing the Policy Matrix in Step 4."""
    keys = (
        "id", "name", "price_drops", "price_label", "category", "trust_score",
        "freshness_days", "source_url", "source_network", "payment_mode",
    )
    return [
        {
            **{k: c[k] for k in keys if k in c},
            "passed": False,
            "rejection_reasons": [
                f"not returned by Bazaar discovery for data_type='{data_type}' (candidate category='{c['category']}')"
            ],
        }
        for c in not_discovered
    ]


def query_balance(address: str) -> int:
    """Independent on-chain balance check via account_info — same method
    used in the round-2 self-audit, not something the payment SDK reports."""
    client = JsonRpcClient(RPC_URL)
    from xrpl.models.requests import AccountInfo
    resp = client.request(AccountInfo(account=address, ledger_index="validated"))
    return int(resp.result["account_data"]["Balance"])


def run_real_flow(
    run_id: int, request_id: str, scenario: str, applicant_id: str, trigger_reason: str,
    applicant_score=None, data_type=None, applicant_region=None, freshness_requirement_days=None, customer_checkout_id=None,
):
    timestamp = datetime.now(timezone.utc).isoformat()

    def audit_base():
        return {
            "timestamp": timestamp, "request_id": request_id, "trigger_reason": trigger_reason,
            "applicant_id": applicant_id, "scenario": scenario,
            "customer_checkout_id": customer_checkout_id,
            "applicant_score": applicant_score, "data_type": data_type,
            "applicant_region": applicant_region, "freshness_requirement_days": freshness_requirement_days,
        }

    # ---- Section 4 Step 2-4: discover candidates, filter via Policy Matrix.
    # Runs fresh on every trigger. scenario="default" uses the production
    # Bazaar candidate set; any other scenario name uses a Section-5
    # guardrail test fixture (see policy_filter.TEST_SCENARIOS) instead.
    if scenario == "default":
        # Live, unpaid HTTP 402 probes: real t54 Bazaar metadata and sample
        # outputs, with an independent fallback for each resource.
        candidates_in = marketplace.load_candidates()
        policy_in = policy_filter.POLICY
    else:
        fixture = policy_filter.TEST_SCENARIOS[scenario]
        candidates_in = fixture["candidates"]
        policy_in = fixture.get("policy", policy_filter.POLICY)

    applicant_spent_before = get_applicant_spent(applicant_id)

    set_state(
        run_id=run_id, phase="candidates", request_id=request_id, scenario=scenario,
        applicant_id=applicant_id, trigger_reason=trigger_reason, applicant_score=applicant_score,
        data_type=data_type, applicant_region=applicant_region,
        freshness_requirement_days=freshness_requirement_days,
        error=None, quote=None, tx_hash=None, settlement=None,
        delivered=None, balance_before=None, balance_after=None, billing=None,
    )

    # ---- Section 5 "Trigger threshold": only fires within the pre-defined
    # gray zone band. This is a read-only flag check, not a Policy Matrix
    # rule the Agent can reinterpret — it halts BEFORE discovery even runs.
    if applicant_score is not None and not policy_filter.in_gray_zone(applicant_score, policy_in):
        lo, hi = policy_in.get("gray_zone_score_min"), policy_in.get("gray_zone_score_max")
        reason = f"applicant score {applicant_score} is outside the gray zone band [{lo}, {hi}] — Agent does not fire"
        set_state(phase="not_triggered", error=reason, candidates_considered=None, selected=None, rejected=None)
        append_audit({
            **audit_base(),
            "candidates_considered": None,
            "final_selection": None,
            "price_drops": None,
            "xrpl_transaction_hash": None,
            "delivery_status": f"not_triggered: {reason}",
        })
        return

    try:
        # ---- Section 4 Steps 2-3: Bazaar discovery scoped to data_type ----
        discovered, not_discovered = policy_filter.discover_candidates(candidates_in, data_type)
        if not discovered:
            considered = build_not_discovered_entries(not_discovered, data_type)
            set_state(
                phase="escalated_no_candidate", selected=None, rejected=None,
                candidates_considered=considered,
                error=f"Bazaar discovery returned zero candidates for data_type='{data_type}'",
            )
            append_audit({
                **audit_base(),
                "candidates_considered": considered,
                "final_selection": None,
                "price_drops": None,
                "xrpl_transaction_hash": None,
                "delivery_status": "escalated_no_qualifying_candidate",
            })
            return

        # ---- freshness_requirement_days (per-request, from the lender) can
        # only TIGHTEN the server's configured freshness_max_days, never
        # loosen it — the Agent doesn't get to relax its own criteria.
        effective_policy = policy_in
        if freshness_requirement_days is not None:
            effective_policy = dict(policy_in)
            effective_policy["freshness_max_days"] = min(policy_in["freshness_max_days"], freshness_requirement_days)

        try:
            selected, rejected = filter_candidates(discovered, effective_policy, applicant_spent_before)
        except NoQualifyingCandidate as e:
            # ---- Section 5 "No qualifying candidate" hard stop condition ----
            # Halt BEFORE any payment is attempted. Escalate to a human by
            # writing the escalation to the audit ledger (this demo has no
            # human-in-the-loop channel beyond that, same limitation the
            # original code already documented).
            considered = build_candidates_considered(discovered, None, getattr(e, "rejected", [])) \
                + build_not_discovered_entries(not_discovered, data_type)
            set_state(
                phase="escalated_no_candidate", selected=None, rejected=getattr(e, "rejected", []),
                candidates_considered=considered, error=str(e),
            )
            append_audit({
                **audit_base(),
                "candidates_considered": considered,
                "final_selection": None,
                "price_drops": None,
                "xrpl_transaction_hash": None,
                "delivery_status": "escalated_no_qualifying_candidate",
            })
            return

        considered = build_candidates_considered(discovered, selected, rejected) \
            + build_not_discovered_entries(not_discovered, data_type)
        set_state(phase="candidates", selected=selected, rejected=rejected, candidates_considered=considered)
        time.sleep(0.4)  # let the UI render the candidate reveal before the network calls start

        if scenario != "default":
            # ---- Guardrail test only: prove the filter fired correctly and
            # stop here. Does not spend real testnet XRP re-demonstrating
            # settlement, which round 3 already proved end-to-end.
            set_state(phase="policy_test_complete")
            append_audit({
                **audit_base(),
                "candidates_considered": considered,
                "final_selection": {
                    "id": selected["id"], "name": selected["name"], "price_drops": selected["price_drops"],
                    "source_url": selected.get("source_url"), "source_network": selected.get("source_network"),
                    "payment_mode": selected.get("payment_mode"),
                },
                "price_drops": selected["price_drops"],
                "xrpl_transaction_hash": None,
                "delivery_status": "policy_test_not_purchased",
            })
            return

        # ==================== scenario == "default": real purchase ====================
        buyer = Wallet.from_seed(BUYER_SEED)
        balance_before = query_balance(buyer.classic_address)
        set_state(phase="quote", buyer_address=buyer.classic_address, balance_before=balance_before)

        # ---- Step 5: real unpaid GET -> real 402 ----
        selected_endpoint = SELF_URL_BASE + selected["testnet_path"]
        resp1 = requests.get(selected_endpoint, timeout=30)
        if resp1.status_code != 402:
            raise RuntimeError(f"expected 402, got {resp1.status_code}: {resp1.text[:300]}")
        body = resp1.json()
        accepts = body["accepts"]
        reqs_dict = X402Client.default_payment_requirements_selector(accepts, None, "exact", None)
        reqs = PaymentRequirements.from_dict(reqs_dict)
        set_state(phase="quoted", quote=reqs_dict)

        # ---- Step 6: sign a real XRPL Payment tx and submit the retry ----
        set_state(phase="paying")
        payer = XRPLPresignedPaymentPayer(
            XRPLPresignedPaymentPayerOptions(wallet=buyer, network=reqs.network, rpc_url=RPC_URL, invoice_binding="both")
        )
        x_payment = payer.create_payment_header(reqs)  # <-- real signing happens here
        x_payment = add_relay_comment(x_payment, buyer)
        set_state(phase="settling")

        # ---- Step 7: retry with signature -> facilitator verifies + settles server-side ----
        resp2 = requests.get(selected_endpoint, headers={"PAYMENT-SIGNATURE": x_payment}, timeout=180)
        if resp2.status_code != 200:
            raise RuntimeError(f"settlement failed: HTTP {resp2.status_code}: {resp2.text[:400]}")

        payment_response = resp2.headers.get("PAYMENT-RESPONSE")
        settlement = decode_payment_response(payment_response) if payment_response else None
        tx_hash = settlement.get("transaction") if settlement else None

        # ---- independent on-chain confirmation, not just trusting the facilitator ----
        set_state(phase="confirming", tx_hash=tx_hash, settlement=settlement)
        confirmed = False
        chain_result = None
        if tx_hash:
            client = JsonRpcClient(RPC_URL)
            from xrpl.models.requests import Tx
            for _ in range(10):
                try:
                    txr = client.request(Tx(transaction=tx_hash))
                    if txr.result.get("validated"):
                        chain_result = txr.result["meta"]["TransactionResult"]
                        confirmed = chain_result == "tesSUCCESS"
                        break
                except Exception:
                    pass
                time.sleep(1)

        balance_after = query_balance(buyer.classic_address)

        delivery_status = "delivered" if confirmed else "settlement_unconfirmed"
        bill = None
        if confirmed:
            add_applicant_spend(applicant_id, selected["price_drops"])
            # ---- Section 3 (Pricing): trial credit + platform fee, applied
            # to the billing ledger — NOT a second on-chain payment. See
            # billing.py for why. ----
            bill = billing.bill_purchase(selected["price_drops"]) if not customer_checkout_id else None

        # ---- Step 8: data already came back in resp2 ----
        set_state(
            phase=delivery_status,
            delivered=resp2.json(),
            chain_result=chain_result,
            confirmed=confirmed,
            balance_after=balance_after,
            billing=bill,
        )
        append_audit({
            **audit_base(),
            "candidates_considered": considered,
            "final_selection": {
                "id": selected["id"], "name": selected["name"], "price_drops": selected["price_drops"],
                "source_url": selected.get("source_url"), "source_network": selected.get("source_network"),
                "payment_mode": selected.get("payment_mode"),
            },
            "price_drops": selected["price_drops"],
            "xrpl_transaction_hash": tx_hash,
            "delivery_status": delivery_status,
            "platform_fee_drops": bill["platform_fee_drops"] if bill else None,
            "billed_total_drops": bill["billed_total_drops"] if bill else None,
            "billing_mode_after": bill["billing_mode_after"] if bill else None,
        })
    except Exception as e:
        set_state(phase="failed", error=f"{e}", traceback=traceback.format_exc())
        append_audit({
            **audit_base(),
            "candidates_considered": None,
            "final_selection": None,
            "price_drops": None,
            "xrpl_transaction_hash": None,
            "delivery_status": f"failed: {e}",
        })


def run_customer_flow(*args, **kwargs):
    global RUN_ACTIVE
    checkout_id = kwargs.get('customer_checkout_id')
    try:
        run_real_flow(*args, **kwargs)
    except Exception as exc:
        set_state(phase='failed', error=str(exc))
    finally:
        try:
            if checkout_id:
                customer_checkout.finish(checkout_id, get_state().get('phase'))
        finally:
            with RUN_START_LOCK:
                RUN_ACTIVE = False


@app.post("/run")
async def run(request: Request):
    global RUN_ACTIVE
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    scenario = body.get("scenario", "default")
    if scenario != "default" and scenario not in policy_filter.TEST_SCENARIOS:
        return JSONResponse(
            status_code=400,
            content={"error": f"unknown scenario '{scenario}'", "known_scenarios": ["default", *policy_filter.TEST_SCENARIOS.keys()]},
        )
    applicant_id = body.get("applicant_id", "APPLICANT-DEMO-001")
    trigger_reason = body.get(
        "trigger_reason",
        "applicant score 612 (gray zone) — lender risk engine requested business registration status",
    )
    # ---- Section 4 Step 1: structured request fields. Defaults match what
    # Screen 1's intake panel displays, so a click with no overrides behaves
    # exactly like every prior round's "default" run did. Guardrail test
    # scenarios (scenario != "default") default these to None instead —
    # their fixtures are built to trip one specific Policy Matrix rule via
    # filter_candidates(), and scoping them by data_type/score first would
    # filter the interesting candidate out before it ever reached that rule.
    if scenario == "default":
        applicant_score = body.get("applicant_score", 612)
        data_type = body.get("data_type", "business_registration_status")
        applicant_region = body.get("applicant_region", "US-TX")
        freshness_requirement_days = body.get("freshness_requirement_days", 30)
    else:
        applicant_score = body.get("applicant_score")
        data_type = body.get("data_type")
        applicant_region = body.get("applicant_region")
        freshness_requirement_days = body.get("freshness_requirement_days")

    checkout_id = body.get("checkout_id")
    if scenario == "default" and not checkout_id:
        return JSONResponse(status_code=402, content={"error": "Complete wallet or mock fiat checkout first"})
    with RUN_START_LOCK:
        if checkout_id:
            previous = customer_checkout.fetch(checkout_id)
            if previous['request_id']:
                return customer_checkout.claim(checkout_id, data_type, previous['run_id'], previous['request_id'])
        current = get_state()
        if RUN_ACTIVE or current.get('phase') in {'starting','candidates','quote','quoted','paying','settling','confirming'}:
            return JSONResponse(status_code=409, content={"error": "A procurement is already running. Your payment is retained; retry shortly."})
        request_id = uuid.uuid4().hex.upper()
        if checkout_id:
            customer_checkout.claim(checkout_id, data_type, current.get('run_id', 0) + 1, request_id)
        with STATE_LOCK:
            STATE["run_id"] += 1
            run_id = STATE["run_id"]
        # Publish the new run synchronously before returning. Without this, a
        # fast browser poll can observe the previous run's terminal state and
        # stop polling before the worker thread has updated STATE.
        set_state(
            run_id=run_id,
            phase="starting",
            request_id=request_id,
            scenario=scenario,
            applicant_id=applicant_id,
            trigger_reason=trigger_reason,
            applicant_score=applicant_score,
            data_type=data_type,
            applicant_region=applicant_region,
            freshness_requirement_days=freshness_requirement_days,
            selected=None,
            rejected=None,
            candidates_considered=None,
            quote=None,
            tx_hash=None,
            delivered=None,
            confirmed=None,
            error=None,
        )
        RUN_ACTIVE = True
        threading.Thread(
            target=run_customer_flow,
            args=(run_id, request_id, scenario, applicant_id, trigger_reason),
            kwargs=dict(
                applicant_score=applicant_score, data_type=data_type,
                applicant_region=applicant_region, freshness_requirement_days=freshness_requirement_days,
                customer_checkout_id=checkout_id,
            ),
            daemon=True,
        ).start()
        return {"started": True, "run_id": run_id, "request_id": request_id, "scenario": scenario}


@app.get("/status")
async def status():
    return JSONResponse(get_state())


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pay_to": PAY_TO,
        "network": "xrpl:1",
        "marketplace": marketplace.DIRECTORY_URL,
        "testnet_mirrors": [c["name"] for c in MIRROR_CANDIDATES.values()],
    }


@app.get("/marketplace/candidates")
def marketplace_candidates():
    """Real live 402 metadata + samples; this endpoint never pays."""
    return JSONResponse(marketplace.load_candidates())


# ---------------------------------------------------------------------------
# Section 3 — Pricing (billing ledger, not an on-chain payment — see billing.py)
# ---------------------------------------------------------------------------
@app.get("/billing")
async def billing_state():
    return JSONResponse(billing.get_billing_state())


# ---------------------------------------------------------------------------
# Screen 3 — Audit Ledger
# ---------------------------------------------------------------------------
@app.get("/audit")
async def audit_json():
    return JSONResponse(read_audit())


@app.get("/audit.csv")
async def audit_csv():
    rows = read_audit()
    fieldnames = [
        "timestamp", "request_id", "trigger_reason", "applicant_id", "scenario",
        "applicant_score", "data_type", "applicant_region", "freshness_requirement_days",
        "candidates_considered", "final_selection", "price_drops",
        "xrpl_transaction_hash", "delivery_status",
        "platform_fee_drops", "billed_total_drops", "billing_mode_after",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        row = dict(r)
        row["candidates_considered"] = json.dumps(row.get("candidates_considered"))
        row["final_selection"] = json.dumps(row.get("final_selection"))
        w.writerow({k: row.get(k) for k in fieldnames})
    return Response(content=buf.getvalue(), media_type="text/csv")


def _esc(v):
    return "" if v is None else str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


AUDIT_PAGE_STYLE = """
:root{
  --ink:#12161C; --panel:#1A1F27; --panel-raised:#1F2530;
  --line:#2C333D; --line-soft:#232A33;
  --text:#E7E4DA; --text-dim:#8B93A0; --text-faint:#5B6270;
  --brand:#6FA8C9; --amber:#E8A33D; --green:#5FB88A; --rust:#C9614A;
  --radius:3px;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{background:var(--ink);color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:13px;line-height:1.55;}
.wrap{max-width:1100px;margin:0 auto;padding:28px 24px 60px;}
header{display:flex;align-items:baseline;justify-content:space-between;padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:22px;}
.brand{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:21px;letter-spacing:-.01em;}
.brand span{color:var(--brand);}
.brand-sub{color:var(--text-faint);font-size:12px;margin-top:3px;}
a{color:var(--brand);}
.section-label{font-family:'Space Grotesk',sans-serif;font-weight:600;font-size:12px;color:var(--text-dim);margin-bottom:10px;}
table{width:100%;border-collapse:collapse;font-size:11.5px;}
th,td{border-bottom:1px solid var(--line-soft);padding:8px 10px;text-align:left;vertical-align:top;}
th{color:var(--text-faint);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;}
td.mono{color:var(--text-dim);word-break:break-all;}
.status-delivered{color:var(--green);}
.status-escalated{color:var(--amber);}
.status-failed{color:var(--rust);}
.status-test{color:var(--brand);}
.hash{color:var(--brand);}
.empty{color:var(--text-faint);padding:20px 0;}
.note{color:var(--text-faint);font-size:11px;margin-top:16px;}
details summary{cursor:pointer;color:var(--text-dim);}
pre{white-space:pre-wrap;word-break:break-all;color:var(--text-dim);font-size:10.5px;margin:4px 0 0;}
"""


def _status_class(status: str) -> str:
    if not status:
        return ""
    if status.startswith("delivered"):
        return "status-delivered"
    if status.startswith("escalated"):
        return "status-escalated"
    if status.startswith("failed"):
        return "status-failed"
    if status.startswith("policy_test"):
        return "status-test"
    return ""


@app.get("/audit-ledger", response_class=HTMLResponse)
async def audit_ledger_page():
    rows = list(reversed(read_audit()))  # newest first
    body_rows = []
    for r in rows:
        sel = r.get("final_selection")
        sel_str = f"{sel['name']} ({sel['id']})" if sel else "—"
        tx = r.get("xrpl_transaction_hash")
        tx_html = f'<a class="hash" href="https://testnet.xrpl.org/transactions/{_esc(tx)}" target="_blank">{_esc(tx)}</a>' if tx else "—"
        considered = r.get("candidates_considered") or []
        considered_html = "".join(
            f"<div>{'✓' if c.get('passed') else '✗'} {_esc(c.get('name'))} ({_esc(c.get('id'))}) — "
            f"{_esc(c.get('price_drops'))} drops, {_esc(c.get('category'))}"
            + (f" — {', '.join(c.get('rejection_reasons') or [])}" if not c.get('passed') else "")
            + "</div>"
            for c in considered
        ) or "—"
        status = r.get("delivery_status") or ""
        body_rows.append(f"""
        <tr>
          <td class="mono">{_esc(r.get('timestamp'))}</td>
          <td class="mono">{_esc(r.get('request_id'))}</td>
          <td>{_esc(r.get('trigger_reason'))}<br><span class="mono">applicant: {_esc(r.get('applicant_id'))} · scenario: {_esc(r.get('scenario'))}</span></td>
          <td><details><summary>{len(considered)} considered</summary>{considered_html}</details></td>
          <td>{_esc(sel_str)}</td>
          <td class="mono">{_esc(r.get('price_drops'))}</td>
          <td class="mono">{tx_html}</td>
          <td class="{_status_class(status)}">{_esc(status)}</td>
        </tr>""")

    table = "".join(body_rows) or '<tr><td colspan="8" class="empty">No audit records yet — trigger a run from <a href="/">Screen 1</a>.</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Relay — Audit Ledger (Screen 3)</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{AUDIT_PAGE_STYLE}</style></head>
<body><div class="wrap">
<header>
  <div>
    <div class="brand"><span>RE</span>LAY — Audit Ledger</div>
    <div class="brand-sub">Screen 3 — chronological log of every procurement trigger, real transactions and escalations alike</div>
  </div>
  <div><a href="/">Screen 1</a> &nbsp;·&nbsp; <a href="/policy-config">Screen 2</a> &nbsp;·&nbsp; <a href="/audit.csv">Export CSV</a></div>
</header>
<div class="section-label">{len(rows)} record(s)</div>
<table>
<thead><tr><th>Timestamp (UTC)</th><th>Request ID</th><th>Trigger reason</th><th>Candidates considered</th><th>Final selection</th><th>Price (drops)</th><th>XRPL tx hash</th><th>Delivery status</th></tr></thead>
<tbody>{table}</tbody>
</table>
<div class="note">PDF export is not implemented in this demo (CSV export above is real). Newest records first.</div>
</div></body></html>"""
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Screen 2 — Policy Configuration (read-only)
# ---------------------------------------------------------------------------
@app.get("/policy.json")
async def policy_json():
    """Raw POLICY dict, consumed by the Screen 2 tab in relay-screen1-live.html."""
    return JSONResponse(policy_filter.POLICY)


@app.get("/policy-config", response_class=HTMLResponse)
async def policy_config_page():
    p = policy_filter.POLICY
    whitelist_html = "".join(f"<li>{_esc(x)}</li>" for x in p["category_whitelist"])
    blacklist_html = "".join(f"<li>{_esc(x)}</li>" for x in p["category_blacklist"])

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Relay — Policy Configuration (Screen 2)</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>{AUDIT_PAGE_STYLE}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px;}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;}}
.card h3{{font-family:'Space Grotesk',sans-serif;font-size:13px;margin:0 0 12px;color:var(--text);}}
.field{{margin-bottom:14px;}}
.field .k{{color:var(--text-faint);font-size:11px;margin-bottom:3px;}}
.field .v{{font-size:16px;color:var(--text);}}
.editable-badge{{display:inline-block;font-size:9.5px;padding:1px 6px;border-radius:var(--radius);border:1px solid var(--brand);color:var(--brand);margin-left:8px;vertical-align:middle;}}
.locked-card{{background:#231B1B;border:1px solid rgba(201,97,74,.45);opacity:.92;}}
.locked-card h3{{color:var(--rust);display:flex;align-items:center;gap:8px;}}
.locked-badge{{display:inline-block;font-size:9.5px;padding:1px 6px;border-radius:var(--radius);border:1px solid var(--rust);color:var(--rust);}}
.locked-card ul{{color:#B08A82;margin:0;padding-left:18px;}}
.locked-card li{{margin-bottom:4px;}}
.locked-note{{color:#8C6E68;font-size:11px;margin-top:10px;padding-top:10px;border-top:1px dashed rgba(201,97,74,.3);}}
ul{{margin:0;padding-left:18px;}}
li{{margin-bottom:4px;color:var(--text-dim);}}
</style></head>
<body><div class="wrap">
<header>
  <div>
    <div class="brand"><span>RE</span>LAY — Policy Configuration</div>
    <div class="brand-sub">Screen 2 — currently effective Policy Matrix values (read-only in this demo; no save/edit action is wired up)</div>
  </div>
  <div><a href="/">Screen 1</a> &nbsp;·&nbsp; <a href="/audit-ledger">Screen 3</a></div>
</header>

<div class="grid">
  <div class="card">
    <h3>Per-transaction price cap <span class="editable-badge">lender-editable</span></h3>
    <div class="field"><div class="k">max spend per single data purchase</div>
      <div class="v">{p['per_tx_cap_drops']:,} drops <span style="color:var(--text-faint);font-size:12px;">(≈ ${p['per_tx_cap_drops']/100000:.2f})</span></div></div>
  </div>

  <div class="card">
    <h3>Per-applicant cumulative cap <span class="editable-badge">lender-editable</span></h3>
    <div class="field"><div class="k">max total spend per applicant across all purchases</div>
      <div class="v">{p['per_applicant_cumulative_cap_drops']:,} drops <span style="color:var(--text-faint);font-size:12px;">(≈ ${p['per_applicant_cumulative_cap_drops']/100000:.2f})</span></div></div>
  </div>

  <div class="card">
    <h3>Category whitelist <span class="editable-badge">lender-editable</span></h3>
    <div class="field"><div class="k">selections agent may query within</div><ul>{whitelist_html}</ul></div>
  </div>

  <div class="card">
    <h3>Vendor trust threshold <span class="editable-badge">lender-editable</span></h3>
    <div class="field"><div class="k">vendors scoring below this are excluded / flagged for human review, never auto-approved</div>
      <div class="v">{p['trust_min']} / 100</div></div>
  </div>

  <div class="card locked-card" style="grid-column:1/-1;">
    <h3>No qualifying candidate <span class="locked-badge">HARD STOP</span></h3>
    <p>Stop before purchase and flag the request for human review. Never force-select a vendor or relax policy automatically.</p>
  </div>
  <div class="card locked-card" style="grid-column:1/-1;">
    <h3>🔒 Category blacklist <span class="locked-badge">LENDER-LOCKED — NOT EDITABLE</span></h3>
    <ul>{blacklist_html}</ul>
    <div class="locked-note">Per PRD Section 5: this is a hard, non-negotiable constraint. The Agent cannot override it "for business need," and per Section 8 it is not a judgment call the Agent makes at runtime — it ships hardcoded and stays that way in this UI.</div>
  </div>
</div>

<div class="note">This screen intentionally has no save/submit control — Section 6 only requires it to <em>show</em> current values, not to edit them, for this demo pass.</div>
</div></body></html>"""
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(os.path.dirname(__file__), "relay-screen1-live.html")) as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
