# Phase Ledger

Statuses: COMPLETE, IN PROGRESS, PLANNED, BLOCKED, UNVERIFIED, NOT AUTHORIZED.

| Phase | Summary | Status and evidence |
|---|---|---|
| Phase 0 | Initial architecture, currency/data safety, implementation boundaries. | UNVERIFIED history; acceptance record incomplete. |
| Phase 1 | Migration framework, database safety/backup, preservation tests. | UNVERIFIED historical acceptance; exact commit/CI proof pending. |
| Phase 2A | Earlier Commerce foundation. | UNVERIFIED; reconstruct exact scope from primary history. |
| Phase 2B | Catalog foundation, merchant linkage and explicit inventory-managed flag. | UNVERIFIED historical acceptance at current HEAD; prior conversation reports tests, but current worktree is modified. |
| Phase 2C | Order-item historical snapshots. | UNVERIFIED historical acceptance; migration/tests exist in modified worktree. |
| Migration 4 | Guest sessions and multi-merchant cart schema foundation. | VERIFIED locally as a historical migration; superseded by Migration 5 / schema v5. |
| Commerce OS Agent Control Plane | Deterministic project-memory/evidence/phase/scope/approval/audit boundary plus provider-neutral Proposal interface. | COMPLETE in current uncommitted worktree; full suite 133 passed. Approval fails closed without an authority adapter; approver identity is not authenticated; no LLM provider added. |
| Phase 2E | Session-bound Cart Service foundation: secure token/cookie handling contract, ownership, cart operations, eligibility, grouping, expiry and concurrency. | COMPLETE in current uncommitted worktree; 42 targeted and 133 full-suite tests passed. No HTTP API or Checkout. |
| Phase 2F | Session-bound delivery-zone selection and read-only server-side Cart Quote using fixed merchant/zone YER policies. | COMPLETE; 31 targeted / 151 full-suite tests were the phase-time results. Later work is recorded below. |
| Phase 2G-A / Migration 5 | Order/idempotency/Merchant Order/Fulfillment schema foundation. | COMPLETE locally: database is v5; integrity check `ok`; FK/orphan audit clean. |
| Phase 2G-B | Quote revision and non-HTTP Checkout Service. | COMPLETE locally: 37 targeted Checkout/Quote tests and 175 full-suite tests passed; local DB remained v5 with no commerce rows. Requires `CHECKOUT_FINGERPRINT_SECRET`; no HTTP adapter. See `phases/HISTORY.md` and `EVIDENCE_AND_RISKS.md`. |
| Phase 2G-C | HTTP adapter and frontend integration. | NOT AUTHORIZED. |
| Later operational phases | Delivery execution, cancellation/stock restoration, payments beyond COD, customer identity/OTP, analytics, connected Sales, future agents. | PLAN/PROPOSAL only; not implemented or authorized here. |

## Phase gate

Phases 2E, 2F, and 2G-A/B are complete only for their stated local service/schema scope. Checkout exists as a Python service only: HTTP endpoints, frontend wiring, delivery execution, settlement execution, cancellation/stock restoration, payment gateway, verified customer linking/merge and analytics remain separate future approvals. Use `commerce-context` to read these phase records; project actions still require a proposal, scope validation and explicit approval record.
