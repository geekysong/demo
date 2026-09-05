# Relay PRD v2 — implementation gap review and next-step plan

Date: 2026-09-04  
Compared:

- PRD: `/Users/dongya/Downloads/relay-prd-v2.md`
- Current UI: `/Users/dongya/Downloads/demo/relay-screen1-live.html`
- Supporting implementation: `orchestrator.py`, `policy_filter.py`, `billing.py`, and the rendered app at `http://127.0.0.1:8000/`

## Executive assessment

The current build is a strong hackathon proof of the x402/XRPL payment loop and audit trail. It demonstrates a structured trigger, server-side policy filtering, a real HTTP 402 flow, XRP Testnet settlement, independent on-chain confirmation, billing calculations, and a populated audit ledger.

It is not yet a complete implementation of PRD v2. The biggest gaps are:

1. Bazaar discovery and counterparty selection are still mocked.
2. The paid endpoint and quote are bound to one vendor selected at server startup, not the vendor selected for the current request.
3. The compliance-critical explainability rule is not enforced.
4. Screen 2 labels four values as lender-editable but provides no edit/save workflow.
5. The purchased supplemental data is received by the backend but not shown to the lender in the Screen 1 receipt.
6. Screen 3 has CSV export but no PDF export.

## PRD comparison

| PRD area | Status | Current evidence | Gap / consequence |
|---|---|---|---|
| Product boundary: procurement only, no credit decision | Meets | No scoring, approval, or denial logic; trigger score is used only to decide whether procurement fires | Preserve this boundary in all future UI copy and APIs |
| Structured lender request | Meets for demo | Screen 1 posts score, data type, region, freshness, and trigger reason | Values are fixed in the UI; acceptable because Screen 1 is a live view, not specified as an intake form |
| Bazaar discovery | Does not meet | `policy_filter.CANDIDATES` is a static list; discovery only filters it by category | Core challenge step 2 is simulated, not demonstrated |
| Policy filtering and rejection reasons | Mostly meets | Price, cumulative spend, whitelist, blacklist, trust, and freshness checks run server-side; rejection reasons are logged | Explainability metadata is not checked; freshness is global rather than category-specific |
| Selected counterparty drives 402 quote/payment | Does not fully meet | Real 402/XRP flow works, but `/income-verification` price, description, and vendor are fixed from `PRODUCTION_SELECTED` at startup | A request-time selection can diverge from the vendor actually paid; this becomes critical once policy is editable or discovery is live |
| XRP Ledger settlement and receipt | Meets for XRP demo | Real XRP Testnet payment, transaction hash, balance checks, and independent validation are present | RLUSD is not implemented, but PRD permits XRP **or** RLUSD, so XRP alone is sufficient |
| Deliver useful data to lender | Partial | Backend receives and stores the paid response in live state | Receipt says “Data delivered” but does not render the returned verification result or reason codes; no separate delivery API/webhook |
| Pricing | Mostly meets | $50 trial credit, 17.5% fee, and automatic trial-to-PAYG transition are modeled | State is global/in-memory; platform fee is ledger-only; subscription is omitted. Reasonable demo simplifications if disclosed |
| Screen 1 live shopping | Mostly meets | Trigger, candidates, selection, quote/payment/settlement rail, and receipt are present | Terminal phases such as `not_triggered`, `escalated_no_candidate`, and `policy_test_complete` are not in the UI phase model, so polling can continue indefinitely and failure/escalation details are not rendered cleanly |
| Screen 2 policy configuration | Does not meet | Values and locked blacklist display correctly from `/policy.json` | PRD explicitly says per-transaction cap, cumulative cap, whitelist, and trust threshold are lender-editable. The current note claiming display-only is sufficient is inconsistent with the PRD |
| Screen 3 audit ledger | Mostly meets | Required columns, candidate details, rejection reasons, transaction links, and CSV export are present | PDF export is missing; human escalation is only a status/audit record, not a real notification or work queue |
| Audit integrity | Meets for demo | Append-only JSONL plus XRPL transaction corroboration | Audit JSONL is local mutable storage, and request/billing counters are not durable or tenant-scoped |

## Recommended execution plan

### Phase 1 — close the demo-breaking correctness gaps

Goal: ensure every path shown in the UI is truthful, terminal, and useful.

1. Add terminal UI handling for `not_triggered`, `escalated_no_candidate`, `policy_test_complete`, `failed`, and `settlement_unconfirmed`.
2. Stop polling on every terminal state and render a clear outcome card with rejection/escalation reasons.
3. Render the purchased data payload in the Screen 1 delivery card, including vendor, freshness, result, and discrete reason codes.
4. Make response rendering safe: escape all vendor/Bazaar/API strings before inserting them into HTML.
5. Add regression tests for success, no-candidate escalation, out-of-band trigger, policy-test completion, and settlement failure/unconfirmed paths.

Acceptance criteria:

- Every run ends in a visible terminal state and stops polling.
- A successful run shows both the data product and the payment/audit receipt.
- A no-candidate run proves that no payment was attempted and shows all rejection reasons.
- Untrusted candidate metadata cannot inject HTML or script into the UI.

### Phase 2 — enforce the full compliance policy

Goal: close the highest-risk PRD policy gaps before integrating external vendors.

1. Extend the candidate schema with explainability metadata such as `supports_reason_codes`, `output_kind`, and intended `decision_use`.
2. Enforce the adverse-use rule server-side: reject black-box scores when the request says the data may support an adverse decision; allow the documented relaxed path only for approval-support use.
3. Replace the global freshness limit with a category-specific staleness table, while allowing a request to tighten but never loosen the configured limit.
4. Add tests proving blacklist and explainability rules cannot be weakened through request payloads or Screen 2.

Acceptance criteria:

- A black-box adverse-use candidate is rejected with a precise audit reason.
- Category-specific freshness rules are visible in policy output and enforced.
- Blacklist and explainability constraints have no writable API surface.

### Phase 3 — make Screen 2 genuinely lender-editable

Goal: meet the explicit Screen 2 requirement without exposing compliance-critical settings.

1. Add form controls for per-transaction cap, cumulative cap, whitelist selections, and trust threshold.
2. Add a validated policy update endpoint that accepts only those four fields.
3. Keep blacklist and explainability constraints server-owned and immutable.
4. Persist editable policy values across restarts for the demo, ideally in a small SQLite database or a validated JSON config file.
5. Show save success, validation errors, and an “effective from” timestamp/version.

Acceptance criteria:

- Saved values survive restart and immediately govern new runs.
- Attempts to submit blacklist or explainability changes are rejected and audited.
- Screen 1 and Screen 2 read the same effective policy version.

### Phase 4 — replace simulated discovery with a real Bazaar adapter

Goal: demonstrate genuine request-time discovery and selection.

1. Define a provider-neutral candidate contract: vendor ID/name, endpoint, price/asset, input/output schema, category, region coverage, freshness, trust score, and explainability metadata.
2. Implement a Bazaar client/adapter that converts the structured lender request into a discovery query and normalizes returned services.
3. Keep the current static candidate set only as an explicit offline-demo fallback, visibly labeled as simulated.
4. Bind the selected candidate's actual endpoint, quote, price, asset, and pay-to address to the request-time x402 flow.
5. Verify the 402 response matches the selected vendor before signing; abort and audit on any mismatch.

Acceptance criteria:

- The candidate list comes from a recorded live Bazaar response or a clearly labeled fallback.
- Changing the request changes the discovered candidate set.
- The selected candidate, quoted merchant, paid merchant, price, and delivered payload all match in one audit record.

### Phase 5 — finish the audit/demo package

Goal: make the demo easy to judge and export.

1. Add PDF export for the audit ledger, with the same fields and rejection details as CSV.
2. Add a visible human-review queue/status for no-candidate escalations; for hackathon scope, an in-app queue is enough.
3. Add request filters/search and a detail drawer so the ledger remains usable beyond a few dozen records.
4. Add a deterministic demo mode that exercises success, blacklist rejection, explainability rejection, and no-candidate escalation without making unnecessary real payments.
5. Update `README_AUDIT.md` so Screen 2 is no longer marked compliant while read-only.

Acceptance criteria:

- CSV and PDF exports contain the same required audit fields.
- A judge can run the four canonical scenarios from the UI and understand the outcome without reading logs.

## Suggested order for the next implementation pass

For the next coding pass, implement Phases 1 and 2 together. They close visible state bugs and the compliance-critical explainability gap without depending on an external Bazaar service. Then implement Screen 2 editing. Start the live Bazaar phase as soon as the discovery endpoint/tool and schema are available, because it is the largest remaining challenge-level gap.

## Input needed before Phase 4

Please provide the x402 Bazaar discovery endpoint/tool, authentication method if any, and one sample candidate response. If no live Bazaar interface is available, the recommended fallback is to build the adapter contract now and use a recorded fixture clearly labeled “simulated discovery” in the UI.

