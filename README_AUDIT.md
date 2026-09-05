# Relay demo — PRD v2 compliance audit & regression test log

## Round 5 update — Section 3 Pricing + Step 1 structured request, now fixed

Per PM triage, these two gaps (previously listed below as "not implemented")
were closed this round, plus two cheap items bundled in because they're the
same PRD rows / same fix:

1. **Section 3 Pricing** — `billing.py` (new file). $50 trial credit +
   17.5% platform fee, applied as a billing ledger (not a second on-chain
   payment — see the file's docstring for why) on every completed purchase.
   Exposed at `GET /billing`, shown in Screen 1's receipt.
2. **Section 4 Step 1 structured request** — `POST /run` now accepts
   `applicant_score`, `data_type`, `applicant_region`,
   `freshness_requirement_days`. Screen 1's "Run flow" button sends the
   exact values its intake panel displays (612 / income_verification /
   US-TX / 30) instead of an empty body.
3. **Section 5 "Trigger threshold"** (bundled with #2) — `applicant_score`
   is now checked against a real gray-zone band (`policy_filter.in_gray_zone()`,
   580–669) before discovery/filtering even runs.
4. **Section 4 Steps 2-3 discovery scoping** (bundled with #2) —
   `data_type` now scopes which candidates are even "returned" by the
   (still-mocked) Bazaar via `policy_filter.discover_candidates()`, before
   Step 4's Policy Matrix runs over the result. A category mismatch is now
   a distinct, earlier rejection reason from failing the Policy Matrix.
5. **`freshness_requirement_days`** (per-request) tightens — never
   loosens — the server's configured `freshness_max_days` for that run.
6. **Screen 1's hardcoded policy-strip** now fetches `/policy.json` on load,
   same source of truth Screen 2 uses, instead of static text that could
   drift from the real `POLICY` dict.

### Regression test evidence (this round)

All re-run against a freshly restarted server:

| Test | Result |
|---|---|
| `over_cap` / `blacklist` / `no_candidate` guardrail scenarios | **Unaffected** — new `applicant_score`/`data_type` defaults only apply to `scenario="default"`; guardrail fixtures still see `None` for these, exactly as before the change. Re-ran all three, same rejection reasons as prior rounds |
| `applicant_score=300` (outside gray zone) | `phase: not_triggered`, error message names the configured band `[580, 669]`, discovery/filtering never runs |
| `data_type="bank_flow_patterns"` (no candidate has this category) | `phase: escalated_no_candidate`, all 3 candidates marked "not returned by Bazaar discovery for data_type=...", never reached the Policy Matrix at all |
| `data_type="credit_score"` (only OffScope Bureau matches) | Discovery correctly narrows to just `C`; Policy Matrix *still* rejects it for `category not in whitelist` — confirms discovery and Step 4 filtering are two independent, correctly-layered checks |
| `freshness_requirement_days=3` (tighter than the server's 30-day default) | PayrollPing (5-day-old data), previously always the winner, now correctly rejected: `"freshness 5d > max 3d"` |
| Real purchase via the actual Screen 1 "Run flow" button (not curl) | tx `6568EF129DCACFFD894CD1DF996EE65B7B272B410B0627B1668DCD22810899DC`, confirmed `tesSUCCESS` independently on https://testnet.xrpl.org/transactions/6568EF129DCACFFD894CD1DF996EE65B7B272B410B0627B1668DCD22810899DC. Network tab confirms the POST body carried `applicant_score:612, data_type:"income_verification", applicant_region:"US-TX", freshness_requirement_days:30` — display and evaluation are now the same data |
| Billing math on that purchase | `platform_fee_drops: 875` (5000 × 17.5%, rounded), fully `covered_by_trial_credit_drops: 5000` (trial not yet exhausted), `billed_total_drops: 875`, `trial_credit_remaining_drops` correctly decremented |
| Trial-credit exhaustion + auto-conversion (direct call to `billing.bill_purchase()` in an isolated process, credit pre-set near zero via the test-only `set_trial_credit_remaining_for_testing()` helper — **not** a live-server test, since exhausting the real $50 credit through actual purchases would need ~1000 sequential real XRPL payments) | Purchase overlapping the boundary split correctly (`covered_by_trial_credit_drops: 3000`, `billed_data_cost_drops: 2000`), `billing_mode` flipped `trial → pay_as_you_go` in the same call (no separate contract-signing step, per PRD), and the next purchase billed in full (`billed_total_drops: 5875`) |
| Audit ledger / CSV schema | New fields (`applicant_score`, `data_type`, `applicant_region`, `freshness_requirement_days`, `platform_fee_drops`, `billed_total_drops`, `billing_mode_after`) present in both `/audit` JSON and `/audit.csv` header |

### What's still a modeled choice, not a gap (stated explicitly so it isn't mistaken for one)

- Trial credit covers vendor data cost only; Relay's own platform fee is
  billed even during trial. The PRD doesn't say either way — this is our
  assumption, changeable in `billing.py` if wrong.
- Fee is percentage-based (17.5%, PRD's stated 15-20% midpoint), not the
  flat $0.50-2/purchase alternative the PRD also allows.
- One global billing account — no lender/tenant model exists in this demo,
  so there's one trial-credit balance, not one per lender.
- The platform fee is never actually collected on-chain from anyone — it's
  a billing-ledger number only. A real deployment would invoice the lender
  separately; re-doing that as a second XRPL microtransaction per purchase
  was judged out of scope for a demo pass.

---


This file is referenced from code comments in `policy_filter.py` and
`orchestrator.py` ("see README_AUDIT.md"). It didn't exist until this pass —
that dangling reference was itself a bug found during this regression sweep
and is now fixed by this file existing.

Scope: everything built across rounds 3–5 (real x402/XRPL settlement, Policy
Matrix enforcement, Screen 2/3, tabbed UI). Checked against
`relay-prd-v2.md` section by section. All ✅ items below were re-verified in
this session with a running server and real network/chain calls — not read
off the code.

---

## Regression test run (this session)

Server restarted clean, then:

| Test | Result |
|---|---|
| `GET /health`, `/policy.json`, `/audit`, `/audit.csv`, `/policy-config`, `/audit-ledger`, `/` | all HTTP 200 |
| `POST /run {"scenario":"totally_made_up"}` | HTTP 400, rejected with known scenario list — no silent fallback |
| `scenario:"over_cap"` | `policy_test_complete` — over-cap candidate rejected, control candidate selected, no payment attempted |
| `scenario:"blacklist"` | `policy_test_complete` — blacklisted candidate rejected, control candidate selected |
| `scenario:"no_candidate"` | `escalated_no_candidate` — all 3 fail, `NoQualifyingCandidate` raised, no payment attempted, audit entry written |
| `scenario:"default"` (real purchase) | `delivered` — tx `8A834E52CE1633431E930E8A2C16000537C4F54E98F8C8205E99BF5D0F9DB846`, independently confirmed `tesSUCCESS` on https://testnet.xrpl.org/transactions/8A834E52CE1633431E930E8A2C16000537C4F54E98F8C8205E99BF5D0F9DB846 |
| Injection attempt: `POST /run` body included `"policy":{"category_blacklist":[]}` and a fabricated `"candidates":[{"id":"HACK",...}]` alongside `"scenario":"blacklist"` | **Ignored entirely.** Server used its own server-side `blacklist` fixture (GeoProxy rejected, PayrollPing selected); the injected candidate/policy never appeared anywhere. Confirms a caller cannot loosen Section 5's hard rules through the API — matches "compliance-critical rows must be hardcoded, the Agent does not get discretion" |
| Per-applicant cumulative cap | Direct call to the production `filter_candidates()` with a manufactured `applicant_spent_drops` near the cap → all 3 candidates correctly rejected with `"cumulative spend ... > per-applicant cap ..."`; control call with `spent=0` correctly selects PayrollPing. **Caveat**: this exercised the function directly, not through a full HTTP run — see gap list below for why |
| Audit ledger consistency | `audit_log.jsonl` line count matches `/audit.csv` row count minus header (12 records / 13 CSV lines incl. header) |
| Screen 1/2/3 tabs | Manually clicked through all three in the browser after the regression run — Screen 1 flow state persisted, Screen 2 pulled live `/policy.json`, Screen 3 showed all 12 records with working explorer links |

Nothing above required touching business logic — this was pure verification.

---

## Section-by-section PRD compliance

### Section 3 — Pricing: ✅ **implemented (round 5)**
Trial credit ($50) + platform fee (17.5%, cost-based) now applied via
`billing.py` on every completed purchase — see the round-5 section above for
the full test evidence. Audit dashboard subscription is still not modeled
(no subscription/billing-for-Relay's-own-product concept exists anywhere;
low priority, nobody has asked for it and it doesn't affect the procurement
flow itself).

### Section 4 — End-to-end flow
| Step | Status |
|---|---|
| 1. Structured request in (data type, region, freshness requirement, score band) | ✅ **implemented (round 5)**. `POST /run` takes `applicant_score`, `data_type`, `applicant_region`, `freshness_requirement_days`; Screen 1 sends its displayed values instead of an empty body. `applicant_region` is still passthrough/logged only — no candidate field exists to filter on region in this demo's data model |
| 2–3. Bazaar discovery query + candidate list | **Still mocked** — `policy_filter.CANDIDATES` remains a static Python list, there is no live x402 Bazaar/registry call. What changed in round 5: `data_type` now scopes which of those static candidates are "returned" by discovery (`policy_filter.discover_candidates()`), so the step is at least responsive to the request instead of always returning the same fixed 3 regardless of input |
| 4. Filter via Policy Matrix | ✅ real, re-verified this session |
| 5. 402 + quote | ✅ real (scenario=`default` only) |
| 6. Wallet pays (XRP or RLUSD) | ✅ real for **XRP only**. RLUSD is untested/unimplemented — inherited limitation, unchanged since round 1's README |
| 7. Settles in 3–5s, receipt | ✅ real, but observed latency is closer to ~8–10s end-to-end (facilitator verify+settle + independent chain confirmation loop), not 3–5s — same gap the original README already flagged |
| 8. Vendor confirms, data + audit trail delivered | ✅ real for the audit ledger. "Deliver to lender's dashboard/API" = the Screen 1 UI itself; there's no separate lender-facing API/webhook — acceptable for a demo, but worth naming as a simplification |

### Section 5 — Policy Matrix, row by row
| Row | Status |
|---|---|
| Trigger threshold | ✅ **implemented (round 5)** — `applicant_score` is checked against `policy_filter.in_gray_zone()` (580–669 band) before discovery/filtering runs. Out-of-band halts with `phase: not_triggered`, tested this round |
| Per-transaction price cap | ✅ hard limit, tested this session |
| Per-applicant cumulative cap | ✅ implemented; tested via direct function call this session (see caveat above — no HTTP-level test exists because the guardrail-test scenarios deliberately don't execute real payment, so they never call `add_applicant_spend()`. Testing this end-to-end through real HTTP runs would need ~100 sequential real purchases to exhaust the 500,000-drop demo cap, which isn't practical) |
| Category whitelist | ✅ hard whitelist, tested every run (OffScope Bureau rejected every time) |
| Category blacklist | ✅ hard blacklist, tested this session including an active injection attempt |
| Explainability requirement | **Not implemented as a filter.** The demo's `/income-verification` response happens to include `reason_codes` (hardcoded), but the Agent never inspects a candidate's schema metadata to decide whether it's a "black-box score" that should be rejected. Still a real gap |
| Vendor trust threshold | ✅ implemented as a straight rejection ("excluded, not auto-approved"). There is **no separate "pending human review" queue** — the PRD allows either exclusion or a review queue; this demo only does the former |
| Data freshness window | **Still one shared server-side threshold** (30 days), not the PRD's per-category staleness table. Partially softened in round 5: `freshness_requirement_days` lets a specific request tighten that shared threshold, but there's still no per-category table configured by the lender's risk team |
| No qualifying candidate → escalate | ✅ hard stop, tested this session. "Escalate to a human" = write to the audit ledger + set `/status` phase; there is still no actual human-in-the-loop channel (no notification, ticket, or approval queue) |
| Audit logging | ✅ all 8 required fields present, tested this session, CSV export verified consistent with the raw log |

### Section 6 — Screens
- Screen 1: ✅ real backend-driven, now a tab.
- Screen 2: ✅ read-only, blacklist visually locked (🔒 + red styling + explanatory text), values pulled live from `/policy.json`. Screen 1's own "policy-strip" now also fetches `/policy.json` on load (round 5 fix) — both screens read the same live source, the drift risk flagged in round 4 is closed.
- Screen 3: ✅ CSV export works and was re-verified this session (row count matches). **PDF export is not implemented** (stated on the page itself, not hidden).

### Section 8 — Out of scope, compliance check
Verified clean: no credit-scoring or lending-decision logic exists anywhere
in the code; no bureau integration; and the category blacklist is hardcoded
server-side with no endpoint that can modify it — the injection-attempt
regression test above specifically confirms a caller cannot talk the Agent
into loosening it via the API.

### Section 9 — Transaction is part of the product
Qualitatively satisfied: Screen 1 shows settlement happening invisibly
inside the Shopping → Settling states via a console log and a receipt at the
end; nothing asks the (simulated) lender to manage a wallet directly.

---

## Other gaps found during this regression pass (not tied to one PRD line)

- **No authentication/authorization on any endpoint.** `/run`, `/policy-config`,
  `/audit-ledger`, `/audit`, `/audit.csv`, `/policy.json` are all open —
  anyone who can reach `localhost:8000` can trigger a real payment or read
  the full audit ledger. Fine for a local demo; would need addressing before
  this touches a real lender-facing deployment.
- **Per-applicant cumulative spend counter, and now the trial-credit/billing
  ledger too, are in-memory only** — both reset on every server restart.
  Same for the x402-xrpl library's default invoice store. None of it is
  persisted.
- **RLUSD** — PRD Section 4 Step 6 allows "XRP or RLUSD"; only XRP is
  implemented/tested. Unchanged limitation from round 1.
- **The dangling `README_AUDIT.md` reference** in `policy_filter.py` and
  `orchestrator.py` comments, now fixed by this file existing.
