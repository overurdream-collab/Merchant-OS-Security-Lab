# Project State

Snapshot: 2026-09-24
Repository: `F:\lamsa\merchant-os`
Branch / HEAD: `sales-page-v1` / `5f50be3845d56b223d25249bd0d9019025a6c6d4`
Worktree: modified and contains untracked work from earlier phases and this authorized implementation. Changes are not committed.

## Current verified state

- Python 3.14.6; SQLite 3.50.4.
- Migration code defines versions 1–5. Current read-only verification of `data/merchant_os.db` after Phase 2G-B reports `user_version=5`, migration history 1–5, `integrity_check=ok`, no `foreign_key_check` violations, no audit-reported orphan rows or warnings, and zero rows in commerce/business tables. `schema_migrations` has 5 rows.
- Pre-Migration-4 backup `data/backups/merchant_os_pre_migration4_2026-09-24.sqlite3` is readable at version 3, integrity-clean, and has no FK violations.
- Latest full test suite on this worktree: **178 passed** using Python with deferred `TemporaryDirectory` cleanup for Windows SQLite handles. Phase 2G-B targeted Checkout/Quote tests: **40 passed**. Earlier suite counts (including 151 at Phase 2F) are historical phase snapshots, not the latest count. Exact commands and environment are recorded in `EVIDENCE_AND_RISKS.md`.
- Commerce Control Plane, Phase 2E Cart Service, Phase 2F Quote, Migration 5 / Phase 2G-A, and Phase 2G-B Checkout Service are implemented in the modified worktree and validated by local test runs. Evidence is local to the current uncommitted worktree, not CI or a clean commit.
- `commerce-context` CLI reads the agent-context documents and reports current/next phase. It is read-only.
- Phase 2E does not add an HTTP API, Checkout, stock operations, delivery operations, customer authentication, OTP, analytics, or Sales changes.

## Agent Control Plane

- FACT: `src/merchant_os/commerce_agent.py` provides typed record/evidence classifications, reads project memory, tracks phase state, defines a provider-neutral Proposal-only interface, validates configured action scope, records approvals and action outcomes in existing `agent_runs`, requires an injected `ApprovalAuthority` plus a matching persisted approval ID for registered action execution, and only updates runtime memory after a recorded passing test result with matching verified evidence.
- LIMITATION: no authenticated approver service exists. `approver_context` is recorded but is not identity-verified. The control plane is an application-level mediation layer, not an OS sandbox; registered handlers are trusted code.
- `approved=True` on the legacy `ActionEngine` is ignored; execution requires a configured verifier to accept an approval record. It cannot authorize a Commerce Core mutation by itself.

## Phase 2E Cart Service

- FACT: `src/merchant_os/cart_service.py` uses random opaque tokens, stores SHA-256 hashes only, issues HttpOnly/SameSite=Lax cookies and Secure cookies when the trusted caller marks HTTPS, applies rolling 30-day session expiry and 30-day cart inactivity expiry, and enables SQLite foreign keys only on service-owned connections.
- Ownership is resolved by the session token. Supplied cart IDs are additionally constrained by the resolved session; foreign-session cart IDs return the same not-found result. Customer IDs and phone numbers are not accepted as authorization.
- Cart mutation uses parameterized SQL and `BEGIN IMMEDIATE`; offer eligibility is re-read from Offer/Product/Merchant, currency is YER, quantity is a positive integer, duplicate offers increment quantity, and reads recalculate current-price merchant groups and products subtotals. Newly ineligible existing lines are reported unavailable and retained for explicit removal.
- HTTP routes/cookie middleware do not exist in this phase. An eventual HTTP adapter must call session retrieval on each request, send its refreshed Set-Cookie header, pass trusted HTTPS state, and avoid trusting forwarded-protocol headers from untrusted proxies.
- Verified customer linking/merge is not implemented. Session-token rotation requires an injected identity-verifier adapter and a structured verification context; none is configured by default. Without an Auth/OTP system, the service itself cannot establish identity.

## Phase 2F Delivery & Cart Quote

- FACT: `src/merchant_os/cart_service.py` now provides `set_delivery_zone`; it resolves the opaque session cookie, enforces that the selected cart belongs to that session, and accepts only an active delivery zone.
- FACT: `src/merchant_os/quote_service.py` provides an independent read-only server-side quote using SQLite `mode=ro`. It checks session/cart ownership and expiry, selected active zone, current offer/product/merchant eligibility, positive integer quantities, YER currency, and one active fixed-fee policy for each merchant. It groups by merchant, applies delivery fee once per merchant, and calculates all totals from current database values in a single read transaction.
- FACT: monetary calculations use `Decimal` intermediates and decimal-string outputs, while source schema remains SQLite REAL; this does not eliminate precision already lost by REAL storage.
- VERIFIED EVIDENCE at the end of Phase 2F: 31 targeted Cart/Quote tests and 151 full-suite tests passed on Python 3.14.6 / SQLite 3.50.4. The database was then at user_version 4; integrity/FK checks clean; no business rows were created. The database and test count were subsequently advanced/updated in Phase 2G-A/B; see current state above and `EVIDENCE_AND_RISKS.md`.
- LIMITATIONS at the end of Phase 2F: no HTTP endpoint/cookie middleware existed. Strictly read-only Quote did not touch session/cart activity timestamps, so callers requiring rolling activity needed to use the existing session activity operation separately. Quote is ephemeral and reserves neither price nor stock. Checkout and stock operations were not implemented at that phase; Phase 2G-B now implements the bounded Checkout service described below.

## Phase 2G-A / Migration 5 and Phase 2G-B Checkout

- VERIFIED EVIDENCE: Migration 5 is schema version 5. It adds the approved order architecture foundation; no further schema change was made in Phase 2G-B.
- FACT: `src/merchant_os/quote_service.py` returns deterministic SHA-256 `quote_revision` from canonical server-side cart, zone, item eligibility/current price/inventory state, and delivery-policy inputs.
- FACT: `src/merchant_os/checkout_service.py` provides a non-HTTP Checkout service using one SQLite connection, `PRAGMA foreign_keys=ON` before `BEGIN IMMEDIATE`, session-owned Cart resolution, current-state Quote recomputation, HMAC-SHA256 request fingerprints from `CHECKOUT_FINGERPRINT_SECRET`, COD-only Root Orders, merchant orders, item snapshots, pending fulfillment #1, managed stock decrement, atomic idempotency record, and cart transition.
- FACT: guests receive a new `wa_id=NULL` Customer per successful Checkout; phone is not used to find/merge Customers. Existing `orders.create_order()` behavior was not changed.
- VERIFIED EVIDENCE: targeted Checkout/Quote suite **40 passed**; full suite **178 passed** on Python 3.14.6 / SQLite 3.50.4, using the established deferred Windows SQLite temporary-directory cleanup wrapper. Current local DB remains v5, integrity-check `ok`, FK check empty, no audit orphans/warnings, and no commerce rows.
- LIMITATIONS: no HTTP adapter exists; the host must provide the cookie header and configure `CHECKOUT_FINGERPRINT_SECRET` (at least 32 UTF-8 bytes). Fingerprints use the active secret, so safe secret rotation/key-version handling is not designed yet. Current money columns remain REAL. COD is the only method. No Delivery or Settlement rows are created. Cancellation/stock restoration remains a required future operational contract before real commerce operations.

## Historical uncertainty

- Earlier phase history is incomplete; conversation summaries are not automatically treated as repository evidence.
- Migration 4 and the 112-test run were reverified locally during the 2026-09-24 task. The prior 112 count describes the pre-Phase-2E suite; the current suite has 133 passing tests.
- Existing CI evidence cited by `docs/IMPLEMENTATION_AUDIT.md` refers to an older commit and does not prove the current worktree.
