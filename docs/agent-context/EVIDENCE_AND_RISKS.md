# Evidence and Risks

## Current Phase 2G-B evidence — 2026-09-24

- **Environment:** Python 3.14.6 (`.venv\Scripts\python.exe`), SQLite 3.50.4; branch `sales-page-v1`, HEAD `5f50be3845d56b223d25249bd0d9019025a6c6d4`. Worktree remains modified/uncommitted; this is local evidence, not CI.
- **Targeted tests:** pytest arguments `-p no:cacheprovider -q tests/test_checkout_service.py tests/test_quote_service.py` → **40 passed in 8.71s**.
- **Full tests:** required pytest arguments `-p no:cacheprovider -q` → **178 passed in 19.68s**. Both runs used the PowerShell inline Python wrapper shown below to defer `TemporaryDirectory` cleanup until after garbage collection because open SQLite handles can prevent Windows temp directory removal. No project files were created by the wrapper.
- **Exact wrapper invocation shape:** PowerShell piped an inline Python script to `.\.venv\Scripts\python.exe -`; the script set `sys.path` to `src`, replaced `TemporaryDirectory.cleanup` with a finalizer-detach/deferred-path collector, invoked `pytest.main(['-p','no:cacheprovider','-q'])` (or the targeted test paths above), forced `gc.collect()`, removed deferred temporary directories, and propagated pytest's exit code.
- **Read-only database verification:** `data/merchant_os.db` is at `user_version=5`; migration history is versions 1–5 and has no metadata error. `PRAGMA integrity_check` = `ok`; `PRAGMA foreign_key_check` = empty; audit orphans and ambiguous/suspicious-link warnings = empty. Counts for customers, orders, order_items, merchant_orders, fulfillments, deliveries, settlements, checkout_idempotency, sessions, carts, and cart_items are all zero. Tests used temporary databases; no production/demo rows were inserted.
- **Diff validation:** `git diff --check` exited successfully. Git emitted LF-to-CRLF working-copy notices for pre-existing modified tracked files; no whitespace errors were reported.
- **Schema:** Phase 2G-B made no schema or migration changes; Migration 5 remains current. Legacy `create_order()` was not changed.
- **No CI claim:** no CI run was performed.

## Verified environment and source state — 2026-09-24

- Python: **3.14.6** (`.venv\Scripts\python.exe`).
- SQLite library: **3.50.4**.
- Git branch: `sales-page-v1`; HEAD: `5f50be3845d56b223d25249bd0d9019025a6c6d4`.
- Worktree is modified and includes uncommitted/untracked foundation, migration, Cart, Agent Control Plane, tests, and memory files. Results below apply to this local worktree, not a clean HEAD or CI.

## Historical test evidence through Phase 2F

Full suite command run after the implementation and memory-independent code changes:

```powershell
@'
import gc, shutil, sys, tempfile, pytest
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
pending = []
def defer_cleanup(self):
    finalizer = getattr(self, '_finalizer', None)
    if finalizer is not None and finalizer.detach():
        pending.append(self.name)
tempfile.TemporaryDirectory.cleanup = defer_cleanup
try:
    result = pytest.main(['-p', 'no:cacheprovider', '-q'])
finally:
    gc.collect()
    for path in pending:
        shutil.rmtree(path, ignore_errors=True)
raise SystemExit(result)
'@ | .\.venv\Scripts\python.exe -
```

**Final observed result after approval-authority, ActionEngine, and identity-verifier boundaries:** `133 passed in 10.61s`. The cleanup override defers Windows temporary SQLite directory removal until after test connections are closed. No dependency was installed.

Final targeted command used the same wrapper with pytest arguments `['-p', 'no:cacheprovider', '-q', 'tests/test_commerce_agent_control_plane.py', 'tests/test_cart_service.py', 'tests/test_cart_foundation.py', 'tests/test_agent_runtime.py', 'tests/test_operational_core.py']`; result: **42 passed in 4.70s**.

Before adding Phase 2E tests, the full suite was run with the same wrapper and `pytest.main(['-p', 'no:cacheprovider', '-q'])`; result was **112 passed in 7.97s**. This independently verifies the previously reported count for the pre-Phase-2E test set.

CLI read smoke test: `.venv\Scripts\python.exe -m merchant_os.cli commerce-context --root .` with `PYTHONPATH=src`; after switching this command to ASCII-escaped JSON output, PowerShell parsed it successfully. `git diff --check` reported no whitespace errors; Git printed LF-to-CRLF normalization warnings for modified files.

During development, an earlier CLI smoke run failed with `UnicodeEncodeError` on a Unicode arrow in the Windows console. The output mode was changed to escaped JSON and the smoke test then passed. An initial targeted run had 4 failing tests caused by a test-provider assertion harness, expiry test aging the session as well as the cart, and duplicate fixture SKUs; those test issues were corrected. The final targeted and full-suite runs above pass.

## Historical database evidence after Phase 2F tests

Read-only `sqlite3` URI (`mode=ro`) and `audit_database('data/merchant_os.db')` after the full suite:

- `user_version=4`; history `[1, 2, 3, 4]`.
- `PRAGMA integrity_check`: `ok`.
- `PRAGMA foreign_key_check`: 0 rows.
- Audit-reported orphans: 0; ambiguous/suspicious-link warnings: 0.
- `sessions`, `delivery_zones`, `merchant_delivery_policies`, `carts`, and `cart_items`: 0 rows. All other business tables: 0 rows. `schema_migrations`: 4 rows.
- Global foreign-key default was not changed. CartService sets `PRAGMA foreign_keys=ON` only on connections it owns.
- Phase 2E tests use temporary databases. No migration was added or run by Phase 2E.

## Evidence register

| Claim | Classification | Evidence | Limitation |
|---|---|---|---|
| Migration 4 is present and applied to the local database | VERIFIED EVIDENCE | Read-only database audit after tests, 2026-09-24 | Does not tie the uncommitted migration source to a release commit. |
| Phase 2F suite: 151 passed and database v4 | VERIFIED EVIDENCE at Phase 2F completion only | Historical Phase 2F full-suite run and read-only checks below | Superseded by current Phase 2G-B evidence at the top of this file. |
| Phase 2G-B targeted 40 and full 178 tests pass | VERIFIED EVIDENCE | Exact local pytest wrapper runs listed at the top of this file | Modified worktree only; no CI or clean-checkout reproduction. |
| Database currently v5 with integrity/FK/audit checks clean | VERIFIED EVIDENCE | Read-only checks after Phase 2G-B tests, listed at the top of this file | Local workspace database only; does not establish a deployed production database state. |
| `commerce-context` works on Windows console output | VERIFIED EVIDENCE | CLI smoke test parsed by PowerShell `ConvertFrom-Json` | Command reads local docs; it is not a hosted API. |

## Open risks and boundaries

- R1 — **Approver authentication:** there is no Auth service or configured `ApprovalAuthority`. Approval creation fails closed unless a trusted authority adapter validates explicit approval evidence. `approver_context` is recorded but is not independently identity-verified; a trusted human/API boundary must provide a real verifier before production multi-user use. The legacy `ActionEngine` also fails closed without an injected approval-record verifier; the app has no verifier configured.
- R2 — **Process boundary:** registered action handlers are trusted Python code. Scope checks validate proposal paths but are not an OS sandbox and cannot stop arbitrary code from writing elsewhere.
- R3 — **Reasoning:** `ReasoningProvider` is an interface only; no LLM provider, API integration, or dependency was added. Provider output is validated as a Proposal and cannot directly call registered actions.
- R4 — **Evidence attestation:** test evidence is attached by the trusted caller after an external test run; no CI signature or subprocess attestation exists. The control plane requires recorded passing test evidence before its runtime-memory update.
- R5 — **HTTP boundary:** there is no HTTP framework/API in scope. A future adapter must call session retrieval on every request, return its refreshed `Set-Cookie`, pass HTTPS state from trusted transport configuration, and avoid trusting untrusted proxy headers.
- R6 — **Customer identity:** no verified customer-link or cart-merge flow exists. Phone is not authorization; OTP/Auth remains out of scope. Token rotation requires an injected `IdentityVerifier` and structured `VerifiedIdentityContext`; no verifier is configured by default, and customer linkage itself remains future work.
- R7 — **Stale items:** the service reports current ineligible lines in `unavailable_items`, retaining them for explicit removal. Future APIs/UI must communicate this condition and Checkout must revalidate.
- R8 — **Cart ownership conflict:** if an active cart is linked to a customer under another session, the service fails closed rather than revealing or merging it. A verified identity merge policy is still needed.
- R9 — **Quote and order totals:** Quote calculates current YER product totals and fixed merchant/zone delivery fees. Phase 2G-B revalidates and calculates Checkout totals at commit time; neither Quote nor the interval before Checkout reserves a price. Delivery execution remains unimplemented.
- R10 — **Inventory/money:** managed inventory is not reserved before Checkout and is decremented atomically during Checkout; stock restoration/cancellation is not implemented. Current catalog/order money remains REAL and no monetary representation conversion was attempted.
- R13 — **Fingerprint secret rotation:** successful retry comparison depends on the same `CHECKOUT_FINGERPRINT_SECRET` used for the original HMAC. Key versioning/rotation support is not implemented; production secret rotation policy must account for retained idempotency records.
- R11 — **Memory/audit persistence:** runtime records use existing lazily initialized `agent_runs` / `agent_memory`; no new versioned DB schema was created. These older tables are not part of Migration 4's schema contract.
- R12 — **Repository state:** older phase acceptance and CI evidence remain incomplete; all current source results are attached to a modified uncommitted worktree.

Close risks only with explicit decisions and reproducible evidence. Checkout and later commerce phases remain unauthorized until separately approved.

## Phase 2F — Delivery & Cart Quote verification — 2026-09-24

**Scope/decision:** human approval D-012 authorized Cart zone assignment and read-only Quote only. No schema changes or migrations were authorized or performed.

**Files changed by this phase:** `src/merchant_os/cart_service.py`, new `src/merchant_os/quote_service.py`, new `tests/test_quote_service.py`, and Agent Context records: `README.md`, `DECISIONS.md`, `PROJECT_STATE.md`, `phases/HISTORY.md`, `ROADMAP.md`, `EVIDENCE_AND_RISKS.md`. Other modified/untracked files were already present at task start and were not changed by this phase.

**Environment / source state:** Python 3.14.6 (`.venv\\Scripts\\python.exe`), SQLite 3.50.4; branch `sales-page-v1`, HEAD `5f50be3845d56b223d25249bd0d9019025a6c6d4`. The worktree was already modified/untracked before this task; results apply to the current local worktree, not a clean commit or CI.

**Exact test invocation:** PowerShell ran the following Python wrapper, first with targeted pytest arguments and then with full-suite arguments:

```python
import gc, shutil, sys, tempfile, pytest
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
pending = []
def defer_cleanup(self):
    finalizer = getattr(self, '_finalizer', None)
    if finalizer is not None and finalizer.detach():
        pending.append(self.name)
tempfile.TemporaryDirectory.cleanup = defer_cleanup
try:
    result = pytest.main(TEST_ARGS)
finally:
    gc.collect()
    for path in pending:
        shutil.rmtree(path, ignore_errors=True)
raise SystemExit(result)
```

Targeted `TEST_ARGS`: `['-p', 'no:cacheprovider', '-q', 'tests/test_quote_service.py', 'tests/test_cart_service.py']` → **31 passed in 5.11s**. Full-suite `TEST_ARGS`: `['-p', 'no:cacheprovider', '-q']` → **151 passed in 12.90s**. The deferred temporary-directory cleanup is used because Windows SQLite connections can remain open through teardown; cleanup runs after garbage collection.

**Database verification after tests:** read-only audit of `data/merchant_os.db`: `user_version=4`, migration history 1–4, no migration error, no missing core tables, no FK violations, no orphaned records, no suspicious links. Direct read-only SQLite checks: `PRAGMA integrity_check` = `ok`; `PRAGMA foreign_key_check` = empty. Counts for sessions, delivery_zones, merchant_delivery_policies, carts, cart_items, orders, deliveries, and settlements were all zero. No real DB sample/test records were created. No schema changed.

**Diff/scope verification:** `git diff --check` exited 0. Git printed line-ending normalization warnings for already modified tracked files; no whitespace errors were reported. Files/changes outside the Phase 2F and Agent Context scope were present at task start and remained untouched. Existing migrations 1–4 and the Commerce OS Agent Control Plane were not changed by this phase.

**Verified behavior:** session-token hash resolution and session/cart expiry are checked on Quote reads without DB writes; Quote opens SQLite via read-only `mode=ro`; a supplied cart ID is constrained to the session; cart zone assignment requires an active zone and session ownership; Quote reads current offer/product/merchant/policy state in one SQLite read transaction; fixed delivery fee is applied once per merchant; invalid/stale lines and missing/inactive policies fail closed; quote monetary outputs are decimal strings computed with Decimal intermediates from existing REAL values. Tests confirm Quote does not update session/cart timestamps or create order/delivery/settlement records.

**Risks:** no HTTP route/cookie adapter exists. Read-only Quote deliberately does not refresh the rolling session/cart activity timestamps; a future caller must invoke its established session activity path separately. REAL storage still limits source monetary precision. Quotes are ephemeral and do not reserve price or stock.
