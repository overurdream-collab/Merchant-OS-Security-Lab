import json
import os
import tempfile
import unittest
from contextlib import closing

from src.merchant_os import database
from src.merchant_os.agent_runtime import recall
from src.merchant_os.commerce_agent import (
    ApprovalDecision,
    ApprovalDenied,
    CommerceControlPlane,
    Evidence,
    EvidenceState,
    ProjectMemory,
    Proposal,
    RecordKind,
    ScopeViolation,
)


class TestCommerceAgentControlPlane(unittest.TestCase):
    class ApprovalAuthority:
        def verify(self, proposal, decision, approver_context, approval_evidence):
            return approval_evidence == "valid-human-confirmation"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp.name, "agent.sqlite3")
        self.memory_root = os.path.join(self.temp.name, "project")
        context = os.path.join(self.memory_root, "docs", "agent-context")
        os.makedirs(context)
        with open(os.path.join(context, "ROADMAP.md"), "w", encoding="utf-8") as stream:
            stream.write("| Phase 2E | Cart service | IN PROGRESS |\n| Phase 2F | Checkout | PLANNED |\n")
        with open(os.path.join(context, "PROJECT_STATE.md"), "w", encoding="utf-8") as stream:
            stream.write("A verified local state.\n")
        self.control = CommerceControlPlane(
            self.memory_root,
            actions={"update_memory": ("docs/agent-context", "agent-memory/")},
            approval_authority=self.ApprovalAuthority(),
        )
        self.executed = []
        self.control.register_action("update_memory", lambda proposal: self.executed.append(proposal.proposal_id) or {"ok": True})

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def proposal(self, **overrides):
        values = {
            "task_id": "task-1", "action": "update_memory",
            "scope": ("docs/agent-context/PROJECT_STATE.md",),
            "summary": "Record the verified task result.", "parameters": {"result": "passed"},
        }
        values.update(overrides)
        return Proposal(**values)

    def test_project_memory_reads_context_and_current_phase(self):
        memory = ProjectMemory(self.memory_root)
        self.assertIn("ROADMAP.md", memory.load())
        self.assertEqual(memory.current_phase(), "Phase 2E")
        self.assertEqual(memory.next_phase(), "Phase 2F")

    def test_evidence_classification_keeps_claims_unverified_until_evidence(self):
        unverified = Evidence("tests pass", EvidenceState.UNVERIFIED, "conversation", "today", "")
        verified = Evidence("tests pass", EvidenceState.VERIFIED, "pytest output", "today", "2 passed")
        self.assertEqual(unverified.kind, RecordKind.UNVERIFIED_CLAIM)
        self.assertEqual(verified.kind, RecordKind.VERIFIED_EVIDENCE)
        with self.assertRaisesRegex(ValueError, "verified_evidence"):
            Evidence("claim", EvidenceState.VERIFIED, "source", "today", "")

    def test_provider_contract_accepts_only_a_scoped_proposal(self):
        expected = self.proposal()

        class Provider:
            def propose(self, task, project_memory):
                self.asserted = task["id"]
                assert "PROJECT_STATE.md" in project_memory
                return expected

        proposal = self.control.request_proposal(Provider(), {"id": "task-1"})
        self.assertEqual(proposal.task_id, "task-1")

        class BadProvider:
            def propose(self, task, project_memory):
                return {"action": "execute"}

        with self.assertRaisesRegex(TypeError, "must_return_proposal"):
            self.control.request_proposal(BadProvider(), {})

    def test_scope_and_path_traversal_are_rejected(self):
        with self.assertRaises(ScopeViolation):
            self.control.validate_proposal(self.proposal(scope=("src/merchant_os/database.py",)))
        with self.assertRaises(ScopeViolation):
            self.control.validate_proposal(self.proposal(scope=("docs/agent-context/../../src",)))

    def test_action_requires_matching_persisted_approval_not_boolean(self):
        proposal = self.proposal()
        with self.assertRaises(ApprovalDenied):
            self.control.execute(proposal, "approved=True")
        with self.assertRaises(ApprovalDenied):
            self.control.execute(proposal, self.control.decide(
                proposal, ApprovalDecision.REJECTED,
                {"approver": "project owner", "channel": "owner review"},
                approval_evidence="valid-human-confirmation",
            ).approval_id)

        approval = self.control.decide(
            proposal, ApprovalDecision.APPROVED,
            {"approver": "project owner", "channel": "explicit task instruction"},
            approval_evidence="valid-human-confirmation",
        )
        self.assertEqual(self.control.execute(proposal, approval.approval_id), {"ok": True})
        self.assertEqual(self.executed, [proposal.proposal_id])
        with self.assertRaisesRegex(ApprovalDenied, "already_consumed"):
            self.control.execute(proposal, approval.approval_id)

    def test_approval_audit_contains_proposal_scope_decision_and_result(self):
        proposal = self.proposal()
        approval = self.control.decide(
            proposal, ApprovalDecision.APPROVED, {"approver": "human"},
            approval_evidence="valid-human-confirmation",
        )
        self.control.execute(proposal, approval.approval_id)
        with closing(database.get_connection()) as db:
            rows = db.execute("SELECT task_type, status, input, output FROM agent_runs ORDER BY run_id").fetchall()
        self.assertEqual([row["task_type"] for row in rows], ["commerce_approval", "commerce_action"])
        self.assertEqual(rows[0]["status"], "APPROVED")
        approval_data = json.loads(rows[0]["output"])
        self.assertEqual(approval_data["scope"], list(proposal.scope))
        self.assertIn("timestamp", approval_data)
        self.assertEqual(approval_data["evidence_result"]["status"], "completed")
        self.assertEqual(approval_data["evidence_result"]["result"], {"ok": True})
        action_data = json.loads(rows[1]["input"])
        self.assertEqual(action_data["approval_id"], approval.approval_id)

    def test_approval_cannot_be_created_without_trusted_authority_adapter(self):
        unconfigured = CommerceControlPlane(
            self.memory_root, actions={"update_memory": ("docs/agent-context",)}
        )
        unconfigured.register_action("update_memory", lambda _proposal: {"ok": True})
        with self.assertRaisesRegex(ApprovalDenied, "human_approval_authority_required"):
            unconfigured.decide(
                self.proposal(), ApprovalDecision.APPROVED, {"approver": "caller"},
                approval_evidence="claimed-human-approval",
            )

    def test_only_verified_evidence_updates_agent_memory(self):
        unverified = Evidence("result", EvidenceState.UNVERIFIED, "chat", "today", "reported")
        with self.assertRaisesRegex(ValueError, "only_verified"):
            self.control.record_verified_memory(unverified, approval_id="missing", scope="project", scope_id="phase-2e", key="test", value="pass")
        proposal = self.proposal(scope=("agent-memory/project/phase-2e/tests",))
        approval = self.control.decide(
            proposal, ApprovalDecision.APPROVED, {"approver": "human"},
            approval_evidence="valid-human-confirmation",
        )
        self.control.execute(proposal, approval.approval_id)
        verified_without_test = Evidence("result", EvidenceState.VERIFIED, "pytest -q", "today", "112 passed")
        with self.assertRaisesRegex(ApprovalDenied, "test_evidence_required"):
            self.control.record_verified_memory(verified_without_test, approval_id=approval.approval_id,
                                                scope="project", scope_id="phase-2e", key="tests", value="passed")
        verified = self.control.record_test_result(
            approval.approval_id, command="pytest -q", passed=True, output="112 passed"
        )
        self.control.record_verified_memory(verified, approval_id=approval.approval_id,
                                           scope="project", scope_id="phase-2e", key="tests", value="passed")
        memory = recall("project", "phase-2e")
        self.assertEqual(memory["tests"]["value"], "passed")
        self.assertEqual(memory["tests"]["evidence"]["state"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
