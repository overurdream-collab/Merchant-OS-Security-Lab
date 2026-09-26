from typing import Any, Dict, List

def verify_evidence(evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    checked = []
    for item in evidence:
        checked.append({**item, "verified": bool(item.get("source"))})
    return {"verified": bool(checked) and all(x["verified"] for x in checked), "items": checked}
