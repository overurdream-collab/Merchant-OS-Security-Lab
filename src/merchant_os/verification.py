from typing import Any, Dict, List

_PLACEHOLDER_SOURCES = {"candidate_input", "conversation", "unknown", "unverified"}

def verify_evidence(evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    checked = []
    for item in evidence:
        source = item.get("source")
        has_provenance = bool(source) and str(source).strip().lower() not in _PLACEHOLDER_SOURCES
        checked.append({**item, "verified": has_provenance})
    return {"verified": bool(checked) and all(x["verified"] for x in checked), "items": checked}
