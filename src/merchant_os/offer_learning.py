from __future__ import annotations

from typing import Any, Dict

WEIGHTS = {
    "impression": 0,
    "click": 2,
    "order_started": 5,
    "purchase": 10,
    "return": -8,
    "dismissed": -2,
}

class OfferLearningEngine:
    """Records offer outcomes and converts them into explainable product/offer signals."""

    def __init__(self):
        self.events = []

    def record(self, customer_id: int, offer_id: str, product_id: str,
               event_type: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if event_type not in WEIGHTS:
            raise ValueError(f"unsupported offer event: {event_type}")
        event = {
            "customer_id": customer_id,
            "offer_id": offer_id,
            "product_id": product_id,
            "event_type": event_type,
            "metadata": metadata or {},
        }
        self.events.append(event)
        return event

    def outcome(self, customer_id: int, offer_id: str | None = None) -> Dict[str, Any]:
        events = [
            e for e in self.events
            if e["customer_id"] == customer_id
            and (offer_id is None or e["offer_id"] == offer_id)
        ]
        score = sum(WEIGHTS[e["event_type"]] for e in events)
        counts = {}
        for e in events:
            counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1
        return {
            "event_count": len(events),
            "event_counts": counts,
            "outcome_score": score,
            "status": self._status(events, score),
            "last_event": events[-1] if events else None,
        }

    def product_learning(self, product_id: str) -> Dict[str, Any]:
        events = [e for e in self.events if e["product_id"] == product_id]
        score = sum(WEIGHTS[e["event_type"]] for e in events)
        return {
            "product_id": product_id,
            "event_count": len(events),
            "event_counts": self._counts(events),
            "learning_score": score,
        }

    @staticmethod
    def _counts(events):
        out = {}
        for e in events:
            out[e["event_type"]] = out.get(e["event_type"], 0) + 1
        return out

    @staticmethod
    def _status(events, score):
        if not events:
            return "unknown"
        if any(e["event_type"] == "purchase" for e in events):
            return "converted"
        if any(e["event_type"] == "order_started" for e in events):
            return "high_intent"
        if any(e["event_type"] == "click" for e in events):
            return "engaged"
        if score < 0:
            return "negative"
        return "seen"
