from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source: str
    captured_at: str
    data: Dict[str, Any]

class EvidenceStore:
    def __init__(self):
        self._items: List[Evidence] = []
    def add(self, evidence_id: str, source: str, data: Dict[str, Any]):
        item = Evidence(evidence_id, source, datetime.now(timezone.utc).isoformat(), data)
        self._items.append(item)
        return item
    def snapshot(self):
        return list(self._items)
