from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, Optional


SIGNAL_TYPES = {
    "demand",
    "complaint",
    "price_gap",
    "product_gap",
    "competitor_signal",
    "trend",
    "opportunity_candidate",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Optional[str], limit: int = 4000) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def stable_signal_id(source: str, external_id: Optional[str], text: str) -> str:
    basis = "|".join([
        str(source or "").strip().lower(),
        str(external_id or "").strip(),
        _clean_text(text, 1000),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MarketSignal:
    source: str
    signal_type: str
    text: str
    signal_id: Optional[str] = None
    external_id: Optional[str] = None
    source_url: Optional[str] = None
    category: Optional[str] = None
    subject: Optional[str] = None
    location: Optional[str] = None
    intent: Optional[str] = None
    urgency: Optional[str] = None
    confidence: float = 0.0
    captured_at: Optional[str] = None
    tags: tuple = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MarketSignal":
        source = _clean_text(self.source, 100).lower()
        signal_type = _clean_text(self.signal_type, 80).lower()
        if signal_type not in SIGNAL_TYPES:
            raise ValueError(f"Unsupported signal_type: {signal_type}")

        text = _clean_text(self.text)
        if not source:
            raise ValueError("source is required")
        if not text:
            raise ValueError("text is required")

        confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        signal_id = self.signal_id or stable_signal_id(source, self.external_id, text)

        return MarketSignal(
            source=source,
            signal_type=signal_type,
            text=text,
            signal_id=signal_id,
            external_id=_clean_text(self.external_id, 500) or None,
            source_url=_clean_text(self.source_url, 2000) or None,
            category=_clean_text(self.category, 200) or None,
            subject=_clean_text(self.subject, 300) or None,
            location=_clean_text(self.location, 300) or None,
            intent=_clean_text(self.intent, 100) or None,
            urgency=_clean_text(self.urgency, 50) or None,
            confidence=confidence,
            captured_at=self.captured_at or utc_now(),
            tags=tuple(sorted({_clean_text(tag, 80).lower() for tag in self.tags if _clean_text(tag, 80)})),
            metadata=dict(self.metadata or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self.normalized())
        result["tags"] = list(result["tags"])
        return result


def signal_from_item(item: Dict[str, Any], default_source: Optional[str] = None) -> MarketSignal:
    if not isinstance(item, dict):
        raise TypeError("signal item must be a dict")

    return MarketSignal(
        source=item.get("source") or default_source or "",
        signal_type=item.get("signal_type") or item.get("type") or "demand",
        text=item.get("text") or item.get("content") or item.get("body") or "",
        signal_id=item.get("signal_id"),
        external_id=item.get("external_id") or item.get("id"),
        source_url=item.get("source_url") or item.get("url"),
        category=item.get("category"),
        subject=item.get("subject") or item.get("product"),
        location=item.get("location"),
        intent=item.get("intent"),
        urgency=item.get("urgency"),
        confidence=item.get("confidence", 0.0),
        captured_at=item.get("captured_at"),
        tags=tuple(item.get("tags") or ()),
        metadata=item.get("metadata") or {},
    ).normalized()
