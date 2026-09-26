# Merchant OS — Agentic Commerce Core

Merchant OS is an upgrade-safe foundation for an AI-agent-powered social commerce operation.

## Run

```bash
python -m unittest discover -s tests -v
PYTHONPATH=src python src/run_webhook.py
```

Health endpoint: `GET /health`

## Production WhatsApp configuration

Set these server environment variables (never commit secrets):

- `WHATSAPP_VERIFY_TOKEN`
- `META_APP_SECRET`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `META_GRAPH_VERSION` (optional, default `v23.0`)
- `MERCHANT_OS_DB` (optional)
- `PORT` (optional)

Meta webhook URL: `/webhooks/whatsapp`.

## Architecture

```
Customer → WhatsApp/Web → Intake → Interest → Targeted Offer
        → Creative → Learning → Anti-Spam → Delivery Adapter
        → Order → Delivery → Collection → Return → Settlement
```

External providers stay behind adapters. Tests use a mock provider; real WhatsApp requires valid Meta Business credentials and webhook configuration.

## Intelligence Layer

Merchant OS now includes a reusable intelligence boundary for market discovery.

```text
WhatsApp / Meta / Reddit / Web / other approved sources
                         ↓
                  Hermes Scout
                         ↓
                 Market Signals
                         ↓
             Decision / Validation
                         ↓
                    Action
```

`hermes_scout_agent` is intentionally separate from customer-facing sales/order agents. It discovers and normalizes demand, complaints, price gaps, product gaps, competitor signals and trends into a common `market_signals` store.

Hermes itself is an external execution/collection provider, not hard-coded into the commerce core. Any approved collector can implement the small `SignalCollector` contract. This keeps the agent reusable for Merchant OS, auto parts, hotels, food and future projects.

The scout does not automatically contact users, negotiate, purchase, or execute business actions. Downstream decision agents and policy/risk gates own those actions.


## Operations

- Webhook messages are idempotent.
- Offer delivery has frequency and negative-signal controls.
- Offer lifecycle transitions are explicit.
- Orders, delivery, returns and settlements are persisted in SQLite.
- Secrets are environment variables only.

## Professor OS

Professor OS provides orchestration, specialist agents, JEV decisioning, confidence/risk gates, action execution, decision memory and audit/outcomes.

The commerce modules remain independent business infrastructure.
