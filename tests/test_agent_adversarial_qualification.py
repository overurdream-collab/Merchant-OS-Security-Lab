from src.merchant_os.agent_runtime import AgentRuntime, AgentDefinition, AgentTask
from src.merchant_os.verification import verify_evidence


def test_verification_rejects_placeholder_source_without_real_provenance():
    result = verify_evidence([{
        "source": "candidate_input",
        "data": {"name": "unverified merchant"},
    }])
    assert result["verified"] is False


def test_runtime_does_not_mutate_handler_output_when_extracting_next_agent():
    runtime = AgentRuntime()
    shared = {"value": 1, "_next_agent": "next"}
    runtime.register(AgentDefinition("x", "x", ("x",), lambda _task: shared))
    result = runtime.run(AgentTask("t1", "x", {}))
    assert result.next_agent == "next"
    assert shared["_next_agent"] == "next"
