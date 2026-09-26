# Approved Decisions and Architecture

Status terms: APPROVED, PROPOSED, SUPERSEDED, UNVERIFIED. A design approval does not prove implementation.

| ID | Approved decision | Source and implementation boundary |
|---|---|---|
| D-001 | Merchant OS is reusable Commerce infrastructure; isolate project-specific logic from the core. | Project conversation, 2026-09-24. Architectural intent; not proof modularity is complete. |
| D-002 | One customer-facing cart supports items from multiple merchants and one checkout; group internally by merchant. | Project conversation. Migration foundation is distinct from a working Cart Service. |
| D-003 | Guest checkout; do not force account creation before purchase. | Project conversation. Full checkout is future work. |
| D-004 | Root order can contain merchant-specific commercial groups; separate fulfillment and delivery records, allowing multiple deliveries in future. | Project conversation. Final implementation remains unverified/incomplete. |
| D-005 | Backend validates commercial data and calculates prices/totals; do not trust client-supplied prices or totals. | Project conversation. Checkout validation remains future work. |
| D-006 | Customer analytics/intelligence remain separate from the purchase path and optional consent. | Project conversation. |
| D-007 | Phase 2C order-item history uses nullable legacy-compatible offer/merchant/currency/total/name/SKU snapshots; preserve old API and avoid implementing checkout in that phase. | Phase 2C approval in project conversation. Verify exact migration and commit. |
| D-008 | Do not convert existing REAL money fields or invent legacy mappings/snapshots in Phase 2C. | Phase 2C approval. Future money representation remains unresolved. |
| D-009 | Do not change global SQLite foreign-key behavior in Phase 2C; use FK-enabled test connections and document limits. | Phase 2C approval. |
| D-010 | Agent acts as analyst/architect and executor only within approved scope; owner retains final authority. | Project conversation and current user request. |
| D-011 | Do not start Phase 2E or create/delegate additional agents without explicit authorization. | Earlier user instruction; the Phase 2E and Agent Control Plane work was subsequently explicitly approved. Historical gate satisfied; every new phase still requires explicit authorization. |
| D-012 | Phase 2F may implement a session-owned cart delivery-zone selection and an independent, read-only server-side YER Cart Quote using current eligible offers and active fixed-fee merchant/zone policies. No schema changes, persistence, Checkout, Orders, stock, Delivery records, Payments, WhatsApp, Sales UI, LLM provider, dependency, or Agent Control Plane changes are permitted. | Explicit human approval, project conversation, 2026-09-24. Implementation evidence is recorded in `phases/HISTORY.md` and `EVIDENCE_AND_RISKS.md`. |

## Architecture summary

Repository FACT: Python/SQLite Commerce modules live in src/merchant_os; the repository also contains a sales prototype, WhatsApp/webhook adapters, tests, and Professor OS orchestration/specialists.

Target intent:

Visitor/guest session → catalog/offers → one multi-merchant cart → one root order → merchant-specific order groups → fulfillment(s) → delivery record(s) → settlement.

The sales experience may be project-specific. Commerce rules should live in reusable services. AI agents should use Commerce APIs and guardrails rather than implement parallel commercial rules.

When adding a decision, record its date, approval source, rationale, consequences, related phase, implementation links, evidence, and any decision it supersedes. Do not silently change an approved decision.
