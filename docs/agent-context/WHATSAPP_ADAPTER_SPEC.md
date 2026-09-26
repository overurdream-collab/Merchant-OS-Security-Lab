# WhatsApp Adapter Boundary

## Status

Design specification only. No Meta credentials, webhook, provider dependency, or outbound messaging is authorized by this document.

## Objective

Use WhatsApp as a replaceable channel adapter while keeping Merchant OS commerce logic independent from Meta APIs.

## Boundary

```
WhatsApp
  <-> WhatsApp Adapter
  <-> Merchant OS Agent/Channel Interface
  <-> Control Plane
  <-> Commerce Core
```

An external WhatsApp Business MCP may be used behind the adapter. It must not become a Merchant OS Core dependency.

## Inbound flow

1. Receive and verify the webhook according to the selected channel provider.
2. Normalize the inbound message into a channel-neutral event.
3. Resolve the channel conversation/session without trusting client-supplied ownership identifiers.
4. Route the event to the appropriate agent.
5. Agent reads verified Commerce Core state through typed tools.
6. Consequential actions become proposals and pass the Control Plane.
7. Return a channel-neutral response.
8. Adapter formats and sends only approved outbound messages.

## Outbound contract

The adapter should expose typed operations such as:
- send_text
- send_template
- send_media
- mark_read
- send_interactive

Each operation must have:
- tenant/merchant scope;
- conversation identifier;
- idempotency key;
- message type;
- approval/policy context where required;
- provider response receipt.

## Security

- Verify provider webhook signatures before processing.
- Keep provider tokens outside Git.
- Do not trust phone numbers as ownership proof.
- Do not let the model construct arbitrary provider API requests.
- Apply rate limits and outbound frequency policy.
- Record provider message IDs for deduplication.
- Sanitize provider errors before exposing them to customers.

## Commerce boundary

The WhatsApp adapter must never:
- write orders directly;
- decrement stock directly;
- calculate authoritative totals locally;
- alter settlement records;
- bypass identity requirements;
- bypass the Control Plane.

## First PoC

The first approved implementation should be read-only:
- receive a WhatsApp message;
- identify the intent;
- search the catalog;
- return a product response;
- record an audit/event receipt.

Only after this path is verified should checkout or outbound automation be enabled.

## Success criteria

- channel events are normalized;
- duplicate webhooks are harmless;
- catalog answers use current Commerce Core data;
- no direct database writes occur from the adapter;
- provider errors are contained;
- every consequential action remains behind existing approval/control boundaries.
