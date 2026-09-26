import unittest
from src.merchant_os.agent_training import AgentCompetencySuite
from src.merchant_os.knowledge_learning import KnowledgeSourceRegistry


class TestCriticalAgents(unittest.TestCase):
    def test_data_intelligence_competency_suite(self):
        result = AgentCompetencySuite().evaluate_data_intelligence()
        self.assertTrue(result.passed, result)

    def test_strategic_developer_competency_suite(self):
        result = AgentCompetencySuite().evaluate_strategist()
        self.assertTrue(result.passed, result)

    def test_knowledge_sources_are_extensible(self):
        registry = KnowledgeSourceRegistry()
        registry.register("source_a", lambda q: [{"title": "Pricing", "content": q}])
        snapshot = registry.collect("pricing")
        self.assertEqual(snapshot.sources, ("source_a",))
        self.assertEqual(len(snapshot.items), 1)
        self.assertEqual(snapshot.items[0].content, "pricing")

        registry.register("source_b", lambda q: [{"title": "Pricing", "content": q}])
        snapshot = registry.collect("pricing")
        self.assertEqual(len(snapshot.items), 1)
        self.assertEqual(snapshot.items[0].source, "source_a")


if __name__ == "__main__":
    unittest.main()
