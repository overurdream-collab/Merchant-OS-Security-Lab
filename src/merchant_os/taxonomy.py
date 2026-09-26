from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
import re


# Canonical, expandable Yemen-oriented taxonomy. Labels are data, not assumptions.
MERCHANT_CATEGORIES = {
    "fashion": {"label_ar": "ملابس وأزياء", "keywords": ("ملابس","أزياء","فساتين","عبايات","ثياب","قمصان","أحذية","شنط")},
    "home_tools": {"label_ar": "أدوات منزلية", "keywords": ("أدوات منزلية","أواني","مطبخ","مفروشات","منظفات","أجهزة منزلية")},
    "electronics": {"label_ar": "إلكترونيات", "keywords": ("جوال","هاتف","آيفون","سامسونج","لابتوب","كمبيوتر","إلكترونيات","سماعات")},
    "beauty": {"label_ar": "تجميل وعناية شخصية", "keywords": ("تجميل","مكياج","عطور","عناية","كوزمتك","صالون","بشرة","شعر")},
    "food_grocery": {"label_ar": "غذاء وبقالة", "keywords": ("بقالة","مواد غذائية","غذاء","بهارات","مكسرات","حلويات","مطعم","مخبز")},
    "auto_parts": {"label_ar": "قطع غيار وسيارات", "keywords": ("قطع غيار","سيارات","إطارات","بطاريات","زيوت","أكسسوارات سيارات")},
    "furniture": {"label_ar": "أثاث", "keywords": ("أثاث","غرف نوم","كنب","مجالس","مطابخ تفصيل")},
    "building": {"label_ar": "بناء وأدوات", "keywords": ("مواد بناء","سباكة","كهرباء","دهانات","حديد","أدوات بناء")},
    "pharmacy_health": {"label_ar": "صحة وصيدليات", "keywords": ("صيدلية","مستلزمات طبية","نظارات","أجهزة طبية")},
    "services": {"label_ar": "خدمات", "keywords": ("خدمات","صيانة","تصميم","تصوير","نقل","توصيل","تعليم")},
    "other": {"label_ar": "أخرى", "keywords": ()},
}

GEOGRAPHY_LEVELS = ("country", "governorate", "city", "district", "neighborhood", "unknown")
CUSTOMER_SEGMENTS = ("consumer", "business", "unknown")


@dataclass(frozen=True)
class Classification:
    code: str
    label_ar: str
    confidence: float
    evidence: List[str]
    source: str


class MerchantTaxonomy:
    """Classifies merchants from observed evidence; never invents missing facts."""

    def classify(self, merchant: Dict[str, Any]) -> Dict[str, Any]:
        text = " ".join(str(merchant.get(k, "") or "") for k in
                        ("name", "category", "snippet", "description", "product_text")).casefold()
        explicit = str(merchant.get("category_code") or "").strip()
        if explicit in MERCHANT_CATEGORIES:
            c = MERCHANT_CATEGORIES[explicit]
            return self._result(explicit, c["label_ar"], 1.0, ["explicit_category"], "merchant_record")

        scores = []
        for code, spec in MERCHANT_CATEGORIES.items():
            hits = [kw for kw in spec["keywords"] if kw.casefold() in text]
            if hits:
                scores.append((len(hits), code, hits))
        if not scores:
            return self._result("other", MERCHANT_CATEGORIES["other"]["label_ar"], 0.0, [], "unclassified")
        scores.sort(reverse=True)
        hits, code, evidence = scores[0]
        confidence = min(0.98, 0.45 + 0.12 * hits)
        return self._result(code, MERCHANT_CATEGORIES[code]["label_ar"], confidence, evidence, "observed_text")

    def facets(self, merchant: Dict[str, Any]) -> Dict[str, Any]:
        c = self.classify(merchant)
        return {
            "primary_category": c["code"],
            "primary_category_label": c["label_ar"],
            "category_confidence": c["confidence"],
            "category_evidence": c["evidence"],
            "merchant_type": self._merchant_type(merchant),
            "sales_channels": self._channels(merchant),
            "geography": self._geography(merchant),
            "scale": self._scale(merchant),
        }

    @staticmethod
    def _merchant_type(m: Dict[str, Any]) -> str:
        text = " ".join(str(m.get(k, "") or "").casefold() for k in ("name","snippet","description"))
        if any(x in text for x in ("جملة","wholesale","wholesaler")): return "wholesaler"
        if any(x in text for x in ("مصنع","factory","manufactur")): return "manufacturer"
        if any(x in text for x in ("موزع","وكيل","distributor","dealer")): return "distributor"
        if any(x in text for x in ("متجر","محل","shop","store")): return "retailer"
        return "unknown"

    @staticmethod
    def _channels(m: Dict[str, Any]) -> List[str]:
        values = []
        for key in ("channel","platform","source_type"):
            v = m.get(key)
            if v and v not in values: values.append(str(v))
        for v in m.get("channels", []) or []:
            if v and v not in values: values.append(str(v))
        return sorted(values)

    @staticmethod
    def _geography(m: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "governorate": m.get("governorate"),
            "city": m.get("city"),
            "district": m.get("district"),
            "neighborhood": m.get("neighborhood"),
            "level": "city" if m.get("city") else "unknown",
            "verified": bool(m.get("location_verified")),
        }

    @staticmethod
    def _scale(m: Dict[str, Any]) -> Dict[str, Any]:
        # Sales/revenue are only classified when observed in records; never inferred from followers.
        if m.get("sales_volume") is not None:
            value = float(m["sales_volume"])
            band = "high" if value >= 1000 else "medium" if value >= 100 else "low"
            return {"basis": "observed_sales_volume", "band": band, "value": value}
        return {"basis": "unknown", "band": "unknown"}

    @staticmethod
    def _result(code, label, confidence, evidence, source):
        return {"code": code, "label_ar": label, "confidence": round(confidence,4),
                "evidence": list(evidence), "source": source}


class CustomerTaxonomy:
    """Customer segmentation using explicit/observed attributes only."""

    def classify(self, customer: Dict[str, Any]) -> Dict[str, Any]:
        segments = []
        if customer.get("customer_type") in CUSTOMER_SEGMENTS:
            segments.append(customer["customer_type"])
        else:
            text = " ".join(str(customer.get(k, "") or "").casefold() for k in
                            ("name","snippet","description","intent_text"))
            if any(x in text for x in ("شركة","مؤسسة","مطعم","متجر","بقالة","مكتب")):
                segments.append("business")
            elif customer.get("intent") == "purchase":
                segments.append("consumer")
            else:
                segments.append("unknown")

        age = self._verified_age(customer)
        geography = {
            "governorate": customer.get("governorate"),
            "city": customer.get("city"),
            "district": customer.get("district"),
            "neighborhood": customer.get("neighborhood"),
            "verified": bool(customer.get("location_verified")),
        }
        return {
            "customer_type": segments[0],
            "age": age,
            "geography": geography,
            "purchase_categories": self._categories(customer),
            "purchase_frequency": customer.get("purchase_frequency", "unknown"),
            "budget_band": self._budget_band(customer.get("budget")),
            "intent_strength": customer.get("intent_score", 0.0),
        }

    @staticmethod
    def _verified_age(c: Dict[str, Any]) -> Dict[str, Any]:
        # Do not infer age from names, photos, language, or appearance.
        if c.get("age") is None or not c.get("age_verified"):
            return {"value": None, "band": "unknown", "verified": False}
        age = int(c["age"])
        band = "18-24" if age < 25 else "25-34" if age < 35 else "35-44" if age < 45 else "45-54" if age < 55 else "55+"
        return {"value": age, "band": band, "verified": True}

    @staticmethod
    def _categories(c: Dict[str, Any]) -> List[str]:
        value = c.get("purchase_categories") or c.get("category")
        if isinstance(value, list): return [str(x) for x in value if x]
        return [str(value)] if value else []

    @staticmethod
    def _budget_band(b: Any) -> str:
        if not isinstance(b, dict) or b.get("value") is None: return "unknown"
        v = float(b["value"])
        return "low" if v < 100000 else "medium" if v < 500000 else "high"


def enrich_merchant(merchant: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(merchant)
    out["taxonomy"] = MerchantTaxonomy().facets(out)
    return out


def enrich_customer(customer: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(customer)
    out["taxonomy"] = CustomerTaxonomy().classify(out)
    return out
