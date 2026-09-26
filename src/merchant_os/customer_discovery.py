from __future__ import annotations
from typing import Any, Dict, Iterable, List
from .source_discovery import SourceDiscoveryPlanner, classify_source, MerchantEntityResolver

CUSTOMER_INTENT_TERMS = (
    "أريد", "اريد", "مطلوب", "أبحث", "ابحث", "محتاج", "من عنده",
    "وين ألقى", "وين الاقي", "متوفر", "السعر", "كم", "للشراء", "شراء"
)

class CustomerDiscoveryAgent:
    """Independent demand discovery using the same source infrastructure.

    It searches public/indexable content only and scores purchase-intent
    evidence separately from merchant scoring.
    """

    def __init__(self, provider):
        self.provider = provider

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        subject = payload.get("subject", {})
        category = subject.get("category", "")
        city = subject.get("city", "")
        terms = subject.get("discovery_terms", [])
        source_types = subject.get("source_types")
        max_queries = int(subject.get("max_discovery_queries", 40))
        per_query_limit = int(subject.get("per_query_limit", 5))
        total_limit = int(subject.get("discovery_limit", 100))

        planned = SourceDiscoveryPlanner().plan(category, city, terms, source_types, max_queries)
        findings, evidence, trace = [], [], []

        for dq in planned:
            if len(findings) >= total_limit:
                break
            # Demand is especially useful in Facebook posts/groups/Marketplace.
            if dq.platform != "facebook" and dq.priority > 1:
                continue
            query = dq.query + ' "أريد" OR "مطلوب" OR "أبحث" OR "محتاج"'
            results = self.provider.search(query, min(per_query_limit, total_limit-len(findings)))
            trace.append({"source_type": dq.source_type, "query": query, "results": len(results)})
            for r in results:
                text = f"{r.title} {r.snippet}".lower()
                intent_hits = sum(1 for term in CUSTOMER_INTENT_TERMS if term.lower() in text)
                if intent_hits == 0:
                    continue
                item = {
                    "name": r.title,
                    "url": r.url,
                    "source_url": r.url,
                    "source_type": classify_source(r.url, r.title, r.snippet),
                    "platform": dq.platform,
                    "category": category,
                    "city": city,
                    "snippet": r.snippet,
                    "captured_at": r.captured_at,
                    "intent_hits": intent_hits,
                    "intent_score": min(1.0, 0.2 * intent_hits + 0.4),
                }
                findings.append(item)
                evidence.append({"source": r.url, "captured_at": r.captured_at, "data": item})

        # Same person may appear across multiple public posts/sources.
        resolved = MerchantEntityResolver().resolve(findings)
        for item in resolved:
            item["customer_occurrences"] = item.get("occurrences", 1)
            item["customer_intent_score"] = round(
                min(1.0, float(item.get("intent_score", 0.0)) + 0.1 * (item["customer_occurrences"] - 1)), 4
            )

        resolved.sort(key=lambda x: x.get("customer_intent_score", 0), reverse=True)
        return {
            "customer_research": resolved,
            "customer_evidence": evidence,
            "customer_discovery_trace": trace,
            "customer_discovery_stats": {
                "queries": len(trace),
                "raw_intent_hits": len(findings),
                "unique_demand_entities": len(resolved),
            },
        }


class DemandSupplyMatcher:
    """Matches discovered customer demand against available merchant supply."""

    def match(self, customers: Iterable[Dict[str, Any]], merchants: Iterable[Dict[str, Any]],
              limit: int = 100) -> List[Dict[str, Any]]:
        merchants = list(merchants)
        output = []
        for customer in customers:
            matches = []
            for merchant in merchants:
                score = 0.0
                reasons = []
                if self._same(customer.get("category"), merchant.get("category")):
                    score += 0.45; reasons.append("category_match")
                if customer.get("city") and merchant.get("city") and self._same(customer["city"], merchant["city"]):
                    score += 0.30; reasons.append("location_match")
                if merchant.get("phone") or merchant.get("whatsapp"):
                    score += 0.10; reasons.append("contactable_merchant")
                if merchant.get("occurrences", 1) > 1:
                    score += 0.10; reasons.append("repeated_presence")
                score += 0.05 * float(customer.get("customer_intent_score", 0))
                matches.append({"merchant": merchant, "match_score": round(min(1.0, score), 4), "reasons": reasons})
            matches.sort(key=lambda x: x["match_score"], reverse=True)
            output.append({
                "customer": customer,
                "matches": matches[:limit],
            })
        return output

    @staticmethod
    def _same(a: Any, b: Any) -> bool:
        return bool(a and b and str(a).strip().casefold() == str(b).strip().casefold())
