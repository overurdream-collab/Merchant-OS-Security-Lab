from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List


class OfferFrequencyGuard:
    """Prevents repetitive offers and suppresses customers after negative signals."""

    def __init__(self, cooldown_hours: int = 24, max_offers: int = 3,
                 window_hours: int = 24, negative_cooldown_hours: int = 72):
        self.cooldown = timedelta(hours=cooldown_hours)
        self.max_offers = max_offers
        self.window = timedelta(hours=window_hours)
        self.negative_cooldown = timedelta(hours=negative_cooldown_hours)
        self.events: List[Dict] = []

    def record(self, customer_id: int, offer_id: str, event_type: str,
               occurred_at: datetime | None = None) -> Dict:
        event = {"customer_id": customer_id, "offer_id": offer_id,
                 "event_type": event_type,
                 "occurred_at": occurred_at or datetime.now(timezone.utc)}
        self.events.append(event)
        return event

    def check(self, customer_id: int, now: datetime | None = None) -> Dict:
        now = now or datetime.now(timezone.utc)
        recent = [e for e in self.events if e["customer_id"] == customer_id
                  and now - e["occurred_at"] <= self.window]
        negative = [e for e in self.events if e["customer_id"] == customer_id
                    and e["event_type"] in {"dismissed", "return"}
                    and now - e["occurred_at"] <= self.negative_cooldown]
        last_offer = max((e for e in self.events if e["customer_id"] == customer_id),
                         key=lambda e: e["occurred_at"], default=None)
        if negative:
            return {"allowed": False, "reason": "negative_signal_cooldown",
                    "recent_offers": len(recent)}
        if len(recent) >= self.max_offers:
            return {"allowed": False, "reason": "daily_offer_limit",
                    "recent_offers": len(recent)}
        if last_offer and now - last_offer["occurred_at"] < self.cooldown:
            return {"allowed": False, "reason": "offer_cooldown",
                    "recent_offers": len(recent)}
        return {"allowed": True, "reason": "eligible", "recent_offers": len(recent)}
