# Merchant OS AI Employee Architecture

## Purpose

Define the reusable AI Employee layer without changing Commerce Core or coupling the platform to a specific LLM, channel, or provider.

## Core rule

The model proposes. The Control Plane validates. Commerce Core executes.

```
Channel
  -> Channel Adapter
  -> Agent
  -> Proposal
  -> Control Plane
  -> Commerce Service
  -> Event
  -> Worker / external side effect
```

## Reusable agent roles

### 1. Customer Concierge
- Understand intent.
- Search catalog and current offers.
- Answer product questions from verified data.
- Build or modify a session-bound cart through approved tools.
- Never invent price, stock, delivery fee, or order status.

### 2. Sales Agent
- Recommend relevant products.
- Cross-sell and follow up.
- Use only approved pricing and promotion rules.
- Cannot negotiate or mutate prices unless a dedicated deterministic policy allows it.

### 3. Order Agent
- Convert an approved customer request into a Commerce Core operation.
- Use idempotent checkout.
- Report order status from Commerce Core events.
- Never directly write commerce tables.

### 4. Merchant Agent
- Intake merchant/product information.
- Prepare catalog proposals.
- Surface weak/strong products and operational opportunities.
- Require approval for consequential catalog or inventory mutations.

### 5. Retention Agent
- Identify eligible inactive customers from verified events.
- Prepare follow-up proposals.
- Respect consent, channel policy, frequency limits and suppression rules.

### 6. Intelligence Agent
- Produce weekly merchant reports.
- Explain observed sales, product and customer signals.
- Separate facts, inference and recommendations.
- Never present an unverified inference as a fact.

### 7. Supervisor / Router
- Select the appropriate agent.
- enforce scope and risk boundaries.
- Escalate ambiguous or high-risk requests.
- Prefer deterministic tools over model-generated values.

## Tool contract

Agents receive typed tools, not database access.

Examples:
- catalog.search
- offer.get_current
- cart.get
- cart.add
- cart.remove
- quote.calculate
- checkout.create
- order.get
- merchant_report.generate

Each tool must enforce ownership, currency, eligibility, idempotency and authorization independently.

## Risk gates

| Action | Default |
|---|---|
| Read catalog | Allowed |
| Read verified order status | Allowed |
| Build cart | Allowed within session |
| Calculate quote | Allowed |
| Create COD checkout | Control-plane validated |
| Cancel order | Verified identity + lifecycle rules |
| Change price | Approval required |
| Change inventory | Approval required |
| Send outbound campaign | Approval/policy required |
| Publish content | Approval required |
| Financial settlement | Deterministic core only |

## Provider strategy

Use a provider-neutral ReasoningProvider. No LLM provider becomes a core dependency until separately approved.

The AI layer must remain replaceable and must not own business truth.

## Human handoff

Escalate when:
- identity is insufficient;
- policy is ambiguous;
- requested action exceeds agent scope;
- a customer disputes an order/payment;
- the system detects conflicting commerce state;
- the model confidence is insufficient for the requested action.

## Vertical reuse

Verticals should provide configuration and adapters, not fork the core:

```
Merchant OS Core
  + vertical catalog schema/config
  + vertical policies
  + vertical agents/tools
  = sector solution
```

Initial candidates: auto parts, food, clothing, spices and hospitality.

## Explicit non-goals

This document does not authorize:
- a new LLM provider;
- WhatsApp/Meta integration;
- outbound messaging;
- payment gateway integration;
- automatic negotiation;
- autonomous financial actions.
