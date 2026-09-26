import os
import tempfile

from src.merchant_os.agent_runtime import AgentRuntime, AgentDefinition, AgentTask
from src.merchant_os.jev import JEVDecisionEngine
from src.merchant_os.verification import verify_evidence


def test_verification_rejects_placeholder_source_without_real_provenance():
    result = verify_evidence([{
        "source": "candidate_input",
        "data": {"name": "unverified merchant"},
    }])
    assert result["verified"] is False


def test_jev_does_not_treat_evidence_quantity_as_calibrated_confidence():
    engine = JEVDecisionEngine()
    weak = [{"source": "candidate_input", "data": {"claim": "x"}}] * 5
    result = engine.decide("select a merchant", weak, [{"name": "A"}])
    assert result.score["confidence"] < 0.70


def test_jev_does_not_select_first_candidate_when_scores_are_mixed():
    engine = JEVDecisionEngine()
    candidates = [
        {"name": "A", "score": 0.1},
        {"name": "B"},
        {"name": "C", "score": 0.9},
    ]
    result = engine.decide("select a merchant", [], candidates)
    assert result.choice["selected"]["name"] == "C"


def test_runtime_does_not_mutate_handler_output_when_extracting_next_agent():
    runtime = AgentRuntime()
    shared = {"value": 1, "_next_agent": "next"}
    runtime.register(AgentDefinition("x", "x", ("x",), lambda _task: shared))
    result = runtime.run(AgentTask("t1", "x", {}))
    assert result.next_agent == "next"
    assert shared["_next_agent"] == "next"
