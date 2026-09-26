# Constraints and Guardrails

- Approval-first: analyze and propose before large or out-of-scope implementation.
- Do not start Phase 2E unless explicitly authorized.
- Do not change Commerce behavior as part of context maintenance.
- Do not create or delegate to additional agents without explicit authorization.
- Prefer reusable Commerce Core capabilities and isolate project-specific behavior.
- Keep backend authoritative for prices, totals, merchant relationships, offer eligibility, and checkout validation.
- Keep external providers behind adapters; distinguish mocked/local evidence from live integration proof.
- Do not invent customer/business records, IDs, prices, test results, or security findings.
- Migration definition, successful application, and production database verification are separate claims.
- Attach test/CI results to an exact commit and environment.
- Do not store secrets or customer personal information in project memory.
- If the requested task exceeds its approved scope, stop at a concrete proposal unless the user's instruction explicitly authorizes that scope.
