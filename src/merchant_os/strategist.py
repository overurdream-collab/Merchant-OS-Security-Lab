from __future__ import annotations

from typing import Any, Dict, List


class StrategicDeveloperAgent:
    """Continuously searches for strategic opportunities and blind spots.

    Outputs are evidence-backed hypotheses. It never executes or self-modifies
    production policy/code.
    """

    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        merchants = list(context.get("merchants", []) or [])
        customers = list(context.get("customers", []) or [])
        data = context.get("data_intelligence", {}) or {}
        outcome = data.get("outcome_metrics", {}) or {}
        proposals: List[Dict[str, Any]] = []

        gaps = data.get("data_gaps", {})
        if gaps.get("merchant_missing_city"):
            proposals.append(self._proposal("merchant_geography", "Strengthen governorate/district/neighborhood evidence capture.", ["verified location"]))
        if gaps.get("customer_missing_city"):
            proposals.append(self._proposal("customer_geography", "Strengthen public location evidence and confidence tracking.", ["verified demand location"]))
        if gaps.get("customer_missing_age"):
            proposals.append(self._proposal("customer_age", "Keep age unknown unless verified; use consent-based enrichment where appropriate.", ["verified age or consent"]))

        for gap in data.get("market_signals", {}).get("demand_supply_gaps", [])[:10]:
            proposals.append(self._proposal(
                "market_gap:" + str(gap["category"]),
                "Test whether adding verified supply can close observed demand in this category.",
                ["demand evidence", "verified merchant supply", "orders", "delivery outcomes"],
            ))

        for blind in data.get("blind_spots", [])[:10]:
            proposals.append(self._proposal(
                "blind_spot:" + blind["code"],
                "Close a decision-critical information gap before scaling this area.",
                [blind["code"] + " evidence"],
            ))

        if merchants and not outcome.get("conversion", {}).get("merchant_contact_to_response"):
            proposals.append(self._proposal("merchant_funnel", "Instrument outreach stages so channel and message performance can be compared.", ["contact", "response", "conversion"]))

        if outcome.get("orders", {}).get("created", 0) > outcome.get("orders", {}).get("delivered", 0):
            proposals.append(self._proposal("fulfillment_visibility", "Track delivery and return outcomes against every order to expose operational leakage.", ["order_created", "order_delivered", "order_returned"]))

        if merchants and not outcome.get("conversion", {}).get("merchant_response_to_conversion"):
            proposals.append(self._proposal("merchant_performance", "Instrument merchant response, conversion, delivery and return outcomes so merchant performance can be compared on observed evidence.", ["merchant contact", "merchant response", "merchant conversion", "delivery outcomes"]))

        if customers and not any("purchase_history" in c for c in customers):
            proposals.append(self._proposal("customer_lifecycle", "Capture discovered → contacted → interested → ordered → repeated → inactive lifecycle events.", ["customer lifecycle events"]))

        if data.get("anomalies"):
            for anomaly in data["anomalies"][:10]:
                proposals.append(self._proposal("anomaly:" + anomaly["code"], "Run a focused investigation before treating this signal as a structural problem.", ["time series", "segment breakdown", "root-cause evidence"]))

        proposals = self._dedupe(proposals)
        return {
            "suggestions": proposals,
            "count": len(proposals),
            "blind_spots": data.get("blind_spots", []),
            "development_queue": self._development_queue(data, proposals),
        }

    def _development_queue(self, data, proposals):
        queue = []
        for p in proposals[:20]:
            queue.append({
                "code": p["code"],
                "next_step": "collect_evidence",
                "validation_required": True,
                "promotion_rule": "evidence -> test -> outcome -> approval",
            })
        return queue

    @staticmethod
    def _proposal(code: str, description: str, evidence_required: List[str]) -> Dict[str, Any]:
        return {
            "code": code,
            "description": description,
            "priority": "candidate",
            "requires_validation": True,
            "evidence_required": evidence_required,
            "execution": "blocked_until_validated_and_approved",
        }

    @staticmethod
    def _dedupe(items):
        seen = set()
        result = []
        for item in items:
            if item["code"] in seen:
                continue
            seen.add(item["code"])
            result.append(item)
        return result
