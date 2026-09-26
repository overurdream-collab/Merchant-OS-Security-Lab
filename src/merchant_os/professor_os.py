from dataclasses import dataclass
from typing import Any, Dict
from .agent_runtime import AgentDefinition, AgentRuntime, ensure_runtime_schema, remember
from .jev import JEVDecisionEngine
from .gates import decision_gate
from .verification import verify_evidence
from .evidence import EvidenceStore
from .human_approval import HumanApprovalGate
from .agent_network import AgentNetwork
from .specialists import build_specialist_agents
from .research_tools import ResearchProvider
from .merchants import persist_ranked_merchants
from .commerce_agent import CommerceControlPlane
from .commerce_service import CommerceService

SPECIALISTS = ("research","intelligence","data","market","customer","sales","strategy","verification","execution","supervisor")

@dataclass(frozen=True)
class Mission:
    goal: str
    subject: Dict[str, Any]
    constraints: Dict[str, Any] | None = None

def build_professor_os_runtime() -> AgentRuntime:
    runtime = AgentRuntime()
    for name in SPECIALISTS:
        runtime.register(AgentDefinition(name, f"Professor OS specialist: {name}",
            (f"professor.{name}",), lambda task, n=name: {"specialist": n, "status": "completed"}))
    ensure_runtime_schema()
    return runtime

class ProfessorOS:
    """Professor OS v1.0: orchestrator + 10 specialists + JEV + gates."""
    def __init__(self, runtime: AgentRuntime | None = None, research_provider: ResearchProvider | None = None,
                 commerce_service: CommerceService | None = None,
                 commerce_control_plane: CommerceControlPlane | None = None):
        self.runtime = runtime or build_professor_os_runtime()
        self.jev = JEVDecisionEngine()
        self.evidence_store = EvidenceStore()
        self.approval_gate = HumanApprovalGate()
        self.agent_network = AgentNetwork()
        self.specialists = build_specialist_agents(
            self.agent_network,
            research_provider=research_provider,
            commerce_service=commerce_service,
            commerce_control_plane=commerce_control_plane,
        )
        self._bind_concrete_specialists()

    def _bind_concrete_specialists(self):
        for name, specialist in self.specialists.items():
            self.runtime.register(AgentDefinition(
                name, f"Professor OS specialist: {name}", (f"professor.{name}",),
                lambda task, agent=specialist: agent.run(task.input)))

    def run(self, mission: Mission) -> Dict[str, Any]:
        current = {"goal": mission.goal, "subject": mission.subject,
                   "constraints": mission.constraints or {}, "evidence": [],
                   "findings": [], "veto": False,
                   "customers": list(mission.subject.get("customers", []) or []),
                   "business_events": list(mission.subject.get("business_events", []) or []),
                   "candidates": list(mission.subject.get("candidates", []) or [])}
        if mission.subject.get("research_query"): current["query"] = mission.subject["research_query"]
        if mission.subject.get("limit"): current["limit"] = mission.subject["limit"]
        results, parent = [], None
        for name in SPECIALISTS:
            task = self.runtime.create_task(f"professor.{name}", current, {"mission": mission.goal}, parent)
            result = self.runtime.run(task)
            results.append(result)
            if result.status != "completed":
                return self._response(mission, current, results, "failed")
            current.update(result.output)
            parent = result.task_id

        if current.get("veto") or current.get("supervisor", {}).get("veto"):
            current["veto"] = True
            remember("mission", mission.goal, "last_status", "veto")
            return self._response(mission, current, results, "veto")

        current["verification"] = verify_evidence(current.get("evidence", []))
        if not current["verification"]["verified"]:
            return self._response(mission, current, results, "needs_review")

        ranked = current.get("merchant_scores", [])
        if ranked:
            current["ranked_merchants"] = ranked
            current["persisted_merchant_ids"] = persist_ranked_merchants(ranked)
            candidates = ranked
        else:
            candidates = current.get("research", []) or mission.subject.get("candidates", [])
        jev = self.jev.decide(mission.goal, current.get("evidence", []), candidates)
        current["jev"] = {"noul": jev.noul, "choice": jev.choice, "score": jev.score}
        minimum = float((mission.constraints or {}).get("minimum_confidence", 0.70))
        current["gates"] = decision_gate(float(jev.score.get("confidence", 0.0)),
                                         mission.subject.get("risk_level", "medium"), minimum)
        status = "ready_for_action" if current["gates"]["passed"] else "needs_review"
        remember("mission", mission.goal, "last_status", status)
        return self._response(mission, current, results, status)

    @staticmethod
    def _response(mission, current, results, status):
        return {"mission": mission, "status": status, "specialists": list(SPECIALISTS),
                "results": [{"task_id": r.task_id, "agent": r.agent, "status": r.status,
                             "output": r.output, "error": r.error} for r in results],
                "final": current}
