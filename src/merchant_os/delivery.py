from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass
class DeliveryResult:
    status: str
    channel: str
    recipient: str
    payload: Dict[str, Any]
    reason: str | None = None


class DeliveryProvider(Protocol):
    def send(self, recipient: str, payload: Dict[str, Any]) -> DeliveryResult: ...


class MockDeliveryProvider:
    """Deterministic provider for tests/local MVP; sends nothing externally."""

    channel = "mock"

    def send(self, recipient: str, payload: Dict[str, Any]) -> DeliveryResult:
        return DeliveryResult(
            status="queued",
            channel=self.channel,
            recipient=recipient,
            payload=payload,
        )


class OfferDeliveryAdapter:
    """Final gate before an offer reaches an external messaging provider."""

    def __init__(self, guard, provider: DeliveryProvider):
        self.guard = guard
        self.provider = provider

    def prepare(
        self,
        customer_id: int,
        recipient: str,
        offer_id: str,
        product_id: str,
        creative: Dict[str, Any],
    ) -> Dict[str, Any]:
        decision = self.guard.check(customer_id)
        if not decision["allowed"]:
            return {
                "status": "blocked",
                "offer_id": offer_id,
                "product_id": product_id,
                "reason": decision["reason"],
            }

        payload = {
            "offer_id": offer_id,
            "product_id": product_id,
            "creative": creative,
        }
        return {
            "status": "ready",
            "channel": getattr(self.provider, "channel", "unknown"),
            "recipient": recipient,
            "payload": payload,
        }

    def send(
        self,
        customer_id: int,
        recipient: str,
        offer_id: str,
        product_id: str,
        creative: Dict[str, Any],
    ) -> DeliveryResult | Dict[str, Any]:
        prepared = self.prepare(
            customer_id, recipient, offer_id, product_id, creative
        )
        if prepared["status"] == "blocked":
            return prepared

        result = self.provider.send(recipient, prepared["payload"])
        self.guard.record(customer_id, offer_id, "impression")
        return result
