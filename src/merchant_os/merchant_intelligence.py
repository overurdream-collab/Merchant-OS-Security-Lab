from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List
from urllib.parse import urlparse

@dataclass(frozen=True)
class MerchantScore:
    merchant: Dict[str, Any]
    score: float
    factors: Dict[str, float]
    reasons: List[str]

class MerchantIntelligenceEngine:
    """Deterministic, explainable merchant scoring for Professor OS."""

    WEIGHTS = {
        "identity": 0.15,
        "contactability": 0.15,
        "channel_presence": 0.15,
        "category_fit": 0.15,
        "location_fit": 0.10,
        "evidence_quality": 0.20,
        "freshness": 0.10,
    }

    def score(self, merchant: Dict[str, Any], evidence: List[Dict[str, Any]], subject: Dict[str, Any]) -> MerchantScore:
        factors = {
            "identity": self._identity(merchant),
            "contactability": self._contactability(merchant),
            "channel_presence": self._channels(merchant),
            "category_fit": self._fit(merchant.get("category"), subject.get("category")),
            "location_fit": self._fit(merchant.get("city"), subject.get("city")),
            "evidence_quality": self._evidence(merchant, evidence),
            "freshness": self._freshness(merchant),
        }
        total = round(sum(factors[k] * self.WEIGHTS[k] for k in self.WEIGHTS), 4)
        reasons = [f"{k}={v:.2f}" for k, v in factors.items() if v > 0]
        return MerchantScore(merchant=merchant, score=total, factors=factors, reasons=reasons)

    def rank(self, merchants: List[Dict[str, Any]], evidence: List[Dict[str, Any]], subject: Dict[str, Any]) -> List[Dict[str, Any]]:
        scored = [self.score(m, evidence, subject) for m in merchants]
        scored.sort(key=lambda x: x.score, reverse=True)
        return [{"rank": i + 1, "merchant": x.merchant, "score": x.score,
                 "factors": x.factors, "reasons": x.reasons} for i, x in enumerate(scored)]

    @staticmethod
    def _identity(m: Dict[str, Any]) -> float:
        return 1.0 if m.get("name") and (m.get("url") or m.get("source_url")) else 0.5 if m.get("name") else 0.0

    @staticmethod
    def _contactability(m: Dict[str, Any]) -> float:
        return min(1.0, sum(bool(m.get(k)) for k in ("phone", "whatsapp", "email")) / 2)

    @staticmethod
    def _channels(m: Dict[str, Any]) -> float:
        channels = m.get("channels", m.get("channel"))
        if isinstance(channels, str): channels = [channels]
        return min(1.0, len(channels or []) / 2)

    @staticmethod
    def _fit(actual: Any, expected: Any) -> float:
        if not expected: return 0.5
        if not actual: return 0.0
        return 1.0 if str(actual).strip().lower() == str(expected).strip().lower() else 0.25

    @staticmethod
    def _evidence(m: Dict[str, Any], evidence: List[Dict[str, Any]]) -> float:
        url = m.get("url") or m.get("source_url")
        urls = set(m.get("source_urls", []))
        if url: urls.add(url)
        matching = [e for e in evidence if e.get("source") in urls]
        occurrences = max(int(m.get("occurrences", 0)), len(urls), len(matching))
        if not matching and occurrences <= 1: return 0.0
        return min(1.0, occurrences / 3)

    @staticmethod
    def _freshness(m: Dict[str, Any]) -> float:
        return 1.0 if m.get("captured_at") else 0.5

def rank_merchants(merchants, evidence, subject, limit=None):
    result = MerchantIntelligenceEngine().rank(merchants, evidence, subject)
    return result[:limit] if limit else result
