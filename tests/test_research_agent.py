import unittest
from src.merchant_os.research_tools import ResearchResult, StaticResearchProvider
from src.merchant_os.specialists import ResearchAgent
from src.merchant_os.professor_os import Mission, ProfessorOS

class TestResearchAgent(unittest.TestCase):
    def test_provider_results_become_evidence(self):
        provider = StaticResearchProvider([ResearchResult("Merchant A","https://example.com/a","catalog",captured_at="2026-09-19T00:00:00+00:00")])
        out = ResearchAgent(provider=provider).run({"query":"merchant a","limit":5})
        self.assertEqual(out["research"][0]["name"],"Merchant A")
        self.assertEqual(out["evidence"][0]["source"],"https://example.com/a")

    def test_professor_uses_concrete_research_agent(self):
        provider = StaticResearchProvider([ResearchResult("Merchant A","https://example.com/a","catalog")])
        result = ProfessorOS(research_provider=provider).run(Mission("find merchants",{"research_query":"shops","risk_level":"low"}))
        self.assertEqual(result["results"][0]["output"]["research"][0]["name"],"Merchant A")
        self.assertTrue(result["final"]["verification"]["verified"])

if __name__=="__main__":
    unittest.main()
