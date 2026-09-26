from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from .unified_data import list_events


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_row(row: Any) -> Dict[str, Any]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, dict):
        return row
    raise TypeError(f"unsupported event row type: {type(row).__name__}")


class MetricsEngine:
    """Computes observed outcome metrics from the canonical business event stream.

    No metric is fabricated: absent events produce zero/unknown values.
    """

    def summarize(self, events: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
        raw_rows = list(events) if events is not None else list_events()
        rows = [_normalize_row(row) for row in raw_rows]
        by_type = Counter(row["event_type"] for row in rows)
        orders = [r for r in rows if r["event_type"] == "order_created"]
        delivered = {r["subject_id"] for r in rows if r["event_type"] == "order_delivered"}
        returned = {r["subject_id"] for r in rows if r["event_type"] == "order_returned"}
        repeat = {r["subject_id"] for r in rows if r["event_type"] == "order_repeat"}

        revenue = sum(float(r["value"] or 0) for r in rows if r["event_type"] == "order_created")
        collected = sum(float(r["value"] or 0) for r in rows if r["event_type"] == "payment_collected")
        commission = sum(float(r["value"] or 0) for r in rows if r["event_type"] == "commission_earned")

        created_ids = {r["subject_id"] for r in orders}
        response_times = self._response_times(rows)

        return {
            "event_counts": dict(by_type),
            "orders": {
                "created": len(orders),
                "delivered": len(created_ids & delivered),
                "returned": len(created_ids & returned),
                "repeat_orders": len(created_ids & repeat),
            },
            "financial": {
                "order_value_observed": revenue,
                "payment_collected_observed": collected,
                "commission_observed": commission,
            },
            "conversion": {
                "merchant_contact_to_response": self._rate(by_type["merchant_response"], by_type["merchant_contacted"]),
                "merchant_response_to_conversion": self._rate(by_type["merchant_converted"], by_type["merchant_response"]),
                "contact_to_order": self._rate(by_type["order_created"], by_type["merchant_contacted"]),
            },
            "delivery": {
                "delivery_rate": self._rate(len(created_ids & delivered), len(created_ids)),
                "return_rate": self._rate(len(created_ids & returned), len(created_ids)),
            },
            "response_time": response_times,
            "data_quality": {
                "events_observed": len(rows),
                "financial_events": sum(by_type[t] for t in ("order_created", "payment_collected", "commission_earned")),
                "source_coverage": sum(bool(r.get("source")) for r in rows) / len(rows) if rows else 0.0,
                "evidence_coverage": sum(bool(r.get("evidence_id")) for r in rows) / len(rows) if rows else 0.0,
            },
        }

    @staticmethod
    def _rate(numerator: float, denominator: float) -> Optional[float]:
        return round(float(numerator) / float(denominator), 4) if denominator else None

    @staticmethod
    def _response_times(rows):
        contacted = {}
        durations = []
        for row in sorted(rows, key=lambda x: x["occurred_at"]):
            sid = row["subject_id"]
            if row["event_type"] == "merchant_contacted":
                contacted[sid] = _parse_time(row["occurred_at"])
            elif row["event_type"] == "merchant_response" and sid in contacted:
                delta = (_parse_time(row["occurred_at"]) - contacted[sid]).total_seconds()
                if delta >= 0:
                    durations.append(delta)
                    contacted.pop(sid, None)
        if not durations:
            return {"observed_count": 0, "average_seconds": None, "median_seconds": None}
        durations.sort()
        mid = len(durations) // 2
        median = durations[mid] if len(durations) % 2 else (durations[mid - 1] + durations[mid]) / 2
        return {
            "observed_count": len(durations),
            "average_seconds": round(sum(durations) / len(durations), 2),
            "median_seconds": round(median, 2),
        }
