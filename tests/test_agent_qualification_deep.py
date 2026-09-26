import json
from pathlib import Path

import pytest

from src.merchant_os.agent_runtime import AgentDefinition, AgentRuntime, AgentTask
from src.merchant_os.commerce_agent import (
    ApprovalDecision,
    ApprovalDenied,
    CommerceControlPlane,
    Proposal,
)
from src.merchant_os.database import get_connection
from src.merchant_os.professor_os import Mission, ProfessorOS


class _TrustedApproval:
    def verify(self, proposal, decision, approver_context, approval_evidence):
        return approval_evidence == "trusted"


def _control_plane():
    root = Path(".")
    plane = CommerceControlPlane(
        root,
        actions={"test_action": ("commerce/test",)},
        approval_authority=_TrustedApproval(),
    )
    calls = []

    def handler(proposal):
        calls.append(dict(proposal.parameters))
        return {"ok": True}

    plane.register_action("test_action", handler)
    return plane, calls


def test_runtime_records_failed_handler_without_losing_parent_context():
    runtime = AgentRuntime()

    def broken(task):
        raise RuntimeError("provider exploded")

    runtime.register(AgentDefinition("broken", "broken", ("broken",), broken))
    task = AgentTask("qualification-failure", "broken", {"x": 1}, {"mission": "m1"}, "parent-1")
    result = runtime.run(task)

    assert result.status == "failed"
    assert result.error == "provider exploded"

    with get_connection() as db:
        row = db.execute(
            "SELECT parent_task_id, status, error FROM agent_runs WHERE task_id=?",
            (task.task_id,),
        ).fetchone()

    assert row["parent_task_id"] == "parent-1"
    assert row["status"] == "failed"
    assert row["error"] == "provider exploded"


def test_professor_pipeline_preserves_ten_specialist_chain():
    mission = Mission(
        goal="qualify candidate chain",
        subject={
            "candidates": [{
                "name": "Qualified Merchant",
                "url": "https://example.com/merchant",
                "source_url": "https://example.com/merchant",
                "source_type": "official",
                "city": "Sanaa",
            }],
            "max_enrichment": 0,
        },
        constraints={"minimum_confidence": 0.70},
    )

    result = ProfessorOS().run(mission)

    assert result["status"] in {"needs_review", "ready_for_action"}
    assert [item["agent"] for item in result["results"]] == [
        "research", "intelligence", "data", "market", "customer",
        "sales", "strategy", "verification", "execution", "supervisor",
    ]
    task_ids = [item["task_id"] for item in result["results"]]

    with get_connection() as db:
        rows = db.execute(
            "SELECT task_id, parent_task_id FROM agent_runs WHERE task_id IN ({})".format(
                ",".join("?" for _ in task_ids)
            ),
            task_ids,
        ).fetchall()

    parents = {row["task_id"]: row["parent_task_id"] for row in rows}
    assert parents[task_ids[0]] is None
    for previous, current in zip(task_ids, task_ids[1:]):
        assert parents[current] == previous


def test_approved_proposal_cannot_be_mutated_after_approval():
    plane, calls = _control_plane()
    proposal = Proposal(
        task_id="mutation-test",
        action="test_action",
        scope=("commerce/test",),
        summary="approved test action",
        parameters={"value": 1},
    )
    approval = plane.decide(
        proposal,
        ApprovalDecision.APPROVED,
        {"approver": "test-user"},
        approval_evidence="trusted",
    )

    proposal.parameters["value"] = 999

    with pytest.raises(ApprovalDenied):
        plane.execute(proposal, approval.approval_id)
    assert calls == []


def test_approved_proposal_is_single_use():
    plane, calls = _control_plane()
    proposal = Proposal(
        task_id="replay-test",
        action="test_action",
        scope=("commerce/test",),
        summary="single use",
        parameters={"value": 1},
    )
    approval = plane.decide(
        proposal,
        ApprovalDecision.APPROVED,
        {"approver": "test-user"},
        approval_evidence="trusted",
    )

    assert plane.execute(proposal, approval.approval_id) == {"ok": True}
    with pytest.raises(ApprovalDenied):
        plane.execute(proposal, approval.approval_id)
    assert calls == [{"value": 1}]


def test_scope_escalation_cannot_reuse_approval():
    plane, calls = _control_plane()
    approved = Proposal(
        task_id="scope-test",
        action="test_action",
        scope=("commerce/test",),
        summary="approved scope",
        parameters={"value": 1},
    )
    approval = plane.decide(
        approved,
        ApprovalDecision.APPROVED,
        {"approver": "test-user"},
        approval_evidence="trusted",
    )

    escalated = Proposal(
        task_id=approved.task_id,
        action=approved.action,
        scope=("commerce/test/private",),
        summary=approved.summary,
        parameters=approved.parameters,
        proposal_id=approved.proposal_id,
    )

    with pytest.raises(ApprovalDenied):
        plane.execute(escalated, approval.approval_id)
    assert calls == []
