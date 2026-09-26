from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List


class CustomerVoiceEngine:
    """Turns accessible customer feedback into explainable market signals."""

    THEMES = {
        "price": ("السعر", "غالي", "رخيص", "بكم", "خصم", "تخفيض"),
        "availability": ("متوفر", "موجود", "توفر", "مقاس", "لون", "نفد"),
        "quality": ("جودة", "خامة", "أصلي", "تقليد", "سيئ", "ممتاز"),
        "delivery": ("توصيل", "مندوب", "شحن", "وصل", "التوصيل"),
        "returns": ("استرجاع", "ارجاع", "مرتجع", "إرجاع", "تبديل"),
        "product_request": ("أريد", "ابغى", "أبغى", "محتاج", "أبحث", "أدور"),
    }
    POSITIVE = ("ممتاز", "رائع", "حلو", "ممتازة", "جميل", "أنصح")
    NEGATIVE = ("غالي", "سيئ", "سيئة", "مشكلة", "متأخر", "رديء", "ما عجب")
    
    def analyze(self, text: str) -> Dict[str, Any]:
        text = str(text or "").strip()
        lowered = text.casefold()
        themes = []
        for theme, terms in self.THEMES.items():
            if any(term.casefold() in lowered for term in terms):
                themes.append(theme)
        positive = sum(t.casefold() in lowered for t in self.POSITIVE)
        negative = sum(t.casefold() in lowered for t in self.NEGATIVE)
        sentiment = "positive" if positive > negative else "negative" if negative > positive else "neutral"
        return {
            "text": text,
            "themes": themes,
            "sentiment": sentiment,
            "priority": "high" if any(t in themes for t in ("availability", "product_request", "returns")) else "normal",
        }

    def summarize(self, records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        analyzed = [self.analyze(r.get("text", "")) | {k: v for k, v in r.items() if k != "text"}
                    for r in records]
        theme_counts = Counter(theme for item in analyzed for theme in item["themes"])
        sentiment_counts = Counter(item["sentiment"] for item in analyzed)
        return {
            "records": analyzed,
            "theme_counts": dict(theme_counts),
            "sentiment_counts": dict(sentiment_counts),
            "top_themes": [k for k, _ in theme_counts.most_common()],
        }
