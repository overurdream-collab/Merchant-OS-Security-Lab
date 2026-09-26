import unittest
from src.merchant_os.specialists import build_specialist_agents
from src.merchant_os.agent_network import AgentNetwork

class TestRealSpecialistLogic(unittest.TestCase):
    def test_research_extracts_candidates(self):
        a=build_specialist_agents(AgentNetwork())["research"]
        out=a.run({"candidates":[{"name":"A","channel":"facebook","city":"Sana'a"}]})
        self.assertEqual(out["research"][0]["name"],"A")
        self.assertTrue(out["evidence"])
    def test_sales_uses_research_signals(self):
        a=build_specialist_agents(AgentNetwork())["sales"]
        out=a.run({"research":[{"name":"A","channel":"whatsapp"}]})
        self.assertEqual(out["sales_signals"][0]["merchant"],"A")
    def test_execution_gate(self):
        a=build_specialist_agents(AgentNetwork())["execution"]
        self.assertEqual(a.run({"approved":False})["status"],"blocked")
if __name__=="__main__": unittest.main()
