from typing import Any, Dict, List

class ReplayEngine:
    """Replays only the evidence available at the recorded decision point."""
    def replay(self, trace: List[Dict[str, Any]], at_index: int | None = None) -> Dict[str, Any]:
        limit = len(trace) if at_index is None else max(0, min(at_index, len(trace)))
        visible = trace[:limit]
        return {"visible_events": visible, "future_events_hidden": len(trace) - limit}
