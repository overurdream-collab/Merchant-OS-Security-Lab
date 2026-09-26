from typing import Any, Dict
from .agents import run_agent

BUSINESS_AGENTS = ("merchant_scout","merchant_research","outreach","product","sales","order","operations")

class AgentNetwork:
    """Business execution network below Professor OS."""
    def dispatch(self, agent: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if agent not in BUSINESS_AGENTS:
            return {"status":"blocked","reason":"unknown_business_agent","agent":agent}
        if agent == "merchant_scout":
            return {"status":"completed","agent":agent,"candidates":payload.get("candidates",[])}
        if agent == "merchant_research":
            return {"status":"completed","agent":agent,"merchant":payload.get("merchant",{})}
        return {"status":"completed","agent":agent,"result":run_agent(payload.get("text",""), {"agent":agent, **payload})}
