from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Dict, Iterable, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: Any) -> str:
    return sha256(repr(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgeItem:
    source: str
    title: str
    content: str
    captured_at: str = field(default_factory=_now)
    url: str | None = None
    reliability: float = 0.5
    tags: tuple[str, ...] = ()
    fingerprint: str = ""

    def __post_init__(self):
        if not self.fingerprint:
            # Identity is the evidence itself, not the provider name. The same
            # item seen through two sources must be deduplicated while retaining
            # the first source as provenance.
            normalized_url = str(self.url or "").strip().lower().rstrip("/")
            identity = ("url", normalized_url) if normalized_url else (
                "content", self.title.strip().casefold(), self.content.strip().casefold()
            )
            object.__setattr__(self, "fingerprint", _fingerprint(identity))


@dataclass(frozen=True)
class KnowledgeSnapshot:
    query: str
    created_at: str
    items: tuple[KnowledgeItem, ...]
    sources: tuple[str, ...]


class KnowledgeSourceRegistry:
    """Extensible, evidence-first knowledge ingestion layer.

    Providers are adapters. Adding a source never requires changing agent logic.
    The registry deduplicates content, preserves provenance and records reliability.
    """

    def __init__(self):
        self._providers: Dict[str, Callable[..., Iterable[Any]]] = {}
        self._reliability: Dict[str, float] = {}

    def register(self, name: str, provider: Callable[..., Iterable[Any]], reliability: float = 0.5):
        if not name or not callable(provider):
            raise ValueError("source name and callable provider are required")
        self._providers[name] = provider
        self._reliability[name] = max(0.0, min(1.0, float(reliability)))

    def list_sources(self) -> List[str]:
        return sorted(self._providers)

    def collect(self, query: str, sources: Optional[Iterable[str]] = None) -> KnowledgeSnapshot:
        names = list(sources) if sources is not None else self.list_sources()
        items: List[KnowledgeItem] = []
        seen = set()
        for name in names:
            provider = self._providers.get(name)
            if provider is None:
                continue
            try:
                raw_items = provider(query) or []
            except Exception:
                continue
            for raw in raw_items:
                if isinstance(raw, KnowledgeItem):
                    item = raw
                elif isinstance(raw, dict):
                    item = KnowledgeItem(
                        source=name,
                        title=str(raw.get("title") or raw.get("name") or ""),
                        content=str(raw.get("content") or raw.get("snippet") or ""),
                        url=raw.get("url"),
                        reliability=float(raw.get("reliability", self._reliability.get(name, 0.5))),
                        tags=tuple(raw.get("tags") or ()),
                        captured_at=str(raw.get("captured_at") or _now()),
                    )
                else:
                    item = KnowledgeItem(
                        source=name, title="", content=str(raw),
                        reliability=self._reliability.get(name, 0.5)
                    )
                if item.fingerprint in seen or not item.content.strip():
                    continue
                seen.add(item.fingerprint)
                items.append(item)
        return KnowledgeSnapshot(query=query, created_at=_now(), items=tuple(items), sources=tuple(names))


class KnowledgeLearningLoop:
    """Builds a daily/continuous learning snapshot without changing production code.

    Learning means acquiring validated evidence and evaluation cases. Promotion of
    code, schemas or policies remains a separate approval-gated operation.
    """

    def __init__(self, registry: KnowledgeSourceRegistry):
        self.registry = registry
        self.history: List[KnowledgeSnapshot] = []

    def refresh(self, query: str, sources: Optional[Iterable[str]] = None) -> KnowledgeSnapshot:
        snapshot = self.registry.collect(query, sources)
        self.history.append(snapshot)
        return snapshot

    def changed_fingerprints(self, current: KnowledgeSnapshot) -> List[str]:
        previous = set()
        if len(self.history) >= 2:
            previous = {x.fingerprint for x in self.history[-2].items}
        return [x.fingerprint for x in current.items if x.fingerprint not in previous]
