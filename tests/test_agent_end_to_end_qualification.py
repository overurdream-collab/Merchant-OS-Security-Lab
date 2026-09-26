import pytest

from src.merchant_os import database
from src.merchant_os.commerce_agent import (
    ApprovalDecision,
    CommerceControlPlane,
    Proposal,
)
from src.merchant_os.professor_os import Mission, ProfessorOS
from src.merchant_os.specialists import ExecutionAgent


class ApprovedAuthority:
    def verify(self, proposal, decision, approver_context, approval_evidence):
        return (
            decision is ApprovalDecision.APPROVED
            and approver_context.get("approver") == "test-human"
            and approval_evidence == "confirmed"
        )


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "e2e.sqlite"))
    database.ensure_schema()
    return database


def test_end_to_end_approval_execution_and_execution_agent_cannot_bypass_control_plane(
    isolated_db, tmp_path
):
    executed = []

    class Service:
        def checkout(self, **parameters):
            executed.append(parameters)
            return {"order_id": 42}

    control = CommerceControlPlane(
        tmp_path,
        actions={"checkout": ("commerce/orders",)},
        approval_authority=ApprovedAuthority(),
    )
    service = Service()
    control.register_action("checkout", service.checkout)

    proposal = Proposal(
        task_id="mission-1",
        action="checkout",
        scope=("commerce/orders",),
        summary="Create approved order",
        parameters={"customer_id": 7},
    )

    approval = control.decide(
        proposal,
        ApprovalDecision.APPROVED,
        {"approver": "test-human"},
        approval_evidence="confirmed",
    )

    agent = ExecutionAgent(
        commerce_service=service,
        commerce_control_plane=control,
    )

    blocked = agent.run({
        "commerce_action": True,
        "proposal": proposal,
    })
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "approval_id_required"
    assert executed == []

    result = agent.run({
        "commerce_action": True,
        "proposal": proposal,
        "approval_id": approval.approval_id,
    })
    assert result["status"] == "executed"
    assert executed == [{"customer_id": 7}]

    replay = agent.run({
        "commerce_action": True,
        "proposal": proposal,
        "approval_id": approval.approval_id,
    })
    assert replay["status"] == "blocked"
    assert "approval_already_consumed" in replay["detail"]
    assert len(executed) == 1


def test_supervisor_veto_prevents_ready_for_action(isolated_db):
    professor = ProfessorOS()
    result = professor.run(Mission(
        goal="supervisor veto qualification",
        subject={
            "supervisor_veto": True,
            "candidates": [{
                "name": "Merchant",
                "url": "https://example.com/merchant",
                "source_url": "https://example.com/merchant",
                "source_type": "official",
                "city": "Sanaa",
            }],
            "max_enrichment": 0,
        },
    ))

    assert result["status"] == "veto"
    assert result["final"]["veto"] is True


def test_unverified_candidate_evidence_stops_before_ready_for_action(isolated_db):
    professor = ProfessorOS()
    result = professor.run(Mission(
        goal="verification boundary qualification",
        subject={
            "candidates": [{
                "name": "Unverified merchant",
            }],
            "max_enrichment": 0,
        },
    ))

    assert result["status"] == "needs_review"
    assert result["final"]["verification"]["verified"] is False
    assert result["final"].get("gates") is None
