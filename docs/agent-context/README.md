# Commerce OS Agent Context

This folder is the durable project memory for the future Commerce OS Agent. It records verified state, approved decisions, constraints, phases, risks, and test evidence. It is documentation, not application logic.

## Start-of-session procedure

1. Read this file, repository-root AGENTS.md, and PROJECT_STATE.md.
2. Inspect current branch, commit, and working-tree status.
3. Read relevant entries in DECISIONS.md, ROADMAP.md, and EVIDENCE_AND_RISKS.md.
4. Confirm requested scope and approvals. A plan or old conversation is not permission to implement.

## End-of-phase procedure

For every authorized phase or bounded change, record its goal, approved scope, files changed, decisions and their sources, exact tests/CI actually run, environment, results, failures, skips, limitations, commit, and remaining risks. Update the phase ledger and PROJECT_STATE.md. Never mark a phase complete without acceptance evidence. Keep historical corrections rather than erasing prior claims.

## Evidence labels

- FACT: verified in named code, test output, commit, CI, or environment.
- DECISION: explicitly approved by the owner.
- PLAN: intended work not implemented yet.
- PROPOSAL: suggested but not approved.
- RISK: uncertainty or failure mode needing follow-up.
- UNVERIFIED: reported but not independently confirmed.

## Sources of truth

- Behavior/schema: repository source at a named commit.
- Test/release status: output or CI tied to exact commit and environment.
- Approved intent: DECISIONS.md and linked decision records.
- Planned work: ROADMAP.md.
- Current summary: PROJECT_STATE.md.
- Unresolved issues: EVIDENCE_AND_RISKS.md.

## Project intent

DECISION: Merchant OS should be reusable Commerce infrastructure for multiple projects; isolate project-specific logic from core. The agent is intended to follow the project step by step and eventually support handover. It starts as analyst/architect and approval-gated executor; the human remains final authority.

## Current caution

The inspected repository is F:\lamsa\merchant-os, branch sales-page-v1, commit 5f50be3845d56b223d25249bd0d9019025a6c6d4. The working tree is modified and contains untracked foundation/migration work; these changes are not part of HEAD. The implementation audit references older CI evidence. A read-only check after Phase 2F confirms the local database remains at schema version 4 and passes integrity/FK checks, with a readable version-3 pre-Migration-4 backup. The latest local modified-worktree run on 2026-09-24 observed 151 passing tests (31 targeted Cart/Quote tests); this is local evidence, not CI or a clean-commit result. See PROJECT_STATE.md, ROADMAP.md, and EVIDENCE_AND_RISKS.md.
