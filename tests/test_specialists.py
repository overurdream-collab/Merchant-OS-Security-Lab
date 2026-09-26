import unittest
from src.merchant_os.specialists import build_specialist_agents
from src.merchant_os.agent_network import AgentNetwork

class TestConcreteSpecialists(unittest.TestCase):
    def test_all_ten_exist(self):
        agents=build_specialist_agents(AgentNetwork())
        self.assertEqual(len(agents),10)
        self.assertEqual(set(agents),{"research","intelligence","data","market","customer","sales","strategy","verification","execution","supervisor"})
    def test_execution_requires_approval(self):
        agent=build_specialist_agents(AgentNetwork())["execution"]
        self.assertEqual(agent.run({"approved":False})["status"],"blocked")
if __name__=="__main__": unittest.main()
