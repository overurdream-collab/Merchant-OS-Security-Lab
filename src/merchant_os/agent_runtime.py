from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional
import json
import uuid

from .database import get_connection, utc_now

@dataclass
class AgentContext:
    mission_id: str
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    memory: Dict[str, Any] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)

    def add_evidence(self, source: str, data: Dict[str, Any]):
        self.evidence.append({"source": source, "captured_at": utc_now(), "data": data})

@dataclass(frozen=True)
class AgentTask:
    task_id: str
    task_type: str
    input: Dict[str, Any]
    context: Dict[str, Any] = field(default_factory=dict)
    parent_task_id: Optional[str] = None

@dataclass(frozen=True)
class AgentResult:
    task_id: str
    agent: str
    status: str
    output: Dict[str, Any]
    next_agent: Optional[str] = None
    error: Optional[str] = None

@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    task_types: tuple
    handler: Callable[[AgentTask], Dict[str, Any]]

class AgentRuntime:
    def __init__(self, tools=None):
        self.registry: Dict[str, AgentDefinition] = {}
        self.tools = tools

    def register(self, definition): self.registry[definition.name] = definition
    def register_many(self, definitions):
        for definition in definitions: self.register(definition)

    def list_agents(self):
        return [{"name":a.name,"description":a.description,"task_types":list(a.task_types)} for a in self.registry.values()]

    def find_agent(self, task_type):
        return next((a for a in self.registry.values() if task_type in a.task_types), None)

    def run(self, task):
        definition = self.find_agent(task.task_type)
        if not definition:
            result=AgentResult(task.task_id,"unassigned","failed",{},error=f"No agent registered for task type: {task.task_type}")
            self._audit(task,result); return result
        try:
            isolated_task = AgentTask(
                task_id=task.task_id,
                task_type=task.task_type,
                input=deepcopy(task.input),
                context=deepcopy(task.context),
                parent_task_id=task.parent_task_id,
            )
            output=dict(definition.handler(isolated_task) or {})
            next_agent=output.pop("_next_agent",None)
            result=AgentResult(task.task_id,definition.name,"completed",output,next_agent)
        except Exception as exc:
            result=AgentResult(task.task_id,definition.name,"failed",{},error=str(exc))
        self._audit(task,result); return result

    def create_task(self, task_type, input, context=None, parent_task_id=None):
        return AgentTask(str(uuid.uuid4()),task_type,deepcopy(input),deepcopy(context or {}),parent_task_id)

    def _audit(self, task, result):
        ensure_runtime_schema()
        with get_connection() as db:
            db.execute("""INSERT INTO agent_runs
            (task_id,parent_task_id,task_type,agent,status,input,output,error,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (task.task_id,task.parent_task_id,task.task_type,result.agent,result.status,
             json.dumps(task.input,ensure_ascii=False),json.dumps(result.output,ensure_ascii=False),
             result.error,utc_now()))
            db.commit()

def ensure_runtime_schema():
    with get_connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            parent_task_id TEXT, task_type TEXT NOT NULL, agent TEXT NOT NULL,
            status TEXT NOT NULL, input TEXT, output TEXT, error TEXT, created_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS agent_memory (
            memory_id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
            scope_id TEXT NOT NULL, memory_key TEXT NOT NULL, memory_value TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(scope,scope_id,memory_key))""")
        db.commit()

def remember(scope, scope_id, key, value):
    ensure_runtime_schema(); now=utc_now()
    with get_connection() as db:
        db.execute("""INSERT INTO agent_memory
        (scope,scope_id,memory_key,memory_value,created_at,updated_at)
        VALUES (?,?,?,?,?,?) ON CONFLICT(scope,scope_id,memory_key)
        DO UPDATE SET memory_value=excluded.memory_value,updated_at=excluded.updated_at""",
        (scope,scope_id,key,json.dumps(value,ensure_ascii=False),now,now)); db.commit()

def recall(scope, scope_id):
    ensure_runtime_schema()
    with get_connection() as db:
        rows=db.execute("SELECT memory_key,memory_value FROM agent_memory WHERE scope=? AND scope_id=?",(scope,scope_id)).fetchall()
    out={}
    for row in rows:
        try: out[row["memory_key"]]=json.loads(row["memory_value"])
        except (TypeError,json.JSONDecodeError): out[row["memory_key"]]=row["memory_value"]
    return out
