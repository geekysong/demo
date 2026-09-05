"""
Relay PRD v2 — Section 3 (Pricing), applied to each completed purchase.

Modeled as a BILLING LEDGER, not a second on-chain payment: the real XRPL
Payment (see orchestrator.py's run_real_flow) always pays the FULL vendor
price to the vendor — that's the actual x402 settlement Section 4 Steps 5-7
describe, and it has to happen in full for the vendor to release the data.
What varies is who Relay bills for that cost afterward, plus Relay's own
platform fee. In production this would be a separate invoice / payment-
processor charge to the lender, not something re-done on-chain per purchase.
This module only tracks that billing math — it never touches XRPL.

Modeling choices (the PRD doesn't fully specify these, so stating them
explicitly rather than burying the assumption):
  - Trial credit covers the underlying VENDOR DATA COST only. It does NOT
    waive Relay's own platform fee, which this demo treats as due on every
    purchase regardless of trial status.
  - Fee model: cost + 17.5% (midpoint of the PRD's stated 15-20% range),
    not the flat $0.50-2 alternative. Percentage scales naturally with the
    Policy Matrix's own price cap, which is the more demonstrable choice.
  - Single global account (no lender/tenant model exists in this demo), so
    there is one trial-credit balance, not one per lender.
  - "No separate contract signing step" (PRD) -> the mode flips from trial
    to pay-as-you-go automatically, in the same function call, the moment
    the credit hits zero.
  - State is in-memory only and resets on server restart, same limitation
    as the per-applicant cumulative-spend counter in policy_filter.py.

Demo FX convention used throughout this codebase: 100,000 drops == $1.00.
"""
import threading

DROPS_PER_USD = 100_000
TRIAL_CREDIT_DROPS = 50 * DROPS_PER_USD  # PRD Section 3: "First $50 of procurement covered by Relay"
PLATFORM_FEE_PCT = 0.175  # midpoint of PRD's stated 15-20% range

_LOCK = threading.Lock()
_STATE = {
    "trial_credit_remaining_drops": TRIAL_CREDIT_DROPS,
    "billing_mode": "trial",  # -> "pay_as_you_go" once credit is exhausted
}


def get_billing_state() -> dict:
    with _LOCK:
        return dict(_STATE)


def bill_purchase(price_drops: int) -> dict:
    """Apply Section 3 pricing to one completed purchase. Mutates the
    running trial-credit balance / mode, and returns a receipt describing
    exactly how this purchase was billed."""
    platform_fee_drops = round(price_drops * PLATFORM_FEE_PCT)
    with _LOCK:
        trial_before = _STATE["trial_credit_remaining_drops"]
        mode_before = _STATE["billing_mode"]
        covered_by_trial_drops = min(trial_before, price_drops) if mode_before == "trial" else 0
        billed_data_cost_drops = price_drops - covered_by_trial_drops
        _STATE["trial_credit_remaining_drops"] = max(0, trial_before - price_drops)
        if _STATE["trial_credit_remaining_drops"] == 0:
            _STATE["billing_mode"] = "pay_as_you_go"
        mode_after = _STATE["billing_mode"]

    return {
        "vendor_price_drops": price_drops,
        "platform_fee_drops": platform_fee_drops,
        "covered_by_trial_credit_drops": covered_by_trial_drops,
        "billed_data_cost_drops": billed_data_cost_drops,
        "billed_total_drops": billed_data_cost_drops + platform_fee_drops,
        "billing_mode_before": mode_before,
        "billing_mode_after": mode_after,
        "trial_credit_remaining_drops": _STATE["trial_credit_remaining_drops"],
    }


def set_trial_credit_remaining_for_testing(drops: int) -> None:
    """TEST-ONLY. Lets a regression test push the trial balance near zero
    without needing ~1000 sequential real XRPL purchases to exhaust the
    $50 credit at 5000 drops each. Not called from any HTTP route."""
    with _LOCK:
        _STATE["trial_credit_remaining_drops"] = max(0, drops)
        _STATE["billing_mode"] = "trial" if drops > 0 else "pay_as_you_go"
