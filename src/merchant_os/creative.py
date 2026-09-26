from __future__ import annotations

from typing import Any, Dict, List


class ProductCreativeEngine:
    """Builds publish-ready creative packages without pretending external media was generated."""

    TYPES = ("image", "short_video", "social_post", "product_card")

    def build(self, product: Dict[str, Any], audience: str = "general",
              objective: str = "sell") -> Dict[str, Any]:
        name = str(product.get("name") or "منتج")
        price = product.get("price")
        description = str(product.get("description") or "").strip()
        price_text = f"السعر: {price} ريال" if price is not None else "السعر حسب العرض"
        hook = f"{name} — عرض واضح وسهل الطلب"
        body = description or f"اكتشف {name} مع معلومات واضحة وسعر معلن."
        cta = "اطلب الآن عبر Merchant OS"
        return {
            "status": "draft",
            "product": product,
            "audience": audience,
            "objective": objective,
            "variants": [
                {"type": "image", "hook": hook, "body": body, "price": price_text, "cta": cta},
                {"type": "short_video", "hook": hook, "script": [hook, body, price_text, cta],
                 "asset_generation": "external_media_provider_required"},
                {"type": "social_post", "hook": hook, "caption": f"{hook}\n{body}\n{price_text}\n{cta}"},
                {"type": "product_card", "title": name, "description": body, "price": price_text, "cta": cta},
            ],
        }


def select_creative_variants(package: Dict[str, Any], allowed: List[str]) -> Dict[str, Any]:
    selected = [v for v in package.get("variants", []) if v.get("type") in set(allowed)]
    return {**package, "selected_variants": selected}
