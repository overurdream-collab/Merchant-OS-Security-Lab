# Gap Matrix — Commerce Execution Contract v1.0

Date: 2026-09-27
Repository: `overurdream-collab/Merchant-OS-Security-Lab`
Audited ref: `main` @ `892bd46f8460982e5bd079c73773643cf79a8b28`

## Audit conclusion

The repository already contains a functioning approval-backed CommerceControlPlane with proposal validation, scope enforcement, fingerprint binding, replay protection, audit records, and webhook idempotency. However, the contract is **not yet Beta-ready** under the proposed v1.0 invariant set.

The largest blockers are:
- no explicit Action Registry/version/policy model;
- no approval TTL/expiry;
- no Kill Switch;
- no static/invariant proof that every side-effecting path is forced through the Control Plane;
- no explicit material/non-material fingerprint contract;
- audit records are mutable at the application layer;
- several P0 fail-closed cases are behaviorally present but not yet proven by dedicated invariant tests.

Important correction: the supplied matrix contains **75 rows, not 87**. The count below is based on the actual rows supplied.

## Status legend

- ✅ Implemented + Tested
- ⚠️ Partial
- ❌ Missing
- ⏭️ N/A

## §6 — Proposal Fingerprint

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 6.1 | Deterministic fingerprint | ⚠️ | `src/merchant_os/commerce_agent.py::Proposal.fingerprint`; deterministic SHA-256 exists, but contract target field is not explicit and `summary` is included | P0 | 0.5d |
| 6.2 | Fingerprint persisted | ⚠️ | `ApprovalRecord.proposal_hash` persisted inside `agent_runs` approval output; no dedicated Proposal record | P0 | 0.5d |
| 6.3 | Recomputed at execution | ✅ | `CommerceControlPlane.execute()` compares persisted `proposal_hash` to `proposal.fingerprint()` | P0 | 0d |
| 6.4 | Mismatch → DENY | ✅ | `ApprovalDenied("matching_persisted_approval_required")`; tested in `tests/test_commerce_agent_control_plane.py` and `tests/test_agent_boundary_qualification.py` | P0 | 0d |
| 6.5 | Material fields defined | ❌ | No explicit material-field contract found | P0 | 0.5d |
| 6.6 | Non-material fields defined | ❌ | No explicit non-material-field contract found | P1 | 0.25d |

## §7 — Action Registry

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 7.1 | Registry exists | ⚠️ | Action configuration exists through `CommerceControlPlane._scope_configuration` and `ExecutionAgent.COMMERCE_ACTION_SCOPES`; no standalone registry | P0 | 0.75d |
| 7.2 | Every side effect registered | ⚠️ | Commerce actions are registered by `ExecutionAgent`, but domain services such as checkout/cancellation/delivery/settlement remain directly callable | P0 | 1d |
| 7.3 | Scope per action | ✅ | `ExecutionAgent.COMMERCE_ACTION_SCOPES` + `validate_proposal()` | P0 | 0d |
| 7.4 | Source per action | ❌ | No Action Registry source policy | P0 | 0.5d |
| 7.5 | Approval mode per action | ❌ | No required/policy/none action policy model | P0 | 0.5d |
| 7.6 | Action versioning | ❌ | No semver/action schema version model | P1 | 0.5d |
| 7.7 | Unknown action → DENY | ✅ | `validate_proposal()` rejects unregistered actions; covered by control-plane tests | P0 | 0d |
| 7.8 | Registry tested | ❌ | No registry-wide invariant test exists | P0 | 0.5d |

## §8 — Scope Enforcement

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 8.1 | Scope validation | ✅ | `CommerceControlPlane.validate_proposal()` | P0 | 0d |
| 8.2 | Scope escalation rejected | ✅ | Path/scope traversal and escalation tests in `tests/test_commerce_agent_control_plane.py` and `tests/test_agent_qualification_deep.py` | P0 | 0d |
| 8.3 | Scope comes from proposal and is bound | ✅ | Scope is included in Proposal and ApprovalRecord and compared at execution | P0 | 0d |
| 8.4 | Scope tested | ✅ | `tests/test_agent_qualification_deep.py`, `tests/test_commerce_agent_control_plane.py` | P0 | 0d |

## §14 — Approval Model

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 14.1 | Approval record exists | ⚠️ | `ApprovalRecord` persisted as `agent_runs(task_type='commerce_approval')`; no dedicated approval table | P0 | 0.25d |
| 14.2 | Approval tied to proposal | ✅ | `proposal_id` binding in execute validation | P0 | 0d |
| 14.3 | Approval tied to fingerprint | ✅ | `proposal_hash` comparison | P0 | 0d |
| 14.4 | Approval tied to scope | ✅ | Approval scope compared with Proposal scope | P0 | 0d |
| 14.5 | Approval TTL | ❌ | Approval has timestamp but no expiry policy | P0 | 0.5d |
| 14.6 | Expiry → DENY | ❌ | No expiry enforcement | P0 | 0.25d |
| 14.7 | Approval consumed | ✅ | `commerce_action` audit lookup prevents reuse; replay test exists | P0 | 0d |
| 14.8 | Dual approval for high risk | ❌ | No dual-approval policy | P1 | 1d |
| 14.9 | Approval delegation | ❌ | No delegation model | P1 | 0.5d |
| 14.10 | Timeout/escalation | ❌ | No timeout/escalation workflow | P1 | 0.5d |

## §15 — Replay Protection

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 15.1 | Approval nonce | ⚠️ | `approval_id` is UUID-unique and functions as an approval identifier, but no explicit nonce contract exists | P0 | 0.25d |
| 15.2 | Consumed approval → DENY | ✅ | `approval_already_consumed`; end-to-end replay test | P0 | 0d |
| 15.3 | Webhook idempotency key | ✅ | `webhook.py` derives `event_id` from WhatsApp message/status identity; `tests/test_webhook.py` proves duplicate rejection | P0 | 0d |
| 15.4 | Webhook replay guard | ✅ | `already_seen()` + `webhook_events` | P0 | 0d |
| 15.5 | AI rate limiting | ❌ | No rate limiter found | P1 | 0.5d |
| 15.6 | Human rate limiting | ❌ | No operator approval rate limiter | P1 | 0.5d |
| 15.7 | Webhook provider rate limiting | ❌ | No provider-specific limiter/throttle | P1 | 0.5d |

## §15.5 — Kill Switch

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 15.5.1 | L1 freeze AI path | ❌ | No kill-switch implementation found | P0 | 0.5d |
| 15.5.2 | L2 freeze automation | ❌ | No kill-switch implementation found | P1 | 0.5d |
| 15.5.3 | L3 freeze all writes | ❌ | No read-only freeze control found | P1 | 0.5d |
| 15.5.4 | Activation from Operations | ❌ | No Operations Console activation contract found | P0 | 0.5d |
| 15.5.5 | Kill switch tested | ❌ | No kill-switch test exists | P0 | 0.25d |

## §16 — Audit Contract

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 16.1 | Audit record exists | ✅ | `agent_runs` + `CommerceControlPlane._audit()` | P0 | 0d |
| 16.2 | Every side effect → audit | ⚠️ | Control Plane actions are audited, but domain services are directly callable outside CP | P0 | 1d |
| 16.3 | Required audit fields complete | ⚠️ | Generic `agent_runs` contains task/action context, but no normalized action_id/proposal_id/audit schema contract | P0 | 0.5d |
| 16.4 | Immutable at app layer | ⚠️ | Approval audit output is later updated by `_finish_action()` and evidence/memory functions | P0 | 0.75d |
| 16.5 | Hash chain | ❌ | No previous-hash/hash-chain field | P1 | 0.5d |
| 16.6 | Audit schema version | ❌ | No audit schema_version field | P1 | 0.25d |
| 16.7 | Audit query API | ❌ | No dedicated audit query API | P1 | 0.5d |

## §17 — Failure Rules / Fail Closed

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 17.1 | Missing approval → DENY | ✅ | `CommerceControlPlane.execute()`; dedicated tests | P0 | 0d |
| 17.2 | Unknown action → DENY | ✅ | `action_not_registered`; control-plane tests | P0 | 0d |
| 17.3 | Unknown scope → DENY | ✅ | `ScopeViolation`; scope tests | P0 | 0d |
| 17.4 | Fingerprint mismatch → DENY | ✅ | Matching approval fingerprint test | P0 | 0d |
| 17.5 | Expired approval → DENY | ❌ | No expiry exists | P0 | 0.25d |
| 17.6 | Replay → DENY | ✅ | End-to-end replay test | P0 | 0d |
| 17.7 | Invalid schema → DENY | ⚠️ | Proposal is strongly typed/validated manually, but there is no explicit versioned JSON Schema validator | P0 | 0.5d |
| 17.8 | Unauthorized source → DENY | ⚠️ | ApprovalAuthority is required, but the repository explicitly has no authenticated approver implementation | P0 | 1d |
| 17.9 | Default = DENY tested | ❌ | No global default-deny invariant test | P0 | 0.5d |

## §19 — Security Boundary

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 19.1 | No direct Professor OS → Core path | ⚠️ | Professor execution routes through ExecutionAgent/ControlPlane, but no static invariant proves the repository-wide property | P0 | 0.75d |
| 19.2 | No direct Channel → Core path | ⚠️ | WhatsApp webhook currently routes customer messages through router/agents; repository-wide invariant is not enforced | P0 | 0.5d |
| 19.3 | No direct Human → Core raw path | ⚠️ | Human approval is required at CP, but domain services remain directly importable/callable | P0 | 0.75d |
| 19.4 | No direct Webhook → Core path | ⚠️ | WhatsApp webhook does not directly invoke commerce domain writes, but no repository-wide invariant exists | P0 | 0.5d |
| 19.5 | L1 static AST invariant | ❌ | No architecture AST test found | P0 | 0.75d |
| 19.6 | L2 unit per action | ❌ | No per-action direct-Core denial suite; current architecture does not expose the proposed `CommerceCore.execute(token=...)` contract | P0 | 1d |
| 19.7 | L3 integration | ❌ | No full-source-path integration invariant | P1 | 1.5d |

## §20 — Threat Model

| # | Requirement | Status | Evidence | Priority | Effort |
|---|---|---|---|---|---|
| 20.1 | Prompt injection test | ❌ | No dedicated prompt-injection-to-commerce test | P0 | 0.5d |
| 20.2 | Compromised agent test | ⚠️ | ExecutionAgent bypass is tested, but repository-wide compromised-agent coverage is not complete | P0 | 0.5d |
| 20.3 | Scope escalation test | ✅ | Dedicated qualification tests | P0 | 0d |
| 20.4 | Proposal tampering test | ✅ | Fingerprint/tampering qualification tests | P0 | 0d |
| 20.5 | Approval replay test | ✅ | End-to-end replay qualification | P0 | 0d |
| 20.6 | Webhook replay test | ✅ | `tests/test_webhook.py` | P0 | 0d |
| 20.7 | Unauthorized human test | ❌ | No dedicated negative test for unauthorized approver identity/authentication | P0 | 0.5d |
| 20.8 | Context isolation test | ✅ | `tests/test_agent_context_integrity.py` proves deep nested isolation | P0 | 0d |
| 20.9 | Audit tampering test | ❌ | No dedicated audit immutability/tamper test | P1 | 0.5d |
| 20.10 | Insider threat test | ❌ | No dedicated role/dual-approval insider test | P1 | 0.5d |
| 20.11 | DoS on Control Plane test | ❌ | No rate/queue/circuit-breaker stress test | P1 | 1d |
| 20.12 | Dependency compromise / SBOM | ❌ | No SBOM/security-supply-chain qualification in this contract | P2 | 0.5d |

# Summary

## Status statistics

| Status | Count |
|---|---:|
| Total rows in supplied matrix | **75** |
| ✅ Implemented + Tested | **25** |
| ⚠️ Partial | **16** |
| ❌ Missing | **34** |
| ⏭️ N/A | **0** |

The supplied document says 87 total items, but its actual numbered rows total 75. This is a matrix bookkeeping discrepancy, not a repository finding.

## Priority distribution

| Priority | Count | Current assessment |
|---|---:|---|
| P0 | **57** | Beta blockers |
| P1 | **17** | Post-Beta / hardening unless Beta scope makes them money-critical |
| P2 | **1** | Later |

## P0 status

| P0 state | Count |
|---|---:|
| Already implemented + tested | 25 |
| Partial | 16 |
| Missing | 16 |
| **Not fully closed** | **32** |

The 32 not-fully-closed P0 rows should be treated as the actual Beta closure backlog.

## Estimated P0 effort

Current engineering estimate after repository inspection:

- Fingerprint contract + material fields: **1–1.5 days**
- Minimal Action Registry + action policies + registry tests: **1.5–2 days**
- Approval TTL/expiry + fail-closed tests: **0.75–1 day**
- Kill Switch L1 + Operations activation + tests: **1–1.5 days**
- Audit normalization/immutability boundary: **1–1.5 days**
- Security-boundary invariants L1/L2: **1.5–2 days**
- Threat-model P0 tests: **1–1.5 days**

These tasks overlap, so the total is not a simple sum. A realistic **P0 closure window is approximately 5–8 focused engineering days**, assuming no new product scope and no need to redesign the Commerce Core. The direct-path/security-boundary item is the largest uncertainty.

## Beta decision

**Current decision: DO NOT declare Beta-ready yet.**

Reason: the repository has a strong existing Control Plane, but the contract-level proof is incomplete. The most important remaining issue is not adding more agents; it is proving that **every side-effecting commerce path is actually forced through the same authorization boundary**.

### Recommended execution order

1. Close §19 L1/L2 boundary invariant first.
2. Define and lock the material fingerprint contract.
3. Introduce the minimal Action Registry/policy surface.
4. Add approval TTL + expiry denial.
5. Add L1 Kill Switch.
6. Normalize audit immutability/required fields.
7. Add the remaining P0 adversarial tests.
8. Run the full suite and CI.
9. Only then decide Beta readiness.

### Important architecture note

The supplied L2 example assumes a `CommerceCore.execute(action, token=...)` API and a `services/control_plane/` directory. The current repository does **not** use that exact architecture. It has domain services such as `checkout_service.py`, `cancellation_service.py`, `delivery_service.py`, and `settlement_service.py`, with `CommerceControlPlane` mediating registered handlers.

Therefore the invariant should be adapted to the **actual Merchant OS architecture**, not copied literally. We should not introduce a fake `CommerceCore.execute()` abstraction merely to make the test pass.

## Audit scope limitation

This is a static repository audit against the supplied contract. No production external credentials or live Meta/WhatsApp environment were assumed. No production code or feature was changed as part of this gap assessment.
