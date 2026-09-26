from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

STATES = (
    "draft", "approved", "ready", "sent", "delivered",
    "read", "clicked", "ordered", "purchased", "returned", "failed"
)

TRANSITIONS = {
    "draft": {"approved"},
    "approved": {"ready"},
    "ready": {"sent", "failed"},
    "sent": {"delivered", "read", "clicked", "failed"},
    "delivered": {"read", "clicked", "ordered", "failed"},
    "read": {"clicked", "ordered", "failed"},
    "clicked": {"ordered", "failed"},
    "ordered": {"purchased", "returned", "failed"},
    "purchased": {"returned"},
    "returned": set(),
    "failed": set(),
}

class OfferLifecycle:
    """Persistent-ready state machine contract for offer delivery and outcomes."""

    def __init__(self):
        self.records: Dict[str, Dict[str, Any]] = {}

    def create(self, offer_id: str, customer_id: int, product_id: str) -> Dict[str, Any]:
        if offer_id in self.records:
            return self.records[offer_id]
        record = {
            "offer_id": offer_id,
            "customer_id": customer_id,
            "product_id": product_id,
            "state": "draft",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.records[offer_id] = record
        return record

    def transition(self, offer_id: str, state: str, metadata: Dict[str, Any] | None = None):
        if state not in STATES:
            raise ValueError("unsupported_offer_state")
        if offer_id not in self.records:
            raise ValueError("offer_not_found")
        current = self.records[offer_id]["state"]
        if state != current and state not in TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid_offer_transition:{current}->{state}")
        self.records[offer_id]["state"] = state
        self.records[offer_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        if metadata:
            self.records[offer_id].setdefault("metadata", {}).update(metadata)
        return self.records[offer_id]

    def get(self, offer_id: str):
        return self.records.get(offer_id)
