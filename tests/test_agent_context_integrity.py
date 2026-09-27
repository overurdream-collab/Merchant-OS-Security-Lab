from src.merchant_os.agent_runtime import AgentDefinition, AgentRuntime, AgentTask


def test_runtime_deep_isolates_nested_task_input_from_handler_mutation():
    runtime = AgentRuntime()
    task = AgentTask(
        task_id="context-isolation",
        task_type="mutator",
        input={
            "evidence": [{"source": "trusted", "data": {"value": 1}}],
            "nested": {"items": ["original"]},
        },
    )

    def malicious_handler(received):
        received.input["evidence"][0]["data"]["value"] = 999
        received.input["nested"]["items"].append("injected")
        received.input["new_key"] = "handler-only"
        return {"ok": True}

    runtime.register(
        AgentDefinition(
            "mutator",
            "context isolation qualification",
            ("mutator",),
            malicious_handler,
        )
    )

    result = runtime.run(task)

    assert result.status == "completed"
    assert task.input["evidence"][0]["data"]["value"] == 1
    assert task.input["nested"]["items"] == ["original"]
    assert "new_key" not in task.input
