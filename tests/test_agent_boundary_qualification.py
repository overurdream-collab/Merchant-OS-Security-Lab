import pytest

from src.merchant_os.agents import run_agent
from src.merchant_os.commerce_agent import ApprovalDecision, ApprovalDenied, CommerceControlPlane, Proposal
from src.merchant_os.gates import decision_gate
from src.merchant_os.jev import JEVDecisionEngine
from src.merchant_os.router import detect_intent


def test_jev_contradictory_evidence_is_explicitly_characterized():
    engine = JEVDecisionEngine()
    evidence = [
        {"source": "official-a", "claim": "stock=10"},
        {"source": "official-b", "claim": "stock=0"},
    ]
    result = engine.decide("is stock available?", evidence, [{"name": "item", "score": 0.9}])

    assert result.score["confidence"] == 0.4
    assert result.noul["evidence_count"] == 2
    assert result.choice["selected"]["name"] == "item"


def test_jev_evidence_count_does_not_prove_source_quality():
    engine = JEVDecisionEngine()
    weak = engine.decide(
        "question",
        [{"source": "unverified-a"}, {"source": "unverified-b"}, {"source": "unverified-c"}],
        [{"name": "candidate", "score": 0.8}],
    )
    strong = engine.decide(
        "question",
        [{"source": "official-a"}, {"source": "official-b"}, {"source": "official-c"}],
        [{"name": "candidate", "score": 0.8}],
    )

    assert weak.score["confidence"] == strong.score["confidence"] == 0.6


def test_arabic_multi_intent_router_uses_documented_primary_precedence():
    assert detect_intent("أريد السعر وأين طلبي؟") == "order_status"
    assert detect_intent("أريد السعر وفي عندي شكوى") == "complaint"


def test_customer_agent_preserves_primary_routing_contract():
    result = run_agent("أريد السعر وأين طلبي؟")
    assert result["intent"] == "order_status"
    assert result["agent"] == "order_agent"


class _Authority:
    def verify(self, proposal, decision, approver_context, approval_evidence):
        return approval_evidence == "trusted"


def test_execution_boundary_requires_matching_persisted_approval(tmp_path):
    plane = CommerceControlPlane(
        tmp_path,
        actions={"test_action": ("commerce/test",)},
        approval_authority=_Authority(),
    )
    calls = []
    plane.register_action("test_action", lambda proposal: calls.append(proposal.task_id) or {"ok": True})

    proposal = Proposal(
        task_id="boundary-test",
        action="test_action",
        scope=("commerce/test",),
        summary="boundary",
        parameters={"value": 1},
    )

    with pytest.raises(ApprovalDenied):
        plane.execute(proposal, "not-an-approval")

    approval = plane.decide(
        proposal,
        ApprovalDecision.APPROVED,
        {"approver": "qa"},
        approval_evidence="trusted",
    )
    assert plane.execute(proposal, approval.approval_id) == {"ok": True}
    assert calls == ["boundary-test"]


def test_decision_gate_blocks_high_risk_even_with_high_confidence():
    result = decision_gate(1.0, "high", minimum_confidence=0.7)
    assert result["confidence"]["passed"] is True
    assert result["risk"]["passed"] is False
    assert result["passed"] is False
