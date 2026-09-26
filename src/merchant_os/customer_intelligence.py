from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class DemandSignal:
    kind: str
    weight: float
    terms: tuple[str, ...]


class CustomerIntentEngine:
    """Explainable intent extraction; public evidence only."""

    SIGNALS = (
        DemandSignal("explicit_want", 0.30, ("أريد", "اريد", "أبغى", "ابغى", "حاب", "ارغب")),
        DemandSignal("looking_for", 0.28, ("أبحث عن", "ابحث عن", "أدور على", "ادور على", "وين ألقى", "وين الاقي")),
        DemandSignal("need", 0.22, ("محتاج", "احتاج", "مطلوب", "أحتاج")),
        DemandSignal("availability", 0.12, ("متوفر", "موجود", "من عنده", "عند من")),
        DemandSignal("price_question", 0.10, ("السعر", "كم", "بكم", "كم سعر")),
        DemandSignal("purchase", 0.18, ("للشراء", "شراء", "أشتري", "اشتري")),
        DemandSignal("urgency", 0.12, ("اليوم", "الآن", "عاجل", "ضروري", "بسرعة")),
    )

    def extract(self, text: str, category: str = "", city: str = "") -> Dict[str, Any]:
        text = str(text or "")
        hits = []
        score = 0.0
        kinds = set()
        for signal in self.SIGNALS:
            matched = tuple(term for term in signal.terms if term.casefold() in text.casefold())
            if matched:
                hits.append({"kind": signal.kind, "weight": signal.weight, "terms": matched})
                score += signal.weight
                kinds.add(signal.kind)

        budget = self._budget(text)
        urgency = "high" if "urgency" in kinds else "normal"
        explicit = bool(kinds & {"explicit_want", "looking_for", "need", "purchase"})
        confidence = min(1.0, score + (0.15 if explicit else 0.0))
        return {
            "intent": "purchase" if explicit else "weak_demand",
            "intent_score": round(min(1.0, score), 4),
            "intent_confidence": round(confidence, 4),
            "signal_types": sorted(kinds),
            "signals": hits,
            "budget": budget,
            "urgency": urgency,
            "category": category,
            "city": city,
        }

    @staticmethod
    def _budget(text: str) -> Dict[str, Any] | None:
        patterns = (
            r"(?:ميزانيتي|ميزانية|حدي|حدود)\s*[:-]?\s*([0-9٠-٩][0-9٠-٩,٬.]*)",
            r"(?:بحدود|حدود)\s*([0-9٠-٩][0-9٠-٩,٬.]*)",
        )
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                raw = m.group(1).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
                raw = raw.replace(",", "").replace("٬", "")
                try:
                    return {"value": float(raw), "currency": None}
                except ValueError:
                    pass
        return None


class CustomerEntityResolver:
    """Conservative demand entity merging.

    Never claims two people are identical from a name alone. Strong keys are
    public profile URL or public phone; otherwise repeated identical source URL
    is retained as one demand event.
    """

    @staticmethod
    def _norm_url(value: Any) -> str:
        return str(value or "").strip().lower().rstrip("/")

    @staticmethod
    def _phone(value: Any) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        if digits.startswith("00967"):
            digits = digits[5:]
        elif digits.startswith("967"):
            digits = digits[3:]
        return digits[-9:] if len(digits) >= 9 else digits

    def resolve(self, records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        index: Dict[str, int] = {}
        for record in records:
            url = self._norm_url(record.get("profile_url") or record.get("url") or record.get("source_url"))
            phone = self._phone(record.get("phone") or record.get("whatsapp"))
            keys = [f"url:{url}" if url else "", f"phone:{phone}" if phone else ""]
            idx = next((index[k] for k in keys if k in index and k), None)
            if idx is None:
                item = dict(record)
                item["demand_events"] = 1
                item["source_urls"] = [record.get("url")] if record.get("url") else []
                merged.append(item)
                idx = len(merged) - 1
            else:
                item = merged[idx]
                item["demand_events"] = int(item.get("demand_events", 1)) + 1
                for field in ("phone", "whatsapp", "profile_url", "city", "category", "budget"):
                    if not item.get(field) and record.get(field):
                        item[field] = record[field]
                if record.get("url") and record["url"] not in item.setdefault("source_urls", []):
                    item["source_urls"].append(record["url"])
            for key in keys:
                if key:
                    index[key] = idx
        return merged


class CustomerDiscoveryEngine:
    """Facebook-first demand discovery with intent extraction and resolution."""

    def __init__(self, provider):
        self.provider = provider
        self.intent = CustomerIntentEngine()
        self.resolver = CustomerEntityResolver()

    def discover(self, queries: Iterable[Dict[str, Any]], category: str = "", city: str = "",
                 per_query_limit: int = 5, total_limit: int = 100) -> Dict[str, Any]:
        events = []
        trace = []
        for q in queries:
            if len(events) >= total_limit:
                break
            query = str(q.get("query", "")).strip()
            if not query:
                continue
            results = self.provider.search(query, min(per_query_limit, total_limit - len(events)))
            trace.append({"query": query, "source_type": q.get("source_type"), "results": len(results)})
            for result in results:
                analysis = self.intent.extract(
                    f"{result.title} {result.snippet}", category=category, city=city
                )
                if analysis["intent"] == "weak_demand":
                    continue
                event = {
                    "name": result.title,
                    "url": result.url,
                    "source_url": result.url,
                    "source_type": q.get("source_type"),
                    "platform": q.get("platform"),
                    "snippet": result.snippet,
                    "captured_at": result.captured_at,
                    **analysis,
                }
                events.append(event)

        customers = self.resolver.resolve(events)
        for customer in customers:
            events_count = max(1, int(customer.get("demand_events", 1)))
            customer["repeat_signal"] = min(1.0, 0.2 * events_count)
            customer["customer_priority"] = round(
                min(1.0, float(customer.get("intent_score", 0)) * 0.7 +
                    float(customer.get("intent_confidence", 0)) * 0.2 +
                    customer["repeat_signal"] * 0.1), 4
            )
        customers.sort(key=lambda x: x["customer_priority"], reverse=True)
        return {
            "customers": customers,
            "events": events,
            "trace": trace,
            "stats": {
                "queries": len(trace),
                "demand_events": len(events),
                "unique_customers": len(customers),
            },
        }
