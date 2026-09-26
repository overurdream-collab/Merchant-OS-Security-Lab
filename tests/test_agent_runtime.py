import os
import tempfile
import unittest

from src.merchant_os import database
from src.merchant_os.agent_runtime import AgentTask, AgentRuntime, AgentDefinition
from src.merchant_os.professor_os import Mission, ProfessorOS, SPECIALISTS
from src.merchant_os.action_engine import ActionEngine


class TestProfessorOS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "db.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def test_runtime_registry(self):
        runtime = AgentRuntime()
        runtime.register(AgentDefinition("echo", "test", ("echo",), lambda t: {"value": t.input["value"]}))
        result = runtime.run(AgentTask("task-1", "echo", {"value": 7}))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output["value"], 7)

    def test_full_ten_specialist_sequence(self):
        result = ProfessorOS().run(Mission(
            goal="evaluate merchant opportunity",
            subject={"candidates": [{"name": "merchant-a"}], "risk_level": "low"},
            constraints={"minimum_confidence": 0.70},
        ))
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["specialists"], list(SPECIALISTS))
        self.assertEqual(len(result["results"]), 10)
        self.assertEqual([x["agent"] for x in result["results"]], list(SPECIALISTS))

    def test_supervisor_veto_blocks_decision(self):
        result = ProfessorOS().run(Mission(
            goal="high risk action",
            subject={"candidates": [{"name": "merchant-a"}], "risk_level": "low", "supervisor_veto": True},
        ))
        self.assertEqual(result["status"], "veto")
        self.assertTrue(result["final"]["veto"])
        self.assertNotIn("jev", result["final"])

    def test_action_engine_requires_approval(self):
        engine = ActionEngine()
        engine.register("test_action", lambda p: {"ok": p["x"]})
        blocked = engine.execute("test_action", {"x": 1})
        self.assertEqual(blocked["status"], "blocked")
        forged = engine.execute("test_action", {"x": 1}, approved=True)
        self.assertEqual(forged["status"], "blocked")
        engine = ActionEngine(approval_verifier=lambda action, payload, record: record == "verified-approval")
        engine.register("test_action", lambda p: {"ok": p["x"]})
        executed = engine.execute("test_action", {"x": 1}, approval_record="verified-approval")
        self.assertEqual(executed["status"], "executed")


if __name__ == "__main__":
    unittest.main()
