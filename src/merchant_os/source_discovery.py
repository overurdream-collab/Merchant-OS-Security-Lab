from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse
import re


FACEBOOK_TYPES = (
    "facebook_page",
    "facebook_group",
    "facebook_marketplace",
    "facebook_post",
    "facebook_ad",
    "facebook_profile",
    "facebook_reel",
)
SECONDARY_TYPES = (
    "whatsapp_group",
    "whatsapp_community",
    "whatsapp_channel",
    "whatsapp_business",
    "telegram_group",
    "telegram_channel",
    "website",
    "classified",
    "directory",
)


@dataclass(frozen=True)
class DiscoveryQuery:
    source_type: str
    query: str
    priority: int
    platform: str


class SourceDiscoveryPlanner:
    """Builds source-specific public/indexable discovery queries.

    Facebook is deliberately expanded into multiple discovery surfaces. These
    queries target public/indexable results; they do not bypass login, private
    groups, or platform access controls.
    """

    FACEBOOK_DOMAINS = {
        "facebook_page": "site:facebook.com",
        "facebook_group": "site:facebook.com/groups",
        "facebook_marketplace": "site:facebook.com/marketplace",
        "facebook_post": "site:facebook.com",
        "facebook_ad": "site:facebook.com",
        "facebook_profile": "site:facebook.com",
        "facebook_reel": "site:facebook.com/reel",
    }

    def plan(self, category: str = "", city: str = "", terms: Iterable[str] | None = None,
             source_types: Iterable[str] | None = None, max_queries: int = 40) -> List[DiscoveryQuery]:
        category = (category or "").strip()
        city = (city or "").strip()
        terms = [str(x).strip() for x in (terms or []) if str(x).strip()]
        types = list(source_types or (FACEBOOK_TYPES + SECONDARY_TYPES))

        queries: List[DiscoveryQuery] = []
        for source_type in types:
            if source_type in self.FACEBOOK_DOMAINS:
                base = self.FACEBOOK_DOMAINS[source_type]
                variants = self._facebook_variants(base, source_type, category, city, terms)
            elif source_type.startswith("whatsapp_"):
                variants = self._whatsapp_variants(source_type, category, city, terms)
            elif source_type.startswith("telegram_"):
                variants = self._telegram_variants(source_type, category, city, terms)
            elif source_type in ("website", "classified", "directory"):
                variants = self._web_variants(source_type, category, city, terms)
            else:
                continue
            for q in variants:
                queries.append(DiscoveryQuery(source_type, q, self._priority(source_type), self._platform(source_type)))

        queries.sort(key=lambda x: (x.priority, x.source_type, x.query))
        return queries[:max_queries]

    def _facebook_variants(self, base, source_type, category, city, terms):
        anchors = [x for x in [category, city, *terms] if x]
        if not anchors:
            anchors = ["تاجر", "متجر"]
        quoted = " ".join(f'"{x}"' for x in anchors)
        variants = [f"{base} {quoted}"]
        if category and city:
            variants.append(f'{base} "{category}" "{city}"')
            variants.append(f'{base} "{category}" "{city}" بيع OR للبيع OR متجر')
        if source_type in ("facebook_group", "facebook_marketplace"):
            variants.append(f'{base} "{category}" "{city}" "واتساب"')
            variants.append(f'{base} "{category}" "{city}" "السعر"')
        if source_type == "facebook_post":
            variants.append(f'{base} "{category}" "{city}" "للطلب"')
            variants.append(f'{base} "{category}" "{city}" "متوفر"')
        if source_type == "facebook_ad":
            variants.append(f'{base} "{category}" "{city}" إعلان')
            variants.append(f'{base} "{category}" "{city}" "تواصل معنا"')
        if source_type == "facebook_reel":
            variants.append(f'{base} "{category}" "{city}"')
        return self._dedupe(variants)

    def _whatsapp_variants(self, source_type, category, city, terms):
        anchors = " ".join(f'"{x}"' for x in [category, city, *terms] if x)
        domains = {
            "whatsapp_group": "chat.whatsapp.com",
            "whatsapp_community": "chat.whatsapp.com",
            "whatsapp_channel": "whatsapp.com/channel",
            "whatsapp_business": "wa.me",
        }
        domain = domains[source_type]
        return self._dedupe([
            f'site:{domain} {anchors}',
            f'"{domain}" {anchors}',
        ])

    def _telegram_variants(self, source_type, category, city, terms):
        anchors = " ".join(f'"{x}"' for x in [category, city, *terms] if x)
        return self._dedupe([
            f'site:t.me {anchors}',
            f'site:telegram.me {anchors}',
        ])

    def _web_variants(self, source_type, category, city, terms):
        anchors = " ".join(f'"{x}"' for x in [category, city, *terms] if x)
        if source_type == "classified":
            return self._dedupe([f"{anchors} بيع شراء متجر", f"{anchors} سوق إعلانات"])
        if source_type == "directory":
            return self._dedupe([f"{anchors} دليل تجار", f"{anchors} دليل شركات"])
        return self._dedupe([f"{anchors} متجر", f"{anchors} online store"])

    @staticmethod
    def _dedupe(values):
        seen = set()
        out = []
        for value in values:
            value = " ".join(value.split()).strip()
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        return out

    @staticmethod
    def _priority(source_type):
        if source_type.startswith("facebook_"):
            return 0
        if source_type.startswith("whatsapp_"):
            return 1
        if source_type.startswith("telegram_"):
            return 2
        return 3

    @staticmethod
    def _platform(source_type):
        if source_type.startswith("facebook_"): return "facebook"
        if source_type.startswith("whatsapp_"): return "whatsapp"
        if source_type.startswith("telegram_"): return "telegram"
        return "web"


def classify_source(url: str, title: str = "", snippet: str = "") -> str:
    text = f"{url} {title} {snippet}".lower()
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if "facebook.com" in host:
        if "/marketplace" in path: return "facebook_marketplace"
        if "/groups" in path: return "facebook_group"
        if "/reel" in path: return "facebook_reel"
        if any(x in text for x in ("sponsored", "إعلان", "advert")): return "facebook_ad"
        if "/profile" in path: return "facebook_profile"
        if "/posts" in path: return "facebook_post"
        return "facebook_page"
    if "chat.whatsapp.com" in host: return "whatsapp_group"
    if "whatsapp.com" in host and "/channel" in path: return "whatsapp_channel"
    if "wa.me" in host: return "whatsapp_business"
    if "t.me" in host or "telegram.me" in host:
        return "telegram_channel" if "channel" in text else "telegram_group"
    return "website"


class MerchantEntityResolver:
    """Merge repeated public discoveries into one merchant entity."""

    @staticmethod
    def _norm(value: Any) -> str:
        return re.sub(r"\W+", "", str(value or "").strip().lower(), flags=re.UNICODE)

    @staticmethod
    def _phone(value: Any) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        if digits.startswith("00967"): digits = digits[5:]
        if digits.startswith("967"): digits = digits[3:]
        return digits[-9:] if len(digits) >= 9 else digits

    def resolve(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        indexes: Dict[str, int] = {}

        for record in records:
            url = str(record.get("url") or record.get("source_url") or "").strip()
            phone = self._phone(record.get("phone") or record.get("whatsapp"))
            name = self._norm(record.get("name"))
            city = self._norm(record.get("city"))
            keys = [f"url:{url.lower().rstrip('/')}" if url else "",
                    f"phone:{phone}" if phone else "",
                    f"namecity:{name}:{city}" if name and city else ""]
            idx = next((indexes[k] for k in keys if k and k in indexes), None)

            if idx is None:
                item = dict(record)
                item["source_urls"] = [url] if url else []
                item["source_types"] = [record.get("source_type")] if record.get("source_type") else []
                item["occurrences"] = 1
                item["evidence_sources"] = [url] if url else []
                merged.append(item)
                idx = len(merged) - 1
            else:
                item = merged[idx]
                item["occurrences"] = int(item.get("occurrences", 1)) + 1
                for field in ("phone", "whatsapp", "email", "city", "category"):
                    if not item.get(field) and record.get(field):
                        item[field] = record[field]
                if url and url not in item.setdefault("source_urls", []):
                    item["source_urls"].append(url)
                st = record.get("source_type")
                if st and st not in item.setdefault("source_types", []):
                    item["source_types"].append(st)
                if url and url not in item.setdefault("evidence_sources", []):
                    item["evidence_sources"].append(url)

            for k in keys:
                if k:
                    indexes[k] = idx

        return merged
