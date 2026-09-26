"""Atomic Commerce Order and Fulfillment state transitions."""
import sqlite3
from datetime import datetime, timezone

from . import database
from .actors import require_actor
from .commerce_errors import CommerceError

MERCHANT_ORDER_TRANSITIONS = {
    "pending": {"confirmed"},
    "confirmed": {"processing"},
    "processing": {"ready"}, "ready": {"completed"},
    "completed": set(), "cancelled": set(),
}
FULFILLMENT_TRANSITIONS = {
    "pending": {"processing", "cancelled"}, "processing": {"ready"},
    "ready": {"completed"}, "completed": set(), "cancelled": set(),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def root_status(statuses):
    statuses = list(statuses)
    if not statuses:
        return "pending"
    if all(s == "cancelled" for s in statuses):
        return "cancelled"
    if any(s == "cancelled" for s in statuses):
        return "partially_cancelled"
    if all(s == "completed" for s in statuses):
        return "completed"
    if any(s in {"confirmed", "processing", "ready", "completed"} for s in statuses):
        return "processing"
    return "pending"


def transition_merchant_order(merchant_order_id, target, *, actor, verifier, note=None):
    resource = {"merchant_order_id": merchant_order_id}
    actor = require_actor(actor, verifier, "order.transition", resource)
    with database.get_connection() as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM merchant_orders WHERE merchant_order_id=?", (merchant_order_id,)).fetchone()
            if row is None:
                raise CommerceError("ORDER_NOT_FOUND")
            if actor.actor_type == "CUSTOMER" or (actor.actor_type == "MERCHANT" and actor.actor_ref != str(row["merchant_id"])):
                raise CommerceError("FORBIDDEN")
            if target == row["status"]:
                db.commit(); return dict(row)
            allowed = MERCHANT_ORDER_TRANSITIONS.get(row["status"], set())
            if target not in allowed:
                raise CommerceError("INVALID_STATE_TRANSITION")
            now = _now()
            db.execute("UPDATE merchant_orders SET status=?,updated_at=? WHERE merchant_order_id=?", (target, now, merchant_order_id))
            for f in db.execute("SELECT fulfillment_id,status FROM fulfillments WHERE merchant_order_id=?", (merchant_order_id,)).fetchall():
                next_status = "processing" if target == "processing" else ("ready" if target == "ready" else ("completed" if target == "completed" else None))
                if next_status and next_status in FULFILLMENT_TRANSITIONS.get(f["status"], set()):
                    db.execute("UPDATE fulfillments SET status=?,updated_at=? WHERE fulfillment_id=?", (next_status, now, f["fulfillment_id"]))
            states = [r[0] for r in db.execute("SELECT status FROM merchant_orders WHERE order_id=?", (row["order_id"],))]
            db.execute("UPDATE orders SET status=?,updated_at=? WHERE order_id=?", (root_status(states), now, row["order_id"]))
            db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,created_at) VALUES(?,?,?,?,?,?)",
                       ("ORDER_" + target.upper(), actor.actor_type, actor.actor_ref, "merchant_order", merchant_order_id, now))
            db.commit()
            return dict(db.execute("SELECT * FROM merchant_orders WHERE merchant_order_id=?", (merchant_order_id,)).fetchone())
        except Exception:
            db.rollback()
            raise


def transition_fulfillment(fulfillment_id, target, *, actor, verifier):
    actor=require_actor(actor,verifier,"fulfillment.transition",{"fulfillment_id":fulfillment_id})
    if target == "cancelled":
        raise CommerceError("INVALID_STATE_TRANSITION")
    with database.get_connection() as db:
        db.execute("PRAGMA foreign_keys=ON"); db.execute("BEGIN IMMEDIATE")
        try:
            row=db.execute("SELECT f.*,mo.order_id,mo.status AS merchant_order_status FROM fulfillments f JOIN merchant_orders mo ON mo.merchant_order_id=f.merchant_order_id WHERE f.fulfillment_id=?",(fulfillment_id,)).fetchone()
            if row is None: raise CommerceError("FULFILLMENT_INVALID")
            if actor.actor_type == "CUSTOMER" or (actor.actor_type == "MERCHANT" and actor.actor_ref != str(db.execute("SELECT merchant_id FROM merchant_orders WHERE merchant_order_id=?",(row["merchant_order_id"],)).fetchone()[0])):
                raise CommerceError("FORBIDDEN")
            if target == row["status"]:
                db.commit(); return dict(row)
            if target not in FULFILLMENT_TRANSITIONS.get(row["status"],set()): raise CommerceError("INVALID_STATE_TRANSITION")
            expected_mo={"processing":"confirmed","ready":"processing","completed":"ready"}[target]
            if row["merchant_order_status"] not in {expected_mo, target}:
                raise CommerceError("INVALID_STATE_TRANSITION")
            now=_now(); db.execute("UPDATE fulfillments SET status=?,updated_at=? WHERE fulfillment_id=?",(target,now,fulfillment_id))
            mo_target={"processing":"processing","ready":"ready","completed":"completed"}[target]
            db.execute("UPDATE merchant_orders SET status=?,updated_at=? WHERE merchant_order_id=?",(mo_target,now,row["merchant_order_id"]))
            states=[r[0] for r in db.execute("SELECT status FROM merchant_orders WHERE order_id=?",(row["order_id"],))]
            db.execute("UPDATE orders SET status=?,updated_at=? WHERE order_id=?",(root_status(states),now,row["order_id"]))
            event="FULFILLMENT_"+target.upper()
            db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,created_at) VALUES(?,?,?,?,?,?)",(event,actor.actor_type,actor.actor_ref,"fulfillment",fulfillment_id,now))
            db.commit(); return dict(db.execute("SELECT * FROM fulfillments WHERE fulfillment_id=?",(fulfillment_id,)).fetchone())
        except Exception: db.rollback(); raise
