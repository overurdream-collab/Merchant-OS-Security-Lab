from typing import Any, Dict

class HumanApprovalGate:
    def request(self, mission_id: str, action: str, risk_level: str) -> Dict[str, Any]:
        return {"mission_id": mission_id, "action": action, "risk_level": risk_level, "status": "pending"}
    def approve(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {**request, "status": "approved"}
    def reject(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {**request, "status": "rejected"}
