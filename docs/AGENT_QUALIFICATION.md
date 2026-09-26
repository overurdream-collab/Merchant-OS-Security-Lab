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
