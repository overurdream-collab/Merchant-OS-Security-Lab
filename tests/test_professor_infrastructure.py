import unittest
from src.merchant_os.evidence import EvidenceStore
from src.merchant_os.verification import verify_evidence
from src.merchant_os.human_approval import HumanApprovalGate
from src.merchant_os.replay import ReplayEngine
from src.merchant_os.tools import ToolRegistry, Tool

class TestProfessorInfrastructure(unittest.TestCase):
    def test_evidence_and_verification(self):
        store = EvidenceStore()
        item = store.add("e1", "test", {"value": 1})
        self.assertEqual(item.evidence_id, "e1")
        self.assertTrue(verify_evidence([{"source": "test", "value": 1}])["verified"])

    def test_approval(self):
        gate = HumanApprovalGate()
        req = gate.request("m1", "publish_offer", "high")
        self.assertEqual(req["status"], "pending")
        self.assertEqual(gate.approve(req)["status"], "approved")

    def test_replay_hides_future(self):
        trace = [{"event": 1}, {"event": 2}, {"event": 3}]
        out = ReplayEngine().replay(trace, 2)
        self.assertEqual(len(out["visible_events"]), 2)
        self.assertEqual(out["future_events_hidden"], 1)

    def test_tools(self):
        tools = ToolRegistry()
        tools.register(Tool("echo", "echo", lambda p: p["x"]))
        self.assertEqual(tools.call("echo", {"x": 4}), 4)

if __name__ == "__main__":
    unittest.main()
