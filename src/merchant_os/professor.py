from typing import Any, Dict

from .professor_os import Mission, ProfessorOS, build_professor_os_runtime


def build_runtime():
    """Compatibility entry point for the new Professor OS runtime."""
    return build_professor_os_runtime()


def professor_plan(goal: str):
    return [
        "research", "intelligence", "data", "market", "customer",
        "sales", "strategy", "verification", "execution", "supervisor",
    ]


def run_professor(
    goal: str,
    payload: Dict[str, Any],
    *,
    commerce_service=None,
    commerce_control_plane=None,
) -> Dict[str, Any]:
    mission = Mission(goal=goal, subject=dict(payload), constraints=payload.get("constraints", {}))
    return ProfessorOS(
        commerce_service=commerce_service,
        commerce_control_plane=commerce_control_plane,
    ).run(mission)
