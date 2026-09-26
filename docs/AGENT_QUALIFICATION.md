# Agent Qualification & Reuse Audit

Date: 2026-09-27

## Scope

This audit evaluates the existing Merchant OS agent layer without adding agents, integrations, or product features. It also compares the current roles with reusable open-source projects found on GitHub.

## Current architecture findings

| Area | Current state | Qualification |
|---|---|---|
| Professor OS orchestration | 10 specialists run in a deterministic pipeline; state is passed forward | Functional, but not autonomous graph orchestration |
| AgentRuntime | Registry/task execution/audit; `next_agent` is returned but not automatically dispatched | Intentional runtime limitation |
| ResearchAgent | Provider search, source planning, dedupe, entity resolution, enrichment, evidence collection | Strongest specialist |
| IntelligenceAgent | Merchant ranking engine | Functional specialist |
| DataAgent | Data intelligence over merchant/customer/business events | Functional specialist |
| StrategyAgent | Strategic developer analysis | Functional specialist |
| MarketAgent | Returns category/city/count only | Thin deterministic analyzer |
| CustomerAgent | Taxonomy enrichment only | Thin deterministic helper |
| SalesAgent | Extracts channel signals | Thin deterministic helper |
| VerificationAgent | Checks evidence structure (source + dict), not source truth | Structural verification only |
| ExecutionAgent | Commerce actions route through CommerceControlPlane | Strong safety boundary |
| CommerceControlPlane | Scoped proposals, persisted approvals, fingerprints, replay protection, audit | Strongest safety component |
| Customer router | Keyword Arabic intent routing | Reliable deterministic routing, not an LLM agent |
| AgentNetwork | Business-agent dispatch abstraction | Routing layer more than autonomous agent network |
| JEV | Noul/Choice/Score; confidence is currently evidence-count based | Requires adversarial qualification before trusting as a decision signal |

## Important engineering conclusions

1. The system already has an agent-oriented architecture. Replacing it wholesale with CrewAI/LangGraph/etc. would create unnecessary migration risk.
2. The highest-value gap is not "more agents"; it is proving which existing agents are genuinely reasoning agents versus deterministic services.
3. Execution security must remain separate from reasoning. The current CommerceControlPlane should stay the enforcement boundary.
4. Verification currently establishes evidence shape, not evidence truth. It should not be treated as source authenticity or factual validation.
5. JEV confidence must not be interpreted as calibrated confidence until adversarial evaluation demonstrates that evidence quality, contradiction, provenance, and candidate quality affect it appropriately.
6. The customer-facing router is intentionally deterministic and can remain so for reliability; an LLM router is not automatically an improvement.

## Reusable GitHub projects worth evaluating

### 1. Commerceflow AI
Repository: https://github.com/Far3s18/Commerceflow-AI-Multi-Agent-Ecommerce-Assistant

Relevant overlap:
- customer intent routing
- product discovery
- grounded product retrieval
- interrupt-driven checkout
- stock guard before order write
- LangGraph stateful orchestration

Potential reuse:
- patterns for customer/product/order conversational flows
- stateful interrupt/checkpoint ideas
- grounding and no-fabricated-price safeguards

Do NOT copy wholesale:
- its stack is centered on LangGraph, Qdrant, Ollama and Chainlit
- Merchant OS already has its own commerce services and security boundary

### 2. E-Commerce AI Customer Support & Revenue Protection Agent
Repository: https://github.com/DuttPanchal04/ecommerce-ai-customer-support-revenue-protection-agent

Relevant overlap:
- prompt-injection precheck
- customer/order validation
- fraud/risk rules
- policy response
- escalation
- MCP integration patterns
- deterministic fallback mode

Potential reuse:
- adversarial support checks
- refund/fraud escalation patterns
- policy-grounded response design
- graceful model-quota fallback patterns

### 3. MultiAgent E-Commerce Customer Support
Repository: https://github.com/MissLostCodes/Multi-Agent-Ecommerce-Customer-Support-System

Relevant overlap:
- triage agent
- retrieval agent
- cited writer
- compliance agent
- golden evaluation cases

Potential reuse:
- citation-required response policy
- compliance gate
- evaluation-case structure

### 4. ResolveDesk
Repository: https://github.com/parasd086/Agentic-AI-Customer-Support-System-for-eCommerce

Relevant overlap:
- supervisor + specialist agents
- persistent conversation state
- hybrid retrieval
- retry/escalation on weak retrieval
- analytics and confidence tracking

Potential reuse:
- escalation state model
- retrieval retry pattern
- persistent session context

## Frameworks

Current ecosystem research indicates LangGraph, CrewAI, Microsoft Agent Framework, Google ADK, Pydantic AI and other frameworks are active options. AutoGen itself is now described by Microsoft as maintenance mode, with Microsoft Agent Framework as its successor.

For Merchant OS, framework adoption should be treated as an architectural decision, not a quick dependency addition.

## Decision

No external agent has been integrated into Merchant OS in this audit.

Recommended engineering path:
- keep the existing core
- qualify the current agents with adversarial and context-propagation tests
- selectively transplant proven patterns, not whole repositories
- only introduce an orchestration framework if testing proves the current Professor OS runtime is the limiting factor
- keep all real commerce execution behind CommerceControlPlane

## Next qualification targets

1. Evidence poisoning / weak-source acceptance
2. Contradictory evidence and JEV confidence
3. Context propagation across all 10 specialists
4. Agent failure and partial-pipeline recovery
5. Approval tampering and replay
6. Arabic multi-intent routing
7. Customer/order conversational state
8. End-to-end mission -> decision -> approved execution boundary


## Qualification pass 1 — completed 2026-09-27

### Proven invariants tested

- **Evidence provenance:** placeholder provenance such as `candidate_input` is rejected by `verify_evidence`.
- **Runtime isolation:** extracting `_next_agent` no longer mutates a handler-owned output dictionary.
- **Runtime failure audit:** specialist exceptions are converted into failed `AgentResult` records and audited with the original parent task.
- **Professor context chain:** the 10-specialist pipeline preserves a parent-task chain from Research through Supervisor.
- **Approval tampering:** changing approved proposal parameters invalidates the approval fingerprint.
- **Approval replay:** the same persisted approval cannot execute twice.
- **Scope escalation:** a proposal that changes the approved scope cannot reuse the original approval.

The deep qualification suite was committed as `1b2a8bcdd147ef0089de764fd0ab564122056e82`.

### CI verification

For that commit, GitHub Actions reported:
- Security Lab Tests: **success**
- Merchant OS CI: **success**
- test workflow job: **success**

Therefore the qualification additions did not regress the repository's automated test gates.

### Findings requiring characterization, not blind fixes

1. **JEV contradiction handling:** the current score is driven by evidence count and does not distinguish independent evidence from contradictory evidence. This is a confirmed design limitation, but changing the decision semantics would be a product/decision-policy change rather than a routine bug fix. No production change was made.
2. **JEV candidate quality:** mixed scored/unscored candidates fall back to the first candidate. This behavior is documented by the implementation but is not yet proven to violate an explicit contract. No production change was made.
3. **Verification truth:** provenance shape is now checked more strictly, but the verifier still does not independently authenticate or corroborate source truth. This remains a capability boundary.
4. **Multi-intent Arabic routing:** the router intentionally returns one primary intent. Inputs containing multiple intents therefore follow precedence rules rather than producing a multi-intent plan. This is a design limitation unless the product contract requires multi-intent handling.
5. **Conversational state:** the current qualification target remains to verify customer/order state across multiple turns; no new state architecture has been introduced.
6. **Dynamic orchestration:** `AgentRuntime.next_agent` remains metadata only. Professor OS owns orchestration, so this is not treated as a defect.

### Reuse conclusion

Current external research supports borrowing evaluation and orchestration patterns rather than replacing Merchant OS's architecture. In particular, trajectory/state-aware evaluation and explicit tool/business-rule guardrails are proven patterns in current agent tooling. They can strengthen qualification without forcing a framework migration.

No external agent or framework has been integrated.


## Qualification pass 2 — decision and execution boundaries

Additional characterization now covers:

- JEV behavior under contradictory evidence.
- The fact that JEV confidence is invariant to provenance quality when evidence count is equal; this is recorded as a decision-model limitation, not silently "fixed".
- Arabic multi-intent routing precedence.
- Customer-facing routing preserves the selected primary-intent contract.
- The decision gate blocks high-risk execution even at maximum confidence.
- The execution boundary rejects missing approval and permits execution only with a matching persisted approval.

Commit: `a140bd2cdc0ba71cac6dda3792c658e5bf1e1f57`.

CI verification for the commit:
- Security Lab Tests: **success**
- Merchant OS CI: **success**
- test workflow: **success**

### Current qualification conclusion

The strongest production boundary is now demonstrably the approval-backed CommerceControlPlane. The largest remaining qualification risk is decision quality, specifically JEV confidence semantics and evidence contradiction/quality handling. Customer conversational state is also still a capability boundary rather than a demonstrated multi-turn agent capability.

No new agent, framework, integration, or product feature was introduced.


## Qualification pass 3 — customer state and partial failure

Additional qualification on the current implementation:

- **Customer multi-turn persistence:** two inbound turns from the same WhatsApp identity resolve to the same customer record and the same open conversation, while both messages are persisted with that conversation. This proves persistence of the conversation identity/history at the intake/database layer.
- **Agent conversational context:** the current customer-facing agents do not consume persisted message history or conversation state when generating the response. Therefore persistence exists, but true state-aware multi-turn agent behavior is **not yet demonstrated**. No state architecture or agent behavior was added.
- **Partial pipeline failure:** when a specialist fails, Professor OS returns `failed` immediately, preserves the completed prefix in the response/audit trail, and does not continue to later specialists. This is safe fail-stop behavior, but there is currently no automatic retry/resume/recovery.
- **Recovery capability:** automatic retry/resume would change orchestration semantics and was therefore not introduced during qualification.

Qualification commit: `50168d41e1d45bceb4d3bb28a49062243b52f4d4`.

### Updated capability boundary

The current implementation now has evidence for:
- persistent customer/conversation identity across multiple turns;
- complete message persistence;
- audited specialist failure with parent-task context;
- fail-stop Professor OS behavior without continuing into later stages.

The remaining gap is **state-aware agent behavior and recovery**, not basic persistence or failure containment. These remain qualification findings rather than implementation requests.


## Qualification pass 4 — end-to-end decision and execution boundary

The end-to-end qualification now covers:

- **Approval-backed commerce execution:** a registered commerce action executes only when a matching persisted approved proposal and approval ID are supplied.
- **Execution-agent bypass attempt:** calling the commerce ExecutionAgent without an approval ID is blocked before the service handler is reached.
- **Approval replay:** reusing the consumed approval is blocked and the underlying commerce handler is not called again.
- **Supervisor veto:** an explicit supervisor veto returns `veto` and prevents the mission from becoming `ready_for_action`.
- **Verification failure:** evidence originating only from an unverified candidate is rejected before JEV/gates can produce `ready_for_action`.

Qualification commit: `a2d1ab844772354e7341fe928f7cac9301c47b62`.

### Boundary conclusion

The tested path is now:

`Mission -> 10 specialists -> Supervisor -> Evidence verification -> JEV -> Decision Gate`

followed, when separately approved, by:

`Proposal -> persisted approval -> CommerceControlPlane -> registered handler`

The execution path does not accept a caller-supplied boolean as authorization and does not permit the ExecutionAgent to bypass the CommerceControlPlane.

No new agent, framework, integration, or product feature was introduced.
