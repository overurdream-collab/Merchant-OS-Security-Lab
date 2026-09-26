from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any, Dict, Iterable, List
from .metrics import MetricsEngine


class DataIntelligenceAgent:
    """Decision-grade business intelligence over observed data.

    The agent separates observed metrics from hypotheses, detects blind spots,
    and emits evidence requirements rather than inventing missing facts.
    """

    def analyze(
        self,
        merchants: Iterable[Dict[str, Any]] = (),
        customers: Iterable[Dict[str, Any]] = (),
        events: Iterable[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        merchants, customers = list(merchants), list(customers)
        outcome = MetricsEngine().summarize(events)
        merchant_metrics = self._merchant_metrics(merchants)
        customer_metrics = self._customer_metrics(customers)
        market = self._market_signals(merchants, customers)
        financial = outcome.get("financial", {})
        financial_safety = (
            financial.get("commission_observed", 0) == 0
            and financial.get("order_value_observed", 0) == 0
            and financial.get("payment_collected_observed", 0) == 0
        )
        return {
            "merchant_metrics": merchant_metrics,
            "customer_metrics": customer_metrics,
            "market_signals": market,
            "outcome_metrics": outcome,
            "financial_safety": financial_safety,
            "performance_signals": self._performance_signals(merchants, customers, outcome),
            "trend_signals": self._trend_signals(events),
            "anomalies": self._anomalies(outcome),
            "cohorts": self._cohorts(customers),
            "funnel_leakage": self._funnel_leakage(outcome),
            "blind_spots": self._blind_spots(merchants, customers, outcome),
            "hypotheses": self._hypotheses(merchant_metrics, customer_metrics, market, outcome),
            "data_gaps": self._gaps(merchants, customers),
            "data_sufficiency": self._sufficiency(merchants, customers, outcome),
        }

    def _merchant_metrics(self, rows):
        categories = Counter((r.get("taxonomy") or {}).get("primary_category", "unknown") for r in rows)
        cities = Counter(r.get("city") or (r.get("taxonomy") or {}).get("geography", {}).get("city") or "unknown" for r in rows)
        types = Counter((r.get("taxonomy") or {}).get("merchant_type", "unknown") for r in rows)
        return {"count": len(rows), "categories": dict(categories), "cities": dict(cities), "merchant_types": dict(types)}

    def _customer_metrics(self, rows):
        categories, cities, types = Counter(), Counter(), Counter()
        for r in rows:
            tax = r.get("taxonomy") or {}
            categories.update(tax.get("purchase_categories") or [r.get("category") or "unknown"])
            cities[tax.get("geography", {}).get("city") or r.get("city") or "unknown"] += 1
            types[tax.get("customer_type", "unknown")] += 1
        return {"count": len(rows), "purchase_categories": dict(categories), "cities": dict(cities), "customer_types": dict(types)}

    def _market_signals(self, merchants, customers):
        supply = Counter((m.get("taxonomy") or {}).get("primary_category", "unknown") for m in merchants)
        demand = Counter()
        for c in customers:
            demand.update((c.get("taxonomy") or {}).get("purchase_categories") or [c.get("category") or "unknown"])
        gaps = []
        for category, count in demand.items():
            if category == "unknown":
                continue
            ratio = count / max(1, supply.get(category, 0))
            if supply.get(category, 0) == 0 or ratio >= 2:
                gaps.append({"category": category, "demand": count, "supply": supply.get(category, 0), "demand_supply_ratio": round(ratio, 2)})
        return {"demand_supply_gaps": sorted(gaps, key=lambda x: x["demand_supply_ratio"], reverse=True)}

    def _performance_signals(self, merchants, customers, outcome):
        signals = []
        if outcome.get("conversion", {}).get("merchant_contact_to_response") is not None:
            signals.append({"code": "merchant_response_rate", "value": outcome["conversion"]["merchant_contact_to_response"], "evidence": "business_events"})
        if outcome.get("delivery", {}).get("return_rate") is not None:
            signals.append({"code": "return_rate", "value": outcome["delivery"]["return_rate"], "evidence": "business_events"})
        if merchants and customers:
            signals.append({"code": "two_sided_market_observed", "merchants": len(merchants), "customers": len(customers), "evidence": "profiles"})
        return signals

    def _trend_signals(self, events):
        rows = list(events or [])
        if len(rows) < 2:
            return []
        counts = Counter(str(x.get("event_type", "unknown")) for x in rows)
        return [{"event_type": k, "observations": v, "basis": "observed_event_count"} for k, v in counts.items()]

    def _anomalies(self, outcome):
        anomalies = []
        delivery = outcome.get("delivery", {})
        if delivery.get("return_rate") is not None and delivery["return_rate"] > 0.20:
            anomalies.append({"code": "high_return_rate", "value": delivery["return_rate"], "requires_validation": True})
        conversion = outcome.get("conversion", {})
        if conversion.get("merchant_contact_to_response") is not None and conversion["merchant_contact_to_response"] < 0.10:
            anomalies.append({"code": "low_merchant_response", "value": conversion["merchant_contact_to_response"], "requires_validation": True})
        return anomalies

    def _cohorts(self, customers):
        categories = Counter()
        for c in customers:
            tax = c.get("taxonomy") or {}
            for category in tax.get("purchase_categories") or [c.get("category") or "unknown"]:
                categories[category] += 1
        return {"by_purchase_category": dict(categories), "basis": "observed_customer_profiles"}

    def _funnel_leakage(self, outcome):
        conversion = outcome.get("conversion", {})
        stages = [
            ("merchant_contact_to_response", conversion.get("merchant_contact_to_response")),
            ("merchant_response_to_conversion", conversion.get("merchant_response_to_conversion")),
            ("contact_to_order", conversion.get("contact_to_order")),
        ]
        observed = [{"stage": name, "rate": rate} for name, rate in stages if rate is not None]
        return {"observed": observed, "attention_required": [x for x in observed if x["rate"] < 0.20]}

    def _blind_spots(self, merchants, customers, outcome):
        spots = []
        if merchants and not outcome.get("financial", {}).get("commission_observed"):
            spots.append({"code": "commission_visibility", "reason": "no observed commission events"})
        if customers and not any((c.get("taxonomy") or {}).get("purchase_frequency") for c in customers):
            spots.append({"code": "customer_frequency", "reason": "purchase frequency not observed"})
        if merchants and not any((m.get("taxonomy") or {}).get("geography", {}).get("verified") for m in merchants):
            spots.append({"code": "merchant_geography_verification", "reason": "geography lacks verified evidence"})
        return spots

    def _hypotheses(self, merchant_metrics, customer_metrics, market, outcome):
        hypotheses = []
        for gap in market.get("demand_supply_gaps", [])[:10]:
            hypotheses.append({
                "code": "close_market_gap",
                "category": gap["category"],
                "hypothesis": "Increasing verified supply in this category may improve fulfillment of observed demand.",
                "evidence_required": ["verified merchant supply", "orders", "delivery outcomes"],
                "requires_validation": True,
            })
        if outcome.get("delivery", {}).get("return_rate") is not None and outcome["delivery"]["return_rate"] > 0:
            hypotheses.append({
                "code": "reduce_returns",
                "hypothesis": "A measurable share of returns may be addressable through better product/customer qualification.",
                "evidence_required": ["return reasons", "product", "customer", "merchant"],
                "requires_validation": True,
            })
        return hypotheses

    def _gaps(self, merchants, customers):
        return {
            "merchant_missing_city": sum(not (m.get("city") or (m.get("taxonomy") or {}).get("geography", {}).get("city")) for m in merchants),
            "merchant_missing_category": sum((m.get("taxonomy") or {}).get("primary_category", "unknown") == "unknown" for m in merchants),
            "customer_missing_city": sum(not (c.get("city") or (c.get("taxonomy") or {}).get("geography", {}).get("city")) for c in customers),
            "customer_missing_age": sum(not (c.get("taxonomy") or {}).get("age", {}).get("verified") for c in customers),
        }

    def _sufficiency(self, merchants, customers, outcome):
        dimensions = {
            "merchant_sample": min(1.0, len(merchants) / 20) if merchants else 0.0,
            "customer_sample": min(1.0, len(customers) / 20) if customers else 0.0,
            "event_depth": min(1.0, outcome.get("data_quality", {}).get("events_observed", 0) / 50),
        }
        observed = [v for v in dimensions.values() if v > 0]
        return {"dimensions": dimensions, "overall": round(mean(observed), 4) if observed else 0.0, "confidence_note": "sample size is a sufficiency signal, not proof of causality"}
