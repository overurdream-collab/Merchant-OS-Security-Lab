from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, Optional

from .database import get_connection, utc_now


EVENT_TYPES = (
    "merchant_discovered",
    "merchant_contacted",
    "merchant_response",
    "merchant_converted",
    "customer_discovered",
    "customer_contacted",
    "customer_intent",
    "order_created",
    "order_delivered",
    "order_returned",
    "order_cancelled",
    "order_repeat",
    "payment_collected",
    "commission_earned",
)


@dataclass(frozen=True)
class BusinessEvent:
    event_type: str
    subject_type: str
    subject_id: str
    occurred_at: str
    event_id: str = ""
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None
    source: Optional[str] = None
    evidence_id: Optional[str] = None
    confidence: Optional[float] = None
    value: Optional[float] = None
    currency: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def normalized(self) -> "BusinessEvent":
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"Unsupported event_type: {self.event_type}")
        if not self.subject_type or not self.subject_id:
            raise ValueError("subject_type and subject_id are required")
        confidence = self.confidence
        if confidence is not None and not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return BusinessEvent(
            event_type=self.event_type,
            subject_type=self.subject_type,
            subject_id=str(self.subject_id),
            occurred_at=self.occurred_at or utc_now(),
            event_id=self.event_id or str(uuid.uuid4()),
            actor_type=self.actor_type,
            actor_id=str(self.actor_id) if self.actor_id is not None else None,
            source=self.source,
            evidence_id=self.evidence_id,
            confidence=confidence,
            value=float(self.value) if self.value is not None else None,
            currency=self.currency,
            metadata=self.metadata or {},
        )


def ensure_unified_schema() -> None:
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS business_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                actor_type TEXT,
                actor_id TEXT,
                source TEXT,
                evidence_id TEXT,
                confidence REAL,
                value REAL,
                currency TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_subject ON business_events(subject_type, subject_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON business_events(event_type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_occurred ON business_events(occurred_at)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS profile_observations (
                observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                field_value TEXT,
                value_type TEXT NOT NULL DEFAULT 'text',
                source TEXT,
                evidence_id TEXT,
                confidence REAL,
                observed_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_profile_obs_subject ON profile_observations(subject_type, subject_id)")
        db.commit()


def record_event(event: BusinessEvent) -> str:
    event = event.normalized()
    ensure_unified_schema()
    with get_connection() as db:
        db.execute("""
            INSERT OR IGNORE INTO business_events (
                event_id,event_type,subject_type,subject_id,actor_type,actor_id,
                source,evidence_id,confidence,value,currency,metadata,occurred_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            event.event_id, event.event_type, event.subject_type, event.subject_id,
            event.actor_type, event.actor_id, event.source, event.evidence_id,
            event.confidence, event.value, event.currency,
            json.dumps(event.metadata or {}, ensure_ascii=False),
            event.occurred_at, utc_now(),
        ))
        db.commit()
    return event.event_id


def record_observation(subject_type: str, subject_id: str, field_name: str,
                       field_value: Any, source: Optional[str] = None,
                       evidence_id: Optional[str] = None,
                       confidence: Optional[float] = None,
                       observed_at: Optional[str] = None) -> int:
    if not subject_type or not subject_id or not field_name:
        raise ValueError("subject_type, subject_id and field_name are required")
    if confidence is not None and not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be between 0 and 1")
    ensure_unified_schema()
    value_type = "number" if isinstance(field_value, (int, float)) and not isinstance(field_value, bool) else "boolean" if isinstance(field_value, bool) else "json" if isinstance(field_value, (dict, list)) else "text"
    serialized = json.dumps(field_value, ensure_ascii=False) if value_type == "json" else str(field_value) if field_value is not None else None
    with get_connection() as db:
        cur = db.execute("""
            INSERT INTO profile_observations
            (subject_type,subject_id,field_name,field_value,value_type,source,evidence_id,confidence,observed_at,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (subject_type, str(subject_id), field_name, serialized, value_type,
              source, evidence_id, confidence, observed_at or utc_now(), utc_now()))
        db.commit()
        return int(cur.lastrowid)


def list_events(subject_type: Optional[str] = None, subject_id: Optional[str] = None,
                event_types: Optional[Iterable[str]] = None, limit: int = 1000) -> list[Dict[str, Any]]:
    ensure_unified_schema()
    clauses, params = [], []
    if subject_type:
        clauses.append("subject_type=?"); params.append(subject_type)
    if subject_id:
        clauses.append("subject_id=?"); params.append(str(subject_id))
    if event_types:
        types = list(event_types)
        if types:
            clauses.append("event_type IN (" + ",".join("?" for _ in types) + ")")
            params.extend(types)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with get_connection() as db:
        rows = db.execute(
            "SELECT * FROM business_events" + where + " ORDER BY occurred_at ASC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"] or "{}")
        result.append(item)
    return result


def list_observations(subject_type: str, subject_id: str, field_name: Optional[str] = None) -> list[Dict[str, Any]]:
    ensure_unified_schema()
    query = "SELECT * FROM profile_observations WHERE subject_type=? AND subject_id=?"
    params = [subject_type, str(subject_id)]
    if field_name:
        query += " AND field_name=?"; params.append(field_name)
    query += " ORDER BY observed_at DESC"
    with get_connection() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(row) for row in rows]
