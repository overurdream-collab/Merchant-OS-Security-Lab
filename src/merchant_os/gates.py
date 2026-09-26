from typing import Any, Dict

def confidence_gate(confidence: float, minimum: float = 0.70) -> Dict[str, Any]:
    return {"confidence": confidence, "minimum": minimum, "passed": confidence >= minimum}

def risk_gate(risk_level: str, allowed: tuple[str, ...] = ("low", "medium")) -> Dict[str, Any]:
    return {"risk_level": risk_level, "passed": risk_level in allowed}

def decision_gate(confidence: float, risk_level: str, minimum_confidence: float = 0.70) -> Dict[str, Any]:
    confidence_result = confidence_gate(confidence, minimum_confidence)
    risk_result = risk_gate(risk_level)
    return {"passed": confidence_result["passed"] and risk_result["passed"], "confidence": confidence_result, "risk": risk_result}
