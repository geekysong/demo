"""
Relay PRD v2 — Steps 2-4 (Policy Matrix filter), enforcing Section 5 in full.

orchestrator.py imports `filter_candidates` and `NoQualifyingCandidate` from
this file and calls it FRESH ON EVERY TRIGGER (see run_real_flow() in
orchestrator.py) — Step 4 ("Relay Agent filters candidates against the Policy
Matrix; selects one vendor") is evaluated per procurement request, not once
at server boot.

Rules enforced, one check per Section 5 row that is expressible as a
candidate-level filter (Trigger threshold and Explainability requirement are
NOT enforced here — see README_AUDIT.md "What's simplified" for why):

  1. Category blacklist          -> hard, checked first, non-negotiable,
                                     agent cannot override "for business need"
  2. Category whitelist          -> hard, candidate must be in the allowed set
  3. Vendor trust threshold      -> hard; below threshold = excluded, never
                                     auto-approved (never silently relaxed)
  4. Data freshness window       -> max staleness for this demo (PRD says the
                                     real threshold is category-specific and
                                     lender-set; this demo uses one shared
                                     threshold — see simplifications note)
  5. Per-transaction price cap   -> hard limit on this single purchase
  6. Per-applicant cumulative cap-> hard limit + running counter across
                                     purchases for the same applicant

A candidate collects EVERY reason it fails (not just the first) so the audit
trail shows the complete picture, matching Section 5's "candidate list +
rejection reasons" requirement for audit logging.

Each candidate needs every key below, or filter_candidates() will KeyError:
  id             - short string, unique per candidate, e.g. "A"
  name           - vendor display name
  price_usd      - display-only, not wired to a real FX rate anywhere
  price_drops    - the number actually used for the on-chain XRP payment
                    (1 XRP = 1,000,000 drops)
  trust_score    - 0-100, compared against POLICY["vendor_trust_threshold"]
  freshness_days - compared against POLICY["freshness_max_days"]
  schema         - free text, shown in the UI, not filtered on
  category       - must be in POLICY["category_whitelist"] AND must not be in
                   POLICY["category_blacklist"] to pass
"""

# ---------------------------------------------------------------------------
# Default candidate fixtures mirror the two live resources declared in
# marketplace.py. A normal /run refreshes these from their real unpaid 402
# declarations before filtering; these fixtures keep startup and offline
# testing deterministic.
# ---------------------------------------------------------------------------
from marketplace import fallback_candidates

CANDIDATES = fallback_candidates()

POLICY = {
    # Section 5 row: "Vendor trust threshold"
    "trust_min": 70,
    # Section 5 row: "Data freshness window" (demo: one shared threshold,
    # not the category-specific staleness table the PRD describes)
    "freshness_max_days": 30,
    # Section 5 row: "Category whitelist" — the exact 5 categories listed
    "category_whitelist": [
        "income_verification",
        "employment_verification",
        "bank_flow_patterns",
        "business_registration_status",
        "industry_income_benchmarks",
    ],
    # Section 5 row: "Category blacklist" — the exact 3 categories listed.
    # Screen 2 renders this as lender-locked / not editable.
    "category_blacklist": [
        "geographic_layer_no_income_context",
        "surname_ethnicity_database",
        "social_media_profiling",
    ],
    # Section 5 row: "Per-transaction price cap". 100_000 drops == $1.00 at
    # this demo's implied FX rate (matches the "$1.00" cap already printed
    # in relay-screen1-live.html's intake panel).
    "per_tx_cap_drops": 100_000,
    # Section 5 row: "Per-applicant cumulative cap". Demo value: $5.00
    # equivalent across all purchases for one applicant.
    "per_applicant_cumulative_cap_drops": 500_000,
    # Section 5 row: "Trigger threshold" — the gray-zone score band that
    # must contain applicant_score for the Agent to fire at all. Demo
    # values chosen so the default 612 shown in relay-screen1-live.html's
    # intake panel falls inside the band.
    "gray_zone_score_min": 580,
    "gray_zone_score_max": 669,
}

# ---------------------------------------------------------------------------
# Section-5 guardrail test fixtures. These are NOT production Bazaar data —
# each is built to trip exactly one hard rule so its enforcement can be shown
# with a real function call and a real response, not a code-reading exercise.
# orchestrator.py's POST /run accepts a "scenario" field selecting one of
# these instead of CANDIDATES/POLICY above.
# ---------------------------------------------------------------------------
TEST_SCENARIOS = {
    # Section 5 row: "Per-transaction price cap" — Hard limit.
    # One candidate priced above the $1.00 cap, one ordinary control
    # candidate that would otherwise be the cheapest-passing pick, so a
    # human reader can see the cap fire in isolation (not confused with
    # "nothing qualified").
    "over_cap": {
        "candidates": [
            {"id": "X1", "name": "PricePush Analytics", "price_usd": 1.50, "price_drops": 150_000,
             "trust_score": 88, "freshness_days": 3, "schema": "income.v3", "category": "income_verification"},
            {"id": "A", "name": "PayrollPing API", "price_usd": 0.05, "price_drops": 5000,
             "trust_score": 82, "freshness_days": 5, "schema": "income.v2", "category": "income_verification"},
        ],
    },
    # Section 5 row: "Category blacklist" — Hard blacklist, non-negotiable.
    # One candidate in a blacklisted category (geographic data w/o income
    # context — the PRD's protected-class-proxy risk case), one ordinary
    # control candidate.
    "blacklist": {
        "candidates": [
            {"id": "X2", "name": "GeoProxy Data Co", "price_usd": 0.02, "price_drops": 2000,
             "trust_score": 95, "freshness_days": 1, "schema": "geo.v1",
             "category": "geographic_layer_no_income_context"},
            {"id": "A", "name": "PayrollPing API", "price_usd": 0.05, "price_drops": 5000,
             "trust_score": 82, "freshness_days": 5, "schema": "income.v2", "category": "income_verification"},
        ],
    },
    # Section 5 row: "No qualifying candidate" — Hard stop condition.
    # Every candidate fails at least one rule; none may be force-selected.
    "no_candidate": {
        "candidates": [
            {"id": "X1", "name": "PricePush Analytics", "price_usd": 1.50, "price_drops": 150_000,
             "trust_score": 88, "freshness_days": 3, "schema": "income.v3", "category": "income_verification"},
            {"id": "B", "name": "SlowData Co", "price_usd": 0.04, "price_drops": 4000,
             "trust_score": 60, "freshness_days": 45, "schema": "income.v1", "category": "income_verification"},
            {"id": "X2", "name": "GeoProxy Data Co", "price_usd": 0.02, "price_drops": 2000,
             "trust_score": 95, "freshness_days": 1, "schema": "geo.v1",
             "category": "geographic_layer_no_income_context"},
        ],
    },
}


def in_gray_zone(score, policy=None) -> bool:
    """Section 5 row: 'Trigger threshold — only fires when applicant score
    falls in a pre-defined gray zone band.' Read-only flag from the
    lender's risk engine, not something the Agent reinterprets — this is
    a fixed band check, not a filter the Agent can loosen."""
    policy = policy or POLICY
    lo, hi = policy.get("gray_zone_score_min"), policy.get("gray_zone_score_max")
    if lo is None or hi is None:
        return True  # no band configured -> nothing to gate on
    return lo <= score <= hi


def discover_candidates(candidates, data_type):
    """Section 4 Steps 2-3: 'Agent parses request into a Bazaar discovery
    query' / 'Bazaar returns candidate vendors'. In production this would
    be a live query against the x402 Bazaar scoped to the requested data
    type; here it's a category-match filter over the static demo list,
    which is the closest honest stand-in without an external Bazaar to
    call. Candidates that don't match were never "returned" by discovery,
    which is a different (earlier) rejection than failing the Policy
    Matrix in Step 4.

    Returns (matched, unmatched). If data_type is falsy, everything is
    considered matched (no discovery scoping requested).
    """
    if not data_type:
        return list(candidates), []
    matched = [c for c in candidates if c["category"] == data_type]
    unmatched = [c for c in candidates if c["category"] != data_type]
    return matched, unmatched


class NoQualifyingCandidate(RuntimeError):
    """PRD Section 5: 'If zero candidates pass all filters, Agent must halt
    and escalate to a human — it may not relax its own criteria to force a
    purchase.'"""


def filter_candidates(candidates=None, policy=None, applicant_spent_drops=0):
    """Evaluate every candidate against every Section-5 rule.

    applicant_spent_drops: running total already spent for this applicant
    across prior purchases, used to enforce the per-applicant cumulative cap
    (Section 5: "Hard limit + counter"). Defaults to 0 (no prior spend).
    """
    candidates = candidates or CANDIDATES
    policy = policy or POLICY

    accepted, rejected = [], []
    for c in candidates:
        reasons = []

        # 1. Category blacklist — checked first, non-negotiable.
        if c["category"] in policy.get("category_blacklist", ()):
            reasons.append(
                f"category '{c['category']}' is on the compliance blacklist "
                f"(non-negotiable, agent cannot override)"
            )

        # 2. Category whitelist.
        if c["category"] not in policy["category_whitelist"]:
            reasons.append(f"category '{c['category']}' not in whitelist")

        # 3. Vendor trust threshold — below threshold, never auto-approved.
        if c["trust_score"] < policy["trust_min"]:
            reasons.append(
                f"trust {c['trust_score']} < min {policy['trust_min']} "
                f"(excluded, not auto-approved)"
            )

        # 4. Data freshness window.
        if c["freshness_days"] > policy["freshness_max_days"]:
            reasons.append(
                f"freshness {c['freshness_days']}d > max {policy['freshness_max_days']}d"
            )

        # 5. Per-transaction price cap.
        cap = policy.get("per_tx_cap_drops")
        if cap is not None and c["price_drops"] > cap:
            reasons.append(
                f"price {c['price_drops']} drops > per-transaction cap {cap} drops"
            )

        # 6. Per-applicant cumulative cap.
        cum_cap = policy.get("per_applicant_cumulative_cap_drops")
        if cum_cap is not None and (applicant_spent_drops + c["price_drops"]) > cum_cap:
            reasons.append(
                f"cumulative spend {applicant_spent_drops} + price {c['price_drops']} "
                f"> per-applicant cap {cum_cap} drops"
            )

        (rejected if reasons else accepted).append(
            {**c, "rejection_reasons": reasons} if reasons else c
        )

    if not accepted:
        exc = NoQualifyingCandidate(
            "zero candidates passed the Policy Matrix — halt and escalate, "
            "per PRD Section 5. Not implemented: this demo has no human "
            "escalation channel, it just raises."
        )
        exc.rejected = rejected  # let callers log full rejection reasons for the audit trail
        raise exc

    # Tie-break rule: cheapest accepted candidate wins.
    # NOTE: this isn't specified anywhere in the PRD — it's an assumption
    # to get a deterministic single "selected" vendor. Change it here if
    # you want a different rule (e.g. highest trust_score instead).
    selected = sorted(accepted, key=lambda c: c["price_drops"])[0]
    return selected, rejected


if __name__ == "__main__":
    import json
    import sys

    scenario = sys.argv[1] if len(sys.argv) > 1 else None
    if scenario:
        fixture = TEST_SCENARIOS[scenario]
        cands = fixture["candidates"]
        pol = fixture.get("policy", POLICY)
    else:
        cands = CANDIDATES
        pol = POLICY

    try:
        selected, rejected = filter_candidates(cands, pol)
        print("selected:", json.dumps(selected, indent=2))
        print("rejected:", json.dumps(rejected, indent=2))
    except NoQualifyingCandidate as e:
        print("NoQualifyingCandidate:", e)
