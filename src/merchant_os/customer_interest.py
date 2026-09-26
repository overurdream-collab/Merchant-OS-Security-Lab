from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable


EVENT_WEIGHTS = {
    "view": 1,
    "click": 2,
    "search": 3,
    "add_to_order": 5,
    "order_started": 7,
    "purchase": 10,
    "repeat_purchase": 15,
    "return": -6,
}


class CustomerInterestEngine:
    """Persists observable product/category behavior and derives explainable interest."""

    def __init__(self, database):
        self.database = database

    def record_event(self, customer_id: int, event_type: str, product_id: str | None = None,
                     category: str | None = None, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if event_type not in EVENT_WEIGHTS:
            raise ValueError(f"unsupported_event:{event_type}")
        self.database.ensure_schema()
        self.database.ensure_interest_schema()
        return self.database.save_interest_event(
            customer_id, event_type, product_id, category, metadata or {}
        )

    def profile(self, customer_id: int) -> Dict[str, Any]:
        self.database.ensure_schema()
        self.database.ensure_interest_schema()
        events = self.database.get_interest_events(customer_id)
        category_scores = defaultdict(int)
        product_scores = defaultdict(int)
        counts = defaultdict(int)
        for e in events:
            weight = EVENT_WEIGHTS[e["event_type"]]
            counts[e["event_type"]] += 1
            if e.get("category"):
                category_scores[e["category"]] += weight
            if e.get("product_id"):
                product_scores[e["product_id"]] += weight
        ranked_categories = sorted(category_scores.items(), key=lambda x: (-x[1], x[0]))
        ranked_products = sorted(product_scores.items(), key=lambda x: (-x[1], x[0]))
        return {
            "customer_id": customer_id,
            "event_count": len(events),
            "event_counts": dict(counts),
            "category_scores": dict(ranked_categories),
            "product_scores": dict(ranked_products),
            "top_categories": [x[0] for x in ranked_categories[:5]],
            "top_products": [x[0] for x in ranked_products[:5]],
            "purchase_readiness": self._readiness(events),
            "last_event": events[-1] if events else None,
        }

    @staticmethod
    def _readiness(events: Iterable[Dict[str, Any]]) -> str:
        types = {e["event_type"] for e in events}
        if "repeat_purchase" in types:
            return "very_high"
        if "purchase" in types:
            return "high"
        if "order_started" in types:
            return "medium_high"
        if "add_to_order" in types or "search" in types:
            return "medium"
        if events:
            return "low"
        return "unknown"

    def audience_for_category(self, customer_ids: Iterable[int], category: str) -> list[Dict[str, Any]]:
        return [
            self.profile(cid) for cid in customer_ids
            if self.profile(cid)["category_scores"].get(category, 0) > 0
        ]
