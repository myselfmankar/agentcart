# Phase 3 Plan — Production Hardening, Adversarial Testing, Protocol Conformance & Demo Engineering

> Status: PLAN (approved decisions locked below). Execute phases in order; run the suite before and after each phase.

## Context

Phase 2 produced a working, protocol-shaped autonomous-commerce pipeline (Shopping Agent → policy → AP2 mandates → ACP checkout → Razorpay → webhooks → WATCHING). A full execution-path trace shows the *shape* is right but the *guarantees* are not: authorization state, idempotency, and replay protection are **in-memory only** (lost on restart), the ledger is **debited on two paths** (inline + webhook) deduped only by a shared in-memory set, the webhook **trusts attacker-controllable payload fields**, the simulator **fakes instant capture**, the A2A "boundary" is a **direct Python call**, and several verifier checks the README implies (cnf binding, variant/quantity, iss/aud/jti, receipt integrity) **do not exist**. Phase 3 turns this into a system that survives adversarial input, process restarts, and duplicate/out-of-order events, while proving it with tests and a judge demo.

**Intended outcome:** every money movement passes a deterministic gate returning structured error codes; exactly-once ledger debit holds across restarts; invalid/unknown/tampered artifacts move ₹0; and the whole thing is demonstrable and documented.

## Decisions locked (from review)

1. **Payment truth model — Stateful rail + unified exactly-once.** The simulator becomes an async state machine (`created → attempted → authorized → captured/failed`), never instant-capture. Ledger debit fires **exactly once per `payment_id`** via a **persistent** idempotency record shared by the inline reconciliation *and* the webhook — whichever confirms capture first debits, the other is a no-op. The objective still completes inline once capture is confirmed, so existing happy-path E2E semantics are preserved.
2. **Scope — Full Phase 3, phased.** All 17 deliverables, dependency-ordered (Phase 0 → J). Any phase is a safe stopping point.

## Cross-cutting guardrails (apply in every phase)

- The LLM/agent never makes the final authorization decision — `policy_engine` + `DeterministicAP2Verifier` are the only gates.
- Verification returns **structured `VerificationResult`s with stable enum codes**, never bare bools.
- Treat merchant responses and webhooks as **untrusted** until cryptographically verified / reconciled against locally-recorded truth.
- Don't weaken a check to make a test pass; don't fake Razorpay capture; don't reuse stale closed mandates.
- Run `.venv/Scripts/pytest -v` before and after each phase; preserve passing tests unless a test encodes demonstrably incorrect behavior (note any such change in `PHASE3_RESULTS.md`).

## Test execution mode (applies from Phase 0)

The suite must be deterministic and offline. Tests run against the **stateful simulator**, not live Razorpay. Add a `conftest.py` autouse hook that forces `razorpay_client` into simulator mode (e.g. sets `RAZORPAY_KEY_ID` to an `rzp_test_mock…` sentinel and re-inits the client singleton), and a `@pytest.mark.live` opt-in for the existing `test_razorpay_mcp_live.py`. This also prevents the current `IS_LIVE_MCP=True` env from firing real test-mode payments during E2E runs.

---

## Phase 0 — Baseline & Audit  *(deliverable #1)*

- **Goal:** capture the true starting state and document traced findings before touching code.
- **Do:** run `.venv/Scripts/pytest -v` in simulator mode; record pass/fail. Author `docs/PHASE3_AUDIT.md`.
- **`docs/PHASE3_AUDIT.md` must cover:** implemented vs mocked vs protocol-faithful (traced, not "class exists"); security weaknesses (cnf not bound, webhook trusts `notes`/amount, legacy `verify_*` stubs return `True`); state-management weaknesses (in-memory sets); idempotency gaps; restart/recovery gaps; test-coverage gaps; contradictions with the Phase 2 plan (`my_plan.md`) and README (e.g. README claims variant match is enforced in signed checkout — it isn't).
- **Done when:** baseline numbers + audit doc committed; every defect below traces to a file:line in the doc.

## Phase A — Verifier as the final gate + error-code enum  *(deliverables #3, part of #13)*

- **Files:** `app/modules/ap2/verifier.py` (+ new `app/modules/ap2/errors.py`), `app/modules/acp/checkout.py`, `app/modules/acp/models.py`, `app/modules/ap2/mandates.py`, `app/shopping_agent/orchestrator.py`.
- **Changes:**
  - New `class ErrorCode(str, Enum)` — one stable machine-readable code per rejection; replace all string-literal codes. Structured result shape stays `{allowed, code, stage, message, details}`.
  - **Open mandate:** add `iss` and `aud` claims (signer = trusted surface, audience = `shopping_agent`) in `mandates.py`; verify `iss`, `aud`, header `kid == provider key id`, `iat` sanity (not in future), and a persistent **`jti` replay** check — on top of the existing signature/exp/cnf-presence checks.
  - **cnf binding (the headline fix):** the verifier must confirm the key that validly signs each *closed* mandate is exactly the `cnf.jwk` embedded in the corresponding *open* mandate → new `CNF_BINDING_MISMATCH`. Today `cnf` is decorative.
  - **Variant/quantity binding:** add `attributes` (size/color/brand) to the signed `line_items` claims in `sign_authoritative_checkout`, then have `verify_closed_checkout_mandate` assert brand/size/color/quantity match the open checkout mandate → `VARIANT_MISMATCH`, `QUANTITY_MISMATCH`.
  - **Payment mandate:** add nonce-replay, `jti`, and merchant-identity checks (closed payment `merchant_id` must equal the checkout's) → `PAYMENT_NONCE_REPLAY`, `MERCHANT_IDENTITY_MISMATCH`.
  - **Receipt integrity:** new `verify_receipt()` validating the merchant signature + `checkout_hash` on Checkout/Payment receipts → `RECEIPT_SIGNATURE_INVALID`, `RECEIPT_HASH_MISMATCH`.
  - **Remove the footguns:** delete or hard-`raise` the module-bottom `verify_cart_mandate`/`verify_payment_mandate` stubs that return `True` (grep references first; migrate `test_ap2_protocol_faithful.py` if needed).
- **Done when:** every check listed in spec §3 exists and is exercised; nonce/consumed/jti state reads/writes go through the Phase B store (wired in B).

## Phase B — Persistent idempotency & replay store  *(deliverable #7; foundation for #5,#6,#12)*

- **Files:** new `app/modules/state/idempotency.py`; wire into `verifier.py`, `policy/authority.py`, `policy/engine.py`, `razorpay/webhooks.py`.
- **Design:** a small atomic JSON-backed `IdempotencyStore` at `.temp-db/idempotency.json` (write-temp + `os.replace`), namespaced: `consumed_mandates`, `used_nonces`, `mandate_jti`, `payment_captures`, `webhook_events`, `payment_references`. API: `seen(ns, key) -> bool`, `record(ns, key, meta)`.
- **Changes:** replace `DeterministicAP2Verifier._consumed_mandates/_used_nonces`, `BuyerSpendingAuthority._processed_payment_ids`, `PolicyEngine._processed_payment_references`, and `RazorpayWebhookHandler._processed_events` with store-backed calls. `reset()` clears the relevant namespaces for tests.
- **Done when:** a replayed mandate / nonce / payment-id / webhook-event is rejected **after simulating a process restart** (new store instance reads prior state from disk).

## Phase C — Stateful Razorpay test rail  *(deliverable #11)*

- **Files:** `app/modules/razorpay/client.py` (+ `.temp-db/razorpay_rail.json`).
- **Changes:** simulator becomes `StatefulTestRail` — `create_order` records the order; `execute_test_payment` returns **`attempted`/`authorized`, never instant `captured`**; add `confirm_capture(payment_id)`/`poll_payment(payment_id)` that advances to `captured` (or `failed` when `simulate_failure`). Persist state so a restart resumes. Keep `execution_mode` label; **live test-mode path unchanged**. Record an **order registry** (`order_id → {objective_id, merchant_id, expected_amount, currency}`) here for Phase D.
- **Orchestrator:** after `execute_test_payment`, confirm capture via the rail before completing; feed the confirmed capture into the unified exactly-once debit (Phase E).
- **Done when:** no simulator path returns `captured` synchronously from the attempt; mode is clearly labelled; a payment can be observed moving through states.

## Phase D — Webhook hardening  *(deliverable #5)*

- **Files:** `app/modules/razorpay/webhooks.py`.
- **Changes:** after signature verify + persistent event-dedup, **look up `order_id` in the Phase C order registry**. Unknown order → reject, ₹0, `WEBHOOK_UNKNOWN_ORDER`. Derive `objective_id`/`merchant_id`/`expected_amount` from the **registry, not `notes`**. Validate payload `amount == expected_amount` and currency → `WEBHOOK_AMOUNT_MISMATCH` / `WEBHOOK_CURRENCY_MISMATCH` on mismatch, ₹0. Only then call the unified `record_payment_capture` (idempotent).
- **Done when:** valid / duplicate / delayed / out-of-order / replayed / invalid-sig / unknown-id / wrong-amount / wrong-currency / restart-boundary cases each behave correctly and never double-debit.

## Phase E — Buyer spending authority ledger  *(deliverable #12)*

- **Files:** `app/modules/policy/authority.py`; remove the **duplicate inline debit** vs webhook debit ambiguity by routing both through one persistent exactly-once path (Phase B `payment_captures`).
- **Changes:** independent enforcement of total / per-transaction / remaining / currency / identity, and exactly-once debit keyed by `payment_id` (survives restart). Ledger persisted. Canonical example encoded as a test: authority ₹6,000 → capture ₹4,899 → remaining ₹1,101 → subsequent ₹2,000 rejected (`INSUFFICIENT_BUYER_AUTHORITY`).
- **Done when:** one captured payment ⇒ exactly one debit regardless of path/restart; the ledger never trusts merchant price or Razorpay balance (amount comes from the verified checkout/registry).

## Phase F — Real A2A message boundary  *(deliverable #9)*

- **Files:** new `app/modules/a2a/messages.py` + `transport.py`; `app/modules/a2a/discovery.py`; merchants gain a `handle_a2a(request)` entrypoint.
- **Changes:** define `A2ARequest`/`A2AResponse` envelopes (agent-card id, method, structured data parts). `A2AMerchantAdapter` routes `search/create_checkout/sign/complete` through an in-process `transport.send(envelope)` that dispatches by agent card — **no direct merchant method calls** from the agent. Transport may stay in-process; the envelope + discovery must be real.
- **Done when:** a test proves the path Shopping Agent → A2A envelope → Merchant → ACP, and that the agent holds no direct merchant reference on the money path.

## Phase G — Merchant data-mutation / staleness  *(deliverable #10)*

- **Files:** `app/merchants/merchant_{a,b,c}.py`, `repository.py`.
- **Changes:** read merchant catalog **through the repository (disk) at decision time** (discovery/checkout), so a stale in-memory `self.inventory` cache cannot authorize. `data/merchants/*.json` is the single source of truth.
- **Done when:** a test that mutates the JSON via the repository (price up / stock to 0) without a manual reload proves the transaction is evaluated against disk truth, not stale cache.

## Phase H — Audit trail canonicalization  *(deliverable #13)*

- **Files:** `app/modules/audit/trail.py`; de-duplicate double-logging in `orchestrator.py` / `policy/engine.py`.
- **Changes:** define one canonical `EventType` set (resolve the dotted-vs-UPPER_SNAKE dual taxonomy and the "20 vs 21" count), stop emitting both variants per event, fix `_sanitize` over-redaction (keep `token_hash`/`checkout_hash`; redact only true secrets), and make `get_events_for_objective` able to read the persisted JSONL so restart-crossing tests can assert history.
- **Done when:** canonical event list documented; no secret material logged; audit readable after a restart.

## Phase I — Adversarial, crash-recovery & invariant tests  *(deliverables #4, #5-tests, #6, #7-tests, #8, #15)*

New suites (simulator mode):
- `tests/test_adversarial_ap2.py` — tampered/expired/replayed/over-budget/variant-mismatch/cnf-swapped mandates → each yields a specific `ErrorCode`, ₹0 moved, an audit event, no ledger debit.
- `tests/test_webhook_adversarial.py` — the Phase D matrix.
- `tests/test_crash_recovery.py` — inject a simulated restart at the 11 transaction boundaries (documented in `PHASE3_AUDIT.md`/recovery section); assert no double-debit, no stuck money, correct resume/fail. Add an `ObjectiveStore.recover()` that reconciles objectives stuck in `CHECKING_OUT`/`RE_EVALUATING` against the rail + idempotency store.
- `tests/test_idempotency_persistence.py` — replay across a fresh store instance.
- `tests/test_watching_hardening.py` *(deliverable #8)* — prove each re-evaluation mints NEW open+closed mandates and old closed mandates are never reused (structurally + replay-rejected).
- `tests/test_end_to_end_invariants.py` *(deliverable #15)* — core invariant `AUTHORIZED_PAYMENT ≤ OPEN_PAYMENT_MANDATE ∧ BUYER_AUTHORITY ∧ MERCHANT_FINAL_CHECKOUT ∧ USER_CONSTRAINTS`, plus `captured ⇒ exactly_one_debit`, `failed ⇒ zero_debit`, `stale_closed_mandate ⇒ zero_movement`, `invalid_webhook ⇒ zero_debit`.
- **Done when:** all new suites pass and the pre-existing suite still passes.

## Phase J — Demo + conformance + results  *(deliverables #14, #2, #17)*

- **`run_demo.py` → 7 scenarios:** Happy Path, Price Violation, Spending Authority, Replay Attack, Duplicate Webhook, WATCHING, Razorpay Failure — each printing the structured decision (code/stage) and **money moved**. Keep the labelled rail mode banner.
- **`docs/PROTOCOL_CONFORMANCE.md`:** matrix separating AP2 / ACP / A2A / Razorpay; per behavior: requirement, impl location (file:line), input/output artifact, crypto verification, covering test, status `PASS/PARTIAL/MOCK/MISSING`.
- **`docs/PHASE3_RESULTS.md`:** tests run + pass/fail counts, protocol areas covered, real-vs-simulated, exact demo commands, remaining limitations & known risks.
- **Done when:** `.venv/Scripts/python run_demo.py --scenario all` runs all 7; both docs reflect the shipped state.

---

## New error codes (indicative, finalized in Phase A)

`OPEN_MANDATE_ISS_INVALID`, `OPEN_MANDATE_AUD_INVALID`, `OPEN_MANDATE_KID_UNKNOWN`, `OPEN_MANDATE_IAT_INVALID`, `OPEN_MANDATE_JTI_REPLAY`, `CNF_BINDING_MISMATCH`, `VARIANT_MISMATCH`, `QUANTITY_MISMATCH`, `MERCHANT_IDENTITY_MISMATCH`, `PAYMENT_NONCE_REPLAY`, `RECEIPT_SIGNATURE_INVALID`, `RECEIPT_HASH_MISMATCH`, `WEBHOOK_UNKNOWN_ORDER`, `WEBHOOK_AMOUNT_MISMATCH`, `WEBHOOK_CURRENCY_MISMATCH` — added alongside the existing set (`OK`, `OPEN_MANDATE_EXPIRED`, `…SIGNATURE_INVALID`, `CNF_MISSING`, `MANDATE_ALREADY_CONSUMED`, `NONCE_REPLAY_DETECTED`, `CHECKOUT_HASH_MISMATCH`, `MERCHANT_CHECKOUT_SIGNATURE_INVALID`, `PRICE_EXCEEDED`, `MERCHANT_NOT_ALLOWED`, `CURRENCY_MISMATCH`, `PAYMENT_EXCEEDS_OPEN_MANDATE`, `PAYMENT_AMOUNT_MISMATCH`).

## Verification (end-to-end)

```bash
.venv/Scripts/pytest -v
```
```bash
.venv/Scripts/pytest tests/test_end_to_end_invariants.py tests/test_adversarial_ap2.py tests/test_webhook_adversarial.py -v
```
```bash
.venv/Scripts/python run_demo.py --scenario all
```
Manual restart check: run a purchase to the capture boundary, delete the in-memory process (fresh interpreter), re-run recovery, confirm ledger shows exactly one debit in `.temp-db/idempotency.json` and `.logs/audit_trail.jsonl`.

## Risk register

- **Existing E2E semantics.** The stateful rail must still let the inline flow reach `COMPLETED` (via confirm-capture) so `test_single_merchant_e2e` / `test_scenarios_e2e` / `test_watching_flow` stay green; if any legitimately must change, document it in `PHASE3_RESULTS.md`.
- **Live env bleed-through.** Current `.env` resolves to `IS_LIVE_MCP=True`; the Phase 0 conftest simulator-forcing must land first or the suite will hit the network.
- **Legacy `ap2.types` wrappers.** `sign_cart_mandate` / `create_payment_mandate` (and the `verify_*` stubs) are still imported by merchants/tests — grep before deleting; migrate callers rather than breaking imports.
- **Double-log churn.** Removing dual audit events may break tests asserting a specific event string; update them to the canonical taxonomy in the same phase.
