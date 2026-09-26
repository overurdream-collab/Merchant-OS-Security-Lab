"""Hermes Scout: reusable market-intelligence agent boundary.

This module deliberately does not scrape or call a specific Hermes runtime.
Hermes, Meta, Reddit, a browser provider, or another source can be plugged in
through the small collector contract below.

The scout's responsibility is discovery + normalization. Decisions, outreach,
purchases, and other actions belong to downstream agents and policy gates.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol, Sequence

from .signals import MarketSignal, signal_from_item


class SignalCollector(Protocol):
    def collect(self, query: str, context: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        """Return raw source items for a market-intelligence query."""


@dataclass(frozen=True)
class ScoutRequest:
    query: str
    sources: Sequence[str] = ()
    category: Optional[str] = None
    location: Optional[str] = None
    max_items: int = 50

    def normalized(self) -> "ScoutRequest":
        query = str(self.query or "").strip()
        if not query:
            raise ValueError("query is required")
        return ScoutRequest(
            query=query,
            sources=tuple(str(s).strip().lower() for s in self.sources if str(s).strip()),
            category=(self.category or "").strip() or None,
            location=(self.location or "").strip() or None,
            max_items=max(1, min(int(self.max_items or 50), 500)),
        )


class HermesScoutAgent:
    name = "hermes_scout_agent"
    description = "Discovers and normalizes external market and demand signals."

    def __init__(self, collector: SignalCollector):
        self.collector = collector

    def collect(self, request: ScoutRequest) -> list[MarketSignal]:
        request = request.normalized()
        context = {
            "sources": list(request.sources),
            "category": request.category,
            "location": request.location,
        }

        signals: list[MarketSignal] = []
        seen: set[str] = set()

        for item in self.collector.collect(request.query, context):
            try:
                signal = signal_from_item(
                    {
                        **item,
                        "category": item.get("category") or request.category,
                        "location": item.get("location") or request.location,
                    }
                )
            except (TypeError, ValueError):
                continue

            if signal.signal_id in seen:
                continue
            seen.add(signal.signal_id)
            signals.append(signal)

            if len(signals) >= request.max_items:
                break

        return signals

    def collect_and_store(self, request: ScoutRequest) -> list[Dict[str, Any]]:
        from ..database import ensure_intelligence_schema, save_market_signal

        ensure_intelligence_schema()
        stored = []
        for signal in self.collect(request):
            stored.append(save_market_signal(signal.to_dict()))
        return stored


def run_hermes_scout(
    collector: SignalCollector,
    query: str,
    *,
    sources: Sequence[str] = (),
    category: str | None = None,
    location: str | None = None,
    max_items: int = 50,
    store: bool = True,
) -> list[Dict[str, Any]]:
    """Convenience entry point usable by Merchant OS or another project."""

    agent = HermesScoutAgent(collector)
    request = ScoutRequest(
        query=query,
        sources=sources,
        category=category,
        location=location,
        max_items=max_items,
    )

    if store:
        return agent.collect_and_store(request)

    return [signal.to_dict() for signal in agent.collect(request)]
