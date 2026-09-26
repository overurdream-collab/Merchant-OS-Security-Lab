"""Atomic, idempotent whole-Merchant-Order cancellation and stock restoration."""
from datetime import datetime, timezone

from . import database
from .actors import require_actor
from .commerce_errors import CommerceError
from .order_lifecycle import root_status


def _now():
    return datetime.now(timezone.utc).isoformat()


class CancellationService:
    def __init__(self, *, identity_verifier):
        self.identity_verifier = identity_verifier

    def cancel_merchant_order(self, merchant_order_id, *, actor, reason=None):
        actor = require_actor(actor, self.identity_verifier, "order.cancel", {"merchant_order_id": merchant_order_id})
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                mo = db.execute("SELECT * FROM merchant_orders WHERE merchant_order_id=?", (merchant_order_id,)).fetchone()
                if mo is None:
                    raise CommerceError("ORDER_NOT_FOUND")
                if actor.actor_type == "MERCHANT" and actor.actor_ref != str(mo["merchant_id"]):
                    raise CommerceError("FORBIDDEN")
                if actor.actor_type == "CUSTOMER":
                    owner=db.execute("SELECT customer_id FROM orders WHERE order_id=?",(mo["order_id"],)).fetchone()
                    if owner is None or actor.actor_ref != str(owner[0]): raise CommerceError("FORBIDDEN")
                if mo["status"] == "cancelled":
                    db.commit()
                    return dict(mo)
                if mo["status"] not in {"pending", "confirmed"}:
                    raise CommerceError("ORDER_NOT_CANCELLABLE")
                if db.execute("SELECT 1 FROM fulfillments WHERE merchant_order_id=? AND status!='pending' LIMIT 1", (merchant_order_id,)).fetchone():
                    raise CommerceError("ORDER_NOT_CANCELLABLE")
                now = _now()
                lines = db.execute("SELECT order_item_id,offer_id,quantity FROM order_items WHERE merchant_order_id=?", (merchant_order_id,)).fetchall()
                for line in lines:
                    movement = db.execute("SELECT quantity FROM inventory_movements WHERE order_item_id=? AND movement_type='STOCK_DECREMENTED'", (line["order_item_id"],)).fetchone()
                    if movement:
                        # A stock restoration is keyed per historical order item; transaction makes retry exactly-once.
                        restored = db.execute("SELECT 1 FROM inventory_movements WHERE order_item_id=? AND movement_type='STOCK_RESTORED'", (line["order_item_id"],)).fetchone()
                        if not restored:
                            changed = db.execute("UPDATE offers SET stock=stock+? WHERE offer_id=? AND stock IS NOT NULL", (movement["quantity"], line["offer_id"]))
                            if changed.rowcount != 1:
                                raise CommerceError("INVENTORY_RESTORE_FAILED")
                            db.execute("INSERT INTO inventory_movements(order_item_id,offer_id,movement_type,quantity,dedupe_key,created_at) VALUES(?,?,'STOCK_RESTORED',?,?,?)",
                                       (line["order_item_id"], line["offer_id"], movement["quantity"], f"cancel:{line['order_item_id']}", now))
                            db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,dedupe_key,created_at) VALUES('STOCK_RESTORED',?,?,?,?,?,?)",
                                       (actor.actor_type, actor.actor_ref, "order_item", line["order_item_id"], f"restore-event:{line['order_item_id']}", now))
                db.execute("UPDATE merchant_orders SET status='cancelled',updated_at=? WHERE merchant_order_id=?", (now, merchant_order_id))
                db.execute("UPDATE fulfillments SET status='cancelled',updated_at=? WHERE merchant_order_id=? AND status='pending'", (now, merchant_order_id))
                db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,created_at) VALUES('MERCHANT_ORDER_CANCELLED',?,?,?,?,?)",
                           (actor.actor_type, actor.actor_ref, "merchant_order", merchant_order_id, now))
                states = [r[0] for r in db.execute("SELECT status FROM merchant_orders WHERE order_id=?", (mo["order_id"],))]
                status = root_status(states)
                db.execute("UPDATE orders SET status=?,updated_at=? WHERE order_id=?", (status, now, mo["order_id"]))
                db.execute("INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)", (mo["order_id"], status, "Merchant order cancelled", now))
                db.commit()
                return dict(db.execute("SELECT * FROM merchant_orders WHERE merchant_order_id=?", (merchant_order_id,)).fetchone())
            except Exception:
                db.rollback()
                raise

    def cancel_root_order(self, order_id, *, actor, reason=None):
        actor = require_actor(actor, self.identity_verifier, "order.cancel", {"order_id": order_id})
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                root = db.execute("SELECT order_id FROM orders WHERE order_id=?", (order_id,)).fetchone()
                if root is None:
                    raise CommerceError("ORDER_NOT_FOUND")
                current_root=db.execute("SELECT * FROM orders WHERE order_id=?",(order_id,)).fetchone()
                if actor.actor_type == "MERCHANT": raise CommerceError("FORBIDDEN")
                if actor.actor_type == "CUSTOMER" and actor.actor_ref != str(current_root["customer_id"]): raise CommerceError("FORBIDDEN")
                if current_root["status"] == "cancelled":
                    db.commit(); return dict(current_root)
                rows = db.execute("SELECT merchant_order_id FROM merchant_orders WHERE order_id=?", (order_id,)).fetchall()
                if not rows:
                    raise CommerceError("ORDER_NOT_CANCELLABLE")
                # Preflight every child before any change; then cancel all within this transaction.
                for row in rows:
                    mo = db.execute("SELECT status FROM merchant_orders WHERE merchant_order_id=?", (row[0],)).fetchone()
                    if mo[0] not in {"pending", "confirmed", "cancelled"} or (mo[0] != "cancelled" and db.execute("SELECT 1 FROM fulfillments WHERE merchant_order_id=? AND status!='pending' LIMIT 1", (row[0],)).fetchone()):
                        raise CommerceError("ORDER_NOT_CANCELLABLE")
                for row in rows:
                    current = db.execute("SELECT status FROM merchant_orders WHERE merchant_order_id=?", (row[0],)).fetchone()[0]
                    if current != "cancelled":
                        self._cancel_inside(db, row[0], actor, reason)
                now = _now()
                states = [r[0] for r in db.execute("SELECT status FROM merchant_orders WHERE order_id=?", (order_id,))]
                status = root_status(states)
                db.execute("UPDATE orders SET status=?,updated_at=? WHERE order_id=?", (status, now, order_id))
                db.execute("INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)", (order_id,status,"Root order cancelled",now))
                db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,created_at) VALUES('ORDER_CANCELLED',?,?,?,?,?)", (actor.actor_type,actor.actor_ref,"order",order_id,now))
                db.commit()
                return dict(db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone())
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def _cancel_inside(db, merchant_order_id, actor, reason):
        now = _now()
        mo = db.execute("SELECT * FROM merchant_orders WHERE merchant_order_id=?", (merchant_order_id,)).fetchone()
        for line in db.execute("SELECT order_item_id,offer_id FROM order_items WHERE merchant_order_id=?", (merchant_order_id,)).fetchall():
            move = db.execute("SELECT quantity FROM inventory_movements WHERE order_item_id=? AND movement_type='STOCK_DECREMENTED'", (line[0],)).fetchone()
            if move and not db.execute("SELECT 1 FROM inventory_movements WHERE order_item_id=? AND movement_type='STOCK_RESTORED'", (line[0],)).fetchone():
                if db.execute("UPDATE offers SET stock=stock+? WHERE offer_id=? AND stock IS NOT NULL", (move[0], line[1])).rowcount != 1:
                    raise CommerceError("INVENTORY_RESTORE_FAILED")
                db.execute("INSERT INTO inventory_movements(order_item_id,offer_id,movement_type,quantity,dedupe_key,created_at) VALUES(?,?,'STOCK_RESTORED',?,?,?)", (line[0],line[1],move[0],f"cancel:{line[0]}",now))
                db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,dedupe_key,created_at) VALUES('STOCK_RESTORED',?,?,?,?,?,?)",(actor.actor_type,actor.actor_ref,'order_item',line[0],f'restore-event:{line[0]}',now))
        db.execute("UPDATE merchant_orders SET status='cancelled',updated_at=? WHERE merchant_order_id=?", (now,merchant_order_id))
        db.execute("UPDATE fulfillments SET status='cancelled',updated_at=? WHERE merchant_order_id=? AND status='pending'", (now,merchant_order_id))
        db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,created_at) VALUES('MERCHANT_ORDER_CANCELLED',?,?,?,?,?)",(actor.actor_type,actor.actor_ref,'merchant_order',merchant_order_id,now))
