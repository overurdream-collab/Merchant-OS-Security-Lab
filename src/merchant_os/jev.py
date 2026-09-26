from dataclasses import dataclass
from typing import Any, Dict, List

@dataclass(frozen=True)
class JEVResult:
    noul: Dict[str, Any]
    choice: Dict[str, Any]
    score: Dict[str, Any]

class JEVDecisionEngine:
    """Decision engine: Noul -> Choice -> Score. Never executes actions."""
    def decide(self, question: str, evidence: List[Dict[str, Any]], candidates: List[Dict[str, Any]] | None = None) -> JEVResult:
        candidates = candidates or []
        noul = {"question": question, "evidence_count": len(evidence)}
        selected = max(candidates, key=lambda c: float(c.get("score", 0))) if candidates and all(isinstance(c, dict) and "score" in c for c in candidates) else (candidates[0] if candidates else None)
        choice = {"candidates": candidates, "selected": selected}
        selected = choice["selected"]
        score = {
            "selected": selected,
            "confidence": 0.0 if not selected else min(1.0, len(evidence) / 5.0),
            "factors": [{"name": "evidence", "value": len(evidence)}],
        }
        return JEVResult(noul=noul, choice=choice, score=score)
