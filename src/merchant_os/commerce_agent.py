"""Deterministic project-control plane for a provider-agnostic Commerce agent.

Reasoning providers can only return Proposal values. Registered local handlers
are reachable through this control plane only after a proposal is revalidated
and a matching persisted approval record is supplied. This is a process-level
approval boundary; the repository currently has no authenticated approver system.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from . import database
from .agent_runtime import ensure_runtime_schema


class RecordKind(str, Enum):
    FACT = "FACT"
    DECISION = "DECISION"
    PLAN = "PLAN"
    PROPOSAL = "PROPOSAL"
    RISK = "RISK"
    VERIFIED_EVIDENCE = "VERIFIED EVIDENCE"
    UNVERIFIED_CLAIM = "UNVERIFIED CLAIM"


class EvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalAuthority(Protocol):
    """Trusted human-approval adapter; no implementation/auth provider ships in V1."""

    def verify(self, proposal: Proposal, decision: ApprovalDecision,
               approver_context: Mapping[str, Any], approval_evidence: Any) -> bool:
        ...


class ControlPlaneError(Exception):
    pass


class ScopeViolation(ControlPlaneError):
    pass


class ApprovalDenied(ControlPlaneError):
    pass


@dataclass(frozen=True)
class Evidence:
    claim: str
    state: EvidenceState
    source: str
    observed_at: str
    detail: str

    def __post_init__(self):
        if not self.claim.strip() or not self.source.strip() or not self.observed_at.strip():
            raise ValueError("evidence_claim_source_and_timestamp_required")
        if self.state is EvidenceState.VERIFIED and not self.detail.strip():
            raise ValueError("verified_evidence_requires_observation_detail")

    @property
    def kind(self) -> RecordKind:
        return (RecordKind.VERIFIED_EVIDENCE if self.state is EvidenceState.VERIFIED
                else RecordKind.UNVERIFIED_CLAIM)


@dataclass(frozen=True)
class Proposal:
    task_id: str
    action: str
    scope: tuple[str, ...]
    summary: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def fingerprint(self) -> str:
        canonical = json.dumps({
            "task_id": self.task_id, "action": self.action, "scope": list(self.scope),
            "summary": self.summary, "parameters": self.parameters,
            "proposal_id": self.proposal_id,
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    proposal_id: str
    proposal_hash: str
    task_id: str
    action: str
    scope: tuple[str, ...]
    approver_context: Mapping[str, Any]
    timestamp: str
    decision: ApprovalDecision
    evidence_result: Mapping[str, Any]


class ReasoningProvider(Protocol):
    """Provider interface: output a proposal only; never receives executors."""

    def propose(self, task: Mapping[str, Any], project_memory: Mapping[str, str]) -> Proposal:
        ...


class ProjectMemory:
    """Read agent-context documents without changing them or asserting truth."""

    FILES = (
        "README.md", "PROJECT_STATE.md", "phases/HISTORY.md", "ROADMAP.md",
        "EVIDENCE_AND_RISKS.md", "DECISIONS.md", "CONSTRAINTS.md",
    )

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def load(self) -> dict[str, str]:
        folder = self.root / "docs" / "agent-context"
        return {
            relative: (folder / relative).read_text(encoding="utf-8")
            for relative in self.FILES if (folder / relative).is_file()
        }

    def current_phase(self) -> str | None:
        roadmap = self.load().get("ROADMAP.md", "")
        rows = self._phase_rows(roadmap)
        active = next((name for name, status in rows if "IN PROGRESS" in status.upper()), None)
        if active:
            return active
        completed = [name for name, status in rows if "COMPLETE" in status.upper()]
        return completed[-1] if completed else None

    def next_phase(self) -> str | None:
        rows = self._phase_rows(self.load().get("ROADMAP.md", ""))
        active_index = next((index for index, (_, status) in enumerate(rows)
                             if "IN PROGRESS" in status.upper()), None)
        if active_index is not None:
            following = rows[active_index + 1:]
        else:
            completed_indexes = [index for index, (_, status) in enumerate(rows)
                                 if "COMPLETE" in status.upper()]
            following = rows[completed_indexes[-1] + 1:] if completed_indexes else rows
        return next((name for name, status in following
                     if any(term in status.upper() for term in ("PLANNED", "NOT AUTHORIZED", "UNVERIFIED"))), None)

    @staticmethod
    def _phase_rows(roadmap: str) -> list[tuple[str, str]]:
        rows = []
        for line in roadmap.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0].startswith("Phase "):
                rows.append((cells[0], cells[2]))
        return rows


@dataclass(frozen=True)
class _Action:
    scope_prefixes: tuple[str, ...]
    handler: Callable[[Proposal], Mapping[str, Any]]


class CommerceControlPlane:
    """Validate proposals and mediate explicitly approved registered actions."""

    def __init__(self, project_root: str | Path, actions: Mapping[str, Sequence[str]] | None = None,
                 approval_authority: ApprovalAuthority | None = None):
        self.memory = ProjectMemory(project_root)
        self._actions: dict[str, _Action] = {}
        self._scope_configuration = dict(actions or {})
        self.approval_authority = approval_authority

    @staticmethod
    def _normalize_scope(scope: str) -> str:
        raw = scope.replace("\\", "/").strip()
        if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
            raise ScopeViolation("invalid_scope")
        normalized = raw.strip("/")
        parts = normalized.split("/")
        if not normalized or any(part in ("", ".", "..") for part in parts):
            raise ScopeViolation("invalid_scope")
        return normalized

    def register_action(self, action: str, handler: Callable[[Proposal], Mapping[str, Any]]) -> None:
        configured = self._scope_configuration.get(action)
        if not configured or not callable(handler):
            raise ValueError("action_requires_configured_scope_and_handler")
        prefixes = tuple(self._normalize_scope(scope) for scope in configured)
        self._actions[action] = _Action(prefixes, handler)

    def validate_proposal(self, proposal: Proposal) -> Proposal:
        action = self._actions.get(proposal.action)
        if action is None:
            raise ScopeViolation("action_not_registered")
        if not proposal.task_id.strip() or not proposal.summary.strip() or not proposal.scope:
            raise ScopeViolation("proposal_missing_required_fields")
        normalized_scope = tuple(self._normalize_scope(item) for item in proposal.scope)
        for target in normalized_scope:
            if not any(target == allowed or target.startswith(allowed.rstrip("/") + "/")
                       for allowed in action.scope_prefixes):
                raise ScopeViolation("proposal_scope_exceeds_approved_boundary")
        return proposal

    def request_proposal(self, provider: ReasoningProvider, task: Mapping[str, Any]) -> Proposal:
        """Ask an injected reasoning provider for a proposal and validate only."""
        result = provider.propose(dict(task), self.memory.load())
        if not isinstance(result, Proposal):
            raise TypeError("reasoning_provider_must_return_proposal")
        return self.validate_proposal(result)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _proposal_data(proposal: Proposal) -> dict:
        return {
            "task_id": proposal.task_id, "action": proposal.action,
            "scope": list(proposal.scope), "summary": proposal.summary,
            "parameters": dict(proposal.parameters), "proposal_id": proposal.proposal_id,
        }

    def decide(self, proposal: Proposal, decision: ApprovalDecision,
               approver_context: Mapping[str, Any], *, approval_evidence: Any = None) -> ApprovalRecord:
        self.validate_proposal(proposal)
        if not isinstance(decision, ApprovalDecision):
            raise ValueError("invalid_approval_decision")
        approver = approver_context.get("approver") if approver_context else None
        if not isinstance(approver, str) or not approver.strip():
            raise ValueError("approver_identity_context_required")
        if (self.approval_authority is None or approval_evidence is None
                or self.approval_authority.verify(proposal, decision, approver_context, approval_evidence) is not True):
            raise ApprovalDenied("human_approval_authority_required")
        approval = ApprovalRecord(
            approval_id=str(uuid.uuid4()), proposal_id=proposal.proposal_id,
            proposal_hash=proposal.fingerprint(), task_id=proposal.task_id,
            action=proposal.action, scope=proposal.scope,
            approver_context=dict(approver_context), timestamp=self._now(),
            decision=decision,
            evidence_result={"status": "awaiting_execution" if decision is ApprovalDecision.APPROVED
                             else "rejected"},
        )
        self._audit(
            task_id=approval.approval_id, task_type="commerce_approval",
            agent="commerce_control_plane", status=decision.value,
            input_data=self._proposal_data(proposal),
            output_data={
                **asdict(approval), "decision": decision.value,
                "scope": list(approval.scope),
            }, error=None,
        )
        return approval

    def execute(self, proposal: Proposal, approval_id: str) -> Mapping[str, Any]:
        """Execute once through a registered handler after persisted approval validation.

        A caller-supplied boolean such as ``approved=True`` is not accepted here.
        """
        self.validate_proposal(proposal)
        approval = self._load_approval(approval_id)
        if (approval is None or approval["decision"] != ApprovalDecision.APPROVED.value
                or approval["proposal_hash"] != proposal.fingerprint()
                or approval["proposal_id"] != proposal.proposal_id
                or approval["task_id"] != proposal.task_id
                or approval["action"] != proposal.action
                or tuple(approval["scope"]) != proposal.scope):
            raise ApprovalDenied("matching_persisted_approval_required")

        runtime_id = str(uuid.uuid4())
        ensure_runtime_schema()
        with database.get_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT input FROM agent_runs WHERE task_type='commerce_action'"
            ).fetchall()
            if any(json.loads(row["input"] or "{}").get("approval_id") == approval_id for row in rows):
                db.rollback()
                raise ApprovalDenied("approval_already_consumed")
            db.execute(
                """INSERT INTO agent_runs
                   (task_id, parent_task_id, task_type, agent, status, input, output, error, created_at)
                   VALUES (?, ?, 'commerce_action', 'commerce_control_plane', 'running', ?, NULL, NULL, ?)""",
                (runtime_id, proposal.task_id,
                 json.dumps({"approval_id": approval_id, "proposal": self._proposal_data(proposal)}, ensure_ascii=False),
                 self._now()),
            )
            db.commit()

        try:
            output = dict(self._actions[proposal.action].handler(proposal) or {})
            self._finish_action(runtime_id, "completed", output, None, approval_id)
            return output
        except Exception as exc:
            self._finish_action(runtime_id, "failed", {}, str(exc), approval_id)
            raise

    def record_test_result(self, approval_id: str, *, command: str,
                           passed: bool, output: str) -> Evidence:
        """Attach the result of an externally run test to a completed action."""
        if not isinstance(passed, bool) or not isinstance(command, str) or not command.strip():
            raise ValueError("test_result_requires_boolean_and_command")
        if not isinstance(output, str) or not output.strip():
            raise ValueError("test_result_output_required")
        approval = self._load_approval(approval_id)
        if approval is None or approval["decision"] != ApprovalDecision.APPROVED.value:
            raise ApprovalDenied("approved_action_required_for_test_evidence")
        evidence = Evidence(
            claim=f"Verification for approved task {approval['task_id']}",
            state=EvidenceState.VERIFIED if passed else EvidenceState.UNVERIFIED,
            source=command, observed_at=self._now(),
            detail=output.strip() if passed else f"Test run failed or is unverified: {output.strip()}",
        )
        serialized = asdict(evidence)
        serialized["state"] = evidence.state.value
        ensure_runtime_schema()
        with database.get_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT status, input FROM agent_runs WHERE task_type='commerce_action'").fetchall()
            action_done = any(
                row["status"] == "completed"
                and json.loads(row["input"] or "{}").get("approval_id") == approval_id
                for row in rows
            )
            if not action_done:
                raise ApprovalDenied("completed_action_required_for_test_evidence")
            result_id = str(uuid.uuid4())
            now = self._now()
            status = "PASSED" if passed else "FAILED"
            db.execute(
                """INSERT INTO agent_runs
                   (task_id, parent_task_id, task_type, agent, status, input, output, error, created_at)
                   VALUES (?, ?, 'commerce_test', 'commerce_control_plane', ?, ?, ?, NULL, ?)""",
                (result_id, approval_id, status,
                 json.dumps({"command": command}, ensure_ascii=False),
                 json.dumps({"evidence": serialized}, ensure_ascii=False), now),
            )
            approval_row = db.execute(
                "SELECT output FROM agent_runs WHERE task_id=? AND task_type='commerce_approval'",
                (approval_id,),
            ).fetchone()
            approval_output = json.loads(approval_row["output"])
            approval_output["evidence_result"]["test"] = {
                "status": status, "command": command, "task_id": result_id,
            }
            db.execute(
                "UPDATE agent_runs SET output=? WHERE task_id=? AND task_type='commerce_approval'",
                (json.dumps(approval_output, ensure_ascii=False), approval_id),
            )
            db.commit()
            return evidence

    def record_verified_memory(self, evidence: Evidence, *, approval_id: str,
                               scope: str, scope_id: str, key: str, value: Any) -> None:
        if evidence.state is not EvidenceState.VERIFIED or evidence.kind is not RecordKind.VERIFIED_EVIDENCE:
            raise ValueError("only_verified_evidence_may_update_memory")
        if not scope.strip() or not scope_id.strip() or not key.strip():
            raise ValueError("memory_scope_id_and_key_required")
        serialized = asdict(evidence)
        serialized["state"] = evidence.state.value
        ensure_runtime_schema()
        with database.get_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            approval_row = db.execute(
                "SELECT output FROM agent_runs WHERE task_id=? AND task_type='commerce_approval'",
                (approval_id,),
            ).fetchone()
            if approval_row is None:
                raise ApprovalDenied("approved_action_required_for_memory_update")
            approval_output = json.loads(approval_row["output"])
            if approval_output.get("decision") != ApprovalDecision.APPROVED.value:
                raise ApprovalDenied("approved_action_required_for_memory_update")
            memory_target = self._normalize_scope(f"agent-memory/{scope}/{scope_id}/{key}")
            approved_scopes = tuple(approval_output.get("scope") or ())
            if not any(memory_target == allowed or memory_target.startswith(allowed.rstrip("/") + "/")
                       for allowed in approved_scopes):
                raise ScopeViolation("memory_target_exceeds_approved_scope")
            action_rows = db.execute(
                "SELECT status, input FROM agent_runs WHERE task_type='commerce_action'"
            ).fetchall()
            action_done = any(
                row["status"] == "completed"
                and json.loads(row["input"] or "{}").get("approval_id") == approval_id
                for row in action_rows
            )
            test_row = db.execute(
                """SELECT status, output FROM agent_runs
                   WHERE task_type='commerce_test' AND parent_task_id=? ORDER BY run_id DESC LIMIT 1""",
                (approval_id,),
            ).fetchone()
            if not action_done or test_row is None or test_row["status"] != "PASSED":
                raise ApprovalDenied("completed_action_and_passed_test_evidence_required")
            recorded = json.loads(test_row["output"] or "{}").get("evidence")
            if recorded != serialized:
                raise ApprovalDenied("memory_evidence_does_not_match_test_record")

            now = self._now()
            memory_value = json.dumps({
                "value": value, "evidence": serialized,
                "record_kind": evidence.kind.value, "updated_at": now,
            }, ensure_ascii=False, default=str)
            db.execute(
                """INSERT INTO agent_memory
                   (scope, scope_id, memory_key, memory_value, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scope, scope_id, memory_key) DO UPDATE SET
                       memory_value=excluded.memory_value, updated_at=excluded.updated_at""",
                (scope, scope_id, key, memory_value, now, now),
            )
            approval_output["evidence_result"]["memory_update"] = {
                "scope": scope, "scope_id": scope_id, "key": key, "recorded_at": now,
            }
            db.execute(
                "UPDATE agent_runs SET output=? WHERE task_id=? AND task_type='commerce_approval'",
                (json.dumps(approval_output, ensure_ascii=False, default=str), approval_id),
            )
            db.execute(
                """INSERT INTO agent_runs
                   (task_id, parent_task_id, task_type, agent, status, input, output, error, created_at)
                   VALUES (?, ?, 'commerce_memory_update', 'commerce_control_plane', 'completed', ?, ?, NULL, ?)""",
                (str(uuid.uuid4()), approval_id,
                 json.dumps({"scope": scope, "scope_id": scope_id, "key": key}, ensure_ascii=False),
                 json.dumps({"evidence": serialized}, ensure_ascii=False, default=str), now),
            )
            db.commit()

    def _load_approval(self, approval_id: str) -> dict | None:
        ensure_runtime_schema()
        with database.get_connection() as db:
            row = db.execute(
                "SELECT output FROM agent_runs WHERE task_id=? AND task_type='commerce_approval'",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row["output"])
        value["decision"] = value["decision"] if isinstance(value["decision"], str) else value["decision"].value
        return value

    def _audit(self, *, task_id: str, task_type: str, agent: str, status: str,
               input_data: Mapping[str, Any], output_data: Mapping[str, Any], error: str | None) -> None:
        ensure_runtime_schema()
        with database.get_connection() as db:
            db.execute(
                """INSERT INTO agent_runs
                   (task_id, parent_task_id, task_type, agent, status, input, output, error, created_at)
                   VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, task_type, agent, status,
                 json.dumps(input_data, ensure_ascii=False, default=str),
                 json.dumps(output_data, ensure_ascii=False, default=str), error, self._now()),
            )
            db.commit()

    def _finish_action(self, task_id: str, status: str, output: Mapping[str, Any],
                       error: str | None, approval_id: str) -> None:
        with database.get_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE agent_runs SET status=?, output=?, error=? WHERE task_id=? AND task_type='commerce_action'",
                (status, json.dumps(output, ensure_ascii=False, default=str), error, task_id),
            )
            approval_row = db.execute(
                "SELECT output FROM agent_runs WHERE task_id=? AND task_type='commerce_approval'",
                (approval_id,),
            ).fetchone()
            if approval_row is not None:
                approval_output = json.loads(approval_row["output"])
                approval_output["evidence_result"] = {
                    "status": status, "result": dict(output), "error": error,
                    "action_task_id": task_id,
                }
                db.execute(
                    "UPDATE agent_runs SET output=? WHERE task_id=? AND task_type='commerce_approval'",
                    (json.dumps(approval_output, ensure_ascii=False, default=str), approval_id),
                )
            db.commit()
