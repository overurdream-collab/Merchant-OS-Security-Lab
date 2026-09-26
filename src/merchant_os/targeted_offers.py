from __future__ import annotations

from typing import Any, Dict, Iterable


class TargetedOfferEngine:
    """Selects relevant products and creative variants from observable customer intent."""

    def __init__(self, interest_engine, creative_engine):
        self.interest_engine = interest_engine
        self.creative_engine = creative_engine

    def recommend(self, customer_id: int, products: Iterable[Dict[str, Any]], limit: int = 5):
        profile = self.interest_engine.profile(customer_id)
        category_scores = profile["category_scores"]
        product_scores = profile["product_scores"]

        ranked = []
        for product in products:
            product_id = product.get("product_id")
            category = product.get("category")
            score = product_scores.get(product_id, 0) * 3 + category_scores.get(category, 0)
            if score > 0:
                ranked.append((score, product))

        ranked.sort(key=lambda x: (-x[0], str(x[1].get("product_id", ""))))
        return [self._offer(p, profile, score) for score, p in ranked[:limit]]

    def _offer(self, product, profile, score):
        readiness = profile["purchase_readiness"]
        objective = "close" if readiness in {"high", "very_high"} else "engage"
        creative = self.creative_engine.build(
            product,
            audience=profile["top_categories"][0] if profile["top_categories"] else "general",
            objective=objective,
        )
        return {
            "product_id": product.get("product_id"),
            "category": product.get("category"),
            "relevance_score": score,
            "purchase_readiness": readiness,
            "objective": objective,
            "creative": creative,
        }
