# Historical Phase Notes

These initial notes deliberately separate conversation reports from verified repository evidence. Each phase remains UNVERIFIED until its acceptance report, commit, tests/CI, and relevant database proof are linked.

## Phase 0
Available history describes reusable Commerce architecture, staged delivery, currency and data-safety concerns, and preserving the existing Sales experience during early foundation work. Exact acceptance criteria and outcome are incomplete.

## Phase 1
Conversation describes a migration framework, data-integrity review, backup, and preservation tests. Sales behavior, Catalog API, Cart, and Checkout were explicitly out of scope. Related files exist in the current modified worktree; exact commit and CI proof are pending.

## Phase 2A
Exact scope and acceptance have not been recovered. Do not infer it from later work.

## Phase 2B
Conversation reports catalog foundation with merchant_id authoritative for new offers, inventory_managed explicit, and no guessing of legacy merchant mappings. It reports Migration 2 and a delayed-cleanup full suite with 91 passing; standard run had Windows SQLite cleanup failures. Verify current code and exact CI.

## Phase 2C
Design approval is recorded in DECISIONS.md. The conversation explicitly excluded Checkout, stock decrement, merchant orders, fulfillment, delivery pricing, Sales, WhatsApp, and new integrations from that migration task. Verify implementation and test evidence separately.

## Phase 2D
Exact phase boundary and result have not been recovered. Migration 4 is recorded separately to avoid assigning it to Phase 2D without evidence.

## Migration 4
**Goal and approved boundary:** add only the guest-session, delivery-zone/policy, and multi-merchant cart schema foundation. The approved implementation instruction excludes Cart/Checkout APIs, stock operations, merchant orders, fulfillment, delivery behavior, Sales changes, analytics, authentication/OTP, cleanup jobs, payment, and money-type conversion. See the referenced Migration 4 implementation report/instruction in the project conversation (2026-09-24).

**Approved rules:** nullable `customers.wa_id` while preserving existing identities and child relationships; application-level rejection of missing/empty WA IDs; raw session tokens are not stored; session is the cart access boundary; positive integer quantities; one active cart per session and per verified customer; YER only; merchant eligibility requires active merchant, active offer/product, and a linked merchant; no financial totals are persisted on cart rows; no sample/business records are seeded.

**Repository FACT:** `src/merchant_os/migrations.py` defines `guest_sessions_and_multi_merchant_cart_foundation`; migration and cart tests are present in the modified working tree. Current commit observed on 2026-09-24 is `5f50be3845d56b223d25249bd0d9019025a6c6d4`, but migration files and related changes are untracked/modified, so this commit does not contain that implementation.

**Database FACT, read-only checks on 2026-09-24:** `data/merchant_os.db` reports user_version 4 and migration history versions 1–4; Migration 4 timestamp is `2026-09-23T23:24:39.150391+00:00`. The live DB passes `integrity_check`, has zero `foreign_key_check` rows, no audit-reported orphan relationships/warnings, and zero rows in reported business tables. `data/backups/merchant_os_pre_migration4_2026-09-24.sqlite3` is readable, passes integrity/FK checks, and remains at version 3. These checks verify local DB state only, not the applying source commit or exact backup byte identity.

**Initially reported, then independently verified:** the 2026-09-24 follow-up reran the exact full-suite command recorded in `EVIDENCE_AND_RISKS.md` on Python 3.14.6 / SQLite 3.50.4 and observed 112 passed before Phase 2E tests were added. This is local evidence for the then-current modified worktree, not CI or a clean-commit result. Read-only audit after the run showed version 4, `integrity_check=ok`, no FK violations/orphans/warnings, and no business rows.

**Remaining evidence:** reconcile uncommitted files and database lineage; obtain CI tied to a source commit if release/CI evidence is needed. The owner later explicitly approved Commerce OS Agent Control Plane and Phase 2E in the 2026-09-24 conversation; this supersedes the earlier NOT AUTHORIZED status for this bounded task only.

## Commerce OS Agent Control Plane and Phase 2E — 2026-09-24

**Approved scope:** deterministic project-memory/evidence/phase/scope/proposal/approval/action/audit/memory flow; provider-neutral reasoning interface only; guest session creation/retrieval and cookie contract; session-owned cart operations, current eligibility, quantity validation, merchant grouping, inactivity expiry, transaction safety and tests. No provider integration or dependency was approved.

**Implemented in the current modified worktree:**

- `src/merchant_os/commerce_agent.py`: typed FACT/DECISION/PLAN/PROPOSAL/RISK and verified/unverified evidence records, project-memory reader, current/next phase lookup, Proposal-only provider protocol, configured path-scope validation, persisted proposal-bound decisions, single-use approved action mediation and test/evidence-gated memory updates. Approval/action/test/memory audit uses the existing `agent_runs` and `agent_memory` tables; no schema migration was added.
- `src/merchant_os/cli.py`: read-only `commerce-context` command. JSON uses escaped Unicode for Windows console compatibility.
- `src/merchant_os/action_engine.py`: ignores legacy `approved=True`; execution requires a configured verifier to accept an approval record. Verifier failure blocks execution.
- `src/merchant_os/cart_service.py`: opaque random session tokens, SHA-256-only persistence, HttpOnly/SameSite=Lax cookies, caller-selected Secure flag for HTTPS, rolling 30-day session lifetime, 30-day cart inactivity expiration without deletion, session-bound cart ownership, positive integer mutations, current Offer/Product/Merchant/YER eligibility, stale-line reporting, current-price merchant grouping, parameterized SQL, and `BEGIN IMMEDIATE` transactions with per-service-connection FK enforcement. Identity-triggered token rotation requires an injected verifier; no customer-link/merge flow was added.
- Tests added: `tests/test_commerce_agent_control_plane.py` and `tests/test_cart_service.py`.

**Verified results:** final targeted Agent/Cart/ActionEngine tests: 42 passed. Final full suite: 133 passed (10.61s). Python 3.14.6, SQLite 3.50.4. Full command and Windows cleanup procedure are recorded in `EVIDENCE_AND_RISKS.md`. `git diff --check` found no whitespace errors; Git emitted line-ending normalization warnings for existing/modified files. Initial test-harness failures and the Windows CLI encoding failure were corrected and are preserved in the evidence log.

**Database evidence:** after the full suite, the live SQLite DB remained at user_version 4 with migrations 1–4, `integrity_check=ok`, zero FK violations, zero audit orphans/warnings and zero rows in sessions, carts, cart_items, and other business tables. No migration or production data write was performed for Phase 2E.

**Limitations / not implemented:** there is no HTTP framework/API in this scope, so callers must wire cookie parsing/Set-Cookie and trustworthy HTTPS detection. There is no authenticated approver service; approver context is recorded but not independently identity-verified. Registered Python handlers are trusted code, not an OS sandbox. The reasoning interface has no provider. Verified-customer linking/merge, Checkout, stock, deliveries, Sales and all later phases remain unimplemented.

## Phase 2G-A — Migration 5 — 2026-09-24

**VERIFIED EVIDENCE:** migration advanced the local schema from v4 to v5 and established the approved order architecture foundation. The previously reported focused migration/order tests (21 passed) and full suite (156 passed) were not rerun as part of this entry; Phase 2G-B verified the current database is v5, Migration 5 is in history, integrity-check is `ok`, FK check is empty, and commerce tables are empty. No Phase 2G-B schema changes were made.

## Phase 2G-B — Quote Revision and Checkout Service — 2026-09-24

**Authorization:** explicit human approval for proposal `COM-2G-B-CHECKOUT-SERVICE-20260924-01`; implementation was limited to deterministic quote revision, a Python Checkout service, tests, and the requested Agent Context files. No HTTP API, Sales, WhatsApp, payment gateway, delivery/settlement execution, cancellation/refunds, analytics, new dependency, or provider was added.

**Implementation facts:**

- `src/merchant_os/quote_service.py` returns a deterministic SHA-256 revision over canonical, sorted server-side cart/zone/item/policy inputs, including current offer prices, eligibility, inventory mode/stock, and policy fee/state. It detects stale state and is not authorization.
- `src/merchant_os/checkout_service.py` uses one SQLite connection, enables foreign keys before `BEGIN IMMEDIATE`, authenticates by hashed session token and owned Cart, revalidates current catalog/zone/policy/quantity/currency/price state and quote revision, and commits orders, managed-stock decrement, idempotency result, and Cart status atomically.
- Checkout uses `CHECKOUT_FINGERPRINT_SECRET` for HMAC-SHA256; missing or fewer than 32 UTF-8 bytes fails closed. Only a hash of the raw idempotency key is stored. Guests receive a new `wa_id=NULL` Customer inside the transaction; there is no phone matching or WhatsApp identity path.
- Successful Checkout creates one COD Root Order (`pending` / `unpaid`), one Merchant Order per merchant, historical order-item snapshots, and one pending Fulfillment #1 per Merchant Order. It creates no Delivery or Settlement. Legacy `orders.create_order()` is unchanged.

**VERIFIED EVIDENCE:** Python 3.14.6 / SQLite 3.50.4. Targeted pytest arguments `-p no:cacheprovider -q tests/test_checkout_service.py tests/test_quote_service.py` → **40 passed in 8.71s**. Full pytest arguments `-p no:cacheprovider -q` → **178 passed in 19.68s**. Both used the established inline-Python wrapper that defers temporary-directory cleanup until after SQLite handles close. Read-only DB check: `data/merchant_os.db` remains v5, integrity `ok`, FK check empty, audit orphans/warnings empty, zero commerce rows. `git diff --check` succeeded. No CI run occurred.

**Remaining risks:** no HTTP cookie/request adapter exists; deployment must provision the dedicated HMAC secret and keep it out of logs and memory. Fingerprints depend on the active secret; key versioning/rotation with retained idempotency rows is not implemented. Money remains stored as REAL. Managed stock is decremented at Checkout, but cancellation/restoration is not implemented; that contract is required before production order operations. No payment beyond COD exists.

## Phase 2F — Delivery & Cart Quote — 2026-09-24

**DECISION / authorization:** owner explicitly approved only an independent Quote service and session-bound delivery-zone assignment. Quote revalidates ownership, cart, zone, current Offer/Product/Merchant eligibility, quantity, YER currency, and active merchant delivery policies. It calculates fixed delivery fees once per merchant. No schema changes, persistence, Checkout, Orders, stock operations, delivery execution, Sales, WhatsApp, new dependencies, LLM provider, or Agent Control Plane changes were authorized.

**Implemented in current modified worktree:**

- `src/merchant_os/cart_service.py`: added `set_delivery_zone`, which resolves the cookie session, constrains cart selection to that session, requires an active zone, and updates only the selected cart's zone and activity timestamp.
- `src/merchant_os/quote_service.py`: added independent read-only `QuoteService`, opening SQLite with URI `mode=ro`. It reads session/cart ownership without touching activity timestamps, checks session/cart expiry and selected active zone, revalidates every current cart line and policy in one SQLite read transaction, and returns grouped YER totals. Missing/inactive policies or ineligible lines fail closed. Money math uses `Decimal` for intermediates and returns decimal strings; SQLite REAL source representation remains unchanged.
- `tests/test_quote_service.py`: added coverage for single/multi-merchant math, policies, zones, stale catalog state, current price, quantities, YER, session IDOR, empty cart, duplicate offer quantity, read-only behavior, absence of order/delivery records, and FK default behavior.

**VERIFIED EVIDENCE:** on Python 3.14.6 / SQLite 3.50.4, targeted Cart/Quote tests passed **31/31 in 5.11s**; full suite passed **151/151 in 12.90s**. Tests ran with deferred `TemporaryDirectory` cleanup for Windows SQLite handles and disabled pytest cache provider. `git diff --check` returned success (Git emitted line-ending normalization warnings for pre-existing modified tracked files). After tests, read-only database audit found user_version 4 and migration history 1–4; `PRAGMA integrity_check` returned `ok`; `PRAGMA foreign_key_check` returned zero rows; business tables including sessions, zones, policies, carts, cart items, orders, deliveries and settlements had zero rows. No migration/schema changes were made.

**LIMITATIONS / risks:** no HTTP route or cookie middleware exists; application integration must supply the request cookie and use trusted transport state. Strictly read-only Quote does not extend session/cart activity timestamps; callers needing rolling session activity must separately use the existing session activity flow. SQLite REAL fields still limit source monetary precision. A Quote is ephemeral and reserves neither price nor stock. No Checkout, Orders, Payments, stock reservation/decrement, Merchant Orders, Fulfillments, Delivery records, WhatsApp/Sales changes, dependency, LLM provider, or Agent Control Plane changes were made.
