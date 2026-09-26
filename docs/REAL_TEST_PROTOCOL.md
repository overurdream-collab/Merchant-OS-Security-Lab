# Merchant OS — Real Test & Proof Protocol

## Rule
No feature is considered working because the code exists or because a unit test is green.

Every idea must pass:
1. Build — imports, syntax and dependency integrity.
2. Unit test — deterministic logic and edge cases.
3. Integration test — real components connected through their real interfaces.
4. Failure test — required external source/service unavailable, malformed input, empty data, duplicate data and partial data.
5. Evidence test — outputs must trace to observed input/evidence; no invented facts or financials.
6. End-to-end test — the complete user/business path works with production-shaped data.
7. Acceptance test — explicit business outcome matches the specification.
8. CI proof — GitHub Actions run is green on the exact commit.
9. Regression test — previous capabilities remain green after every change.

## 100% claim policy
"100% working" means 100% of the defined acceptance criteria and test cases pass. It does not mean mathematical proof that every possible real-world input will work.

## External integrations
Facebook, WhatsApp, Telegram, web search and APIs are adapters, not core dependencies. For each adapter we test:
- available and valid response
- unavailable/timeout/error
- empty response
- malformed response
- duplicate records
- authentication/policy limitation
- fallback to manual/CSV/public-source input where supported

## Critical agents
Data Intelligence and Strategic Developer cannot be promoted unless:
- all competency cases pass
- adversarial/negative cases pass
- integration path passes
- no-fake-data checks pass
- exact commit has green CI

## Release gate
A feature is RELEASED only when all required gates are green. Otherwise its status is BLOCKED, not "probably works".
