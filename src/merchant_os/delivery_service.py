"""Fulfillment-bound internal delivery operations with immutable snapshots."""
from datetime import datetime, timezone
import hashlib

from . import database
from .actors import require_actor
from .commerce_errors import CommerceError

DELIVERY_TRANSITIONS = {"pending": {"assigned", "failed", "cancelled"}, "assigned": {"out_for_delivery", "failed", "cancelled"},
                        "out_for_delivery": {"delivered", "failed"}, "delivered": set(), "failed": set(), "cancelled": set()}


def _now(): return datetime.now(timezone.utc).isoformat()


class DeliveryService:
    def __init__(self, *, identity_verifier): self.identity_verifier = identity_verifier

    def set_policy(self, merchant_id, zone_id, delivery_fee_minor, *, actor, merchant_receives_fee=False):
        actor=require_actor(actor,self.identity_verifier,"delivery.policy.set",{"merchant_id":merchant_id,"zone_id":zone_id})
        if (actor.actor_type not in {"ADMIN","SYSTEM"} and
                not (actor.actor_type=="MERCHANT" and actor.actor_ref==str(merchant_id))):
            raise CommerceError("FORBIDDEN")
        if (isinstance(delivery_fee_minor,bool) or not isinstance(delivery_fee_minor,int) or delivery_fee_minor<0
                or merchant_receives_fee not in (True,False,0,1)):
            raise CommerceError("DELIVERY_INVALID")
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON"); db.execute("BEGIN IMMEDIATE")
            try:
                valid=db.execute("SELECT 1 FROM merchants WHERE merchant_id=?",(merchant_id,)).fetchone() and db.execute("SELECT 1 FROM delivery_zones WHERE zone_id=? AND active=1",(zone_id,)).fetchone()
                if not valid: raise CommerceError("DELIVERY_INVALID")
                now=_now()
                db.execute("INSERT INTO merchant_delivery_policies(merchant_id,zone_id,delivery_fee,delivery_fee_minor,currency,active,updated_at,merchant_receives_delivery_fee) VALUES(?,?,?,?,'YER',1,?,?) ON CONFLICT(merchant_id,zone_id) DO UPDATE SET delivery_fee=excluded.delivery_fee,delivery_fee_minor=excluded.delivery_fee_minor,currency='YER',active=1,updated_at=excluded.updated_at,merchant_receives_delivery_fee=excluded.merchant_receives_delivery_fee",(merchant_id,zone_id,delivery_fee_minor,delivery_fee_minor,now,int(bool(merchant_receives_fee))))
                db.commit(); return dict(db.execute("SELECT * FROM merchant_delivery_policies WHERE merchant_id=? AND zone_id=?",(merchant_id,zone_id)).fetchone())
            except Exception: db.rollback(); raise

    def create_for_fulfillment(self, fulfillment_id, *, actor, idempotency_key, item_quantities=None):
        actor = require_actor(actor, self.identity_verifier, "delivery.create", {"fulfillment_id": fulfillment_id})
        if not isinstance(idempotency_key,str) or not idempotency_key.strip():
            raise CommerceError("DELIVERY_INVALID")
        key_hash=hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON"); db.execute("BEGIN IMMEDIATE")
            try:
                f = db.execute("SELECT f.*,mo.order_id,mo.merchant_id,mo.delivery_zone_id,mo.delivery_zone_snapshot,mo.delivery_fee_minor,mo.total_minor,o.delivery_address FROM fulfillments f JOIN merchant_orders mo ON mo.merchant_order_id=f.merchant_order_id JOIN orders o ON o.order_id=mo.order_id WHERE f.fulfillment_id=?", (fulfillment_id,)).fetchone()
                if f is None: raise CommerceError("DELIVERY_INVALID")
                if actor.actor_type == "CUSTOMER" or (actor.actor_type == "MERCHANT" and actor.actor_ref != str(f["merchant_id"])): raise CommerceError("FORBIDDEN")
                prior=db.execute("SELECT * FROM deliveries WHERE creation_key_hash=?",(key_hash,)).fetchone()
                if prior:
                    if prior["fulfillment_id"] != fulfillment_id: raise CommerceError("DELIVERY_INVALID")
                    db.commit(); return dict(prior)
                if f["delivery_zone_id"] is None or f["delivery_fee_minor"] is None or f["total_minor"] is None or f["status"] != "ready": raise CommerceError("DELIVERY_INVALID")
                now = _now()
                lines=db.execute("SELECT fulfillment_item_id,quantity FROM fulfillment_items WHERE fulfillment_id=?",(fulfillment_id,)).fetchall()
                if not lines: raise CommerceError("DELIVERY_INVALID")
                remaining={line["fulfillment_item_id"]:line["quantity"]-int(db.execute("SELECT COALESCE(SUM(quantity),0) FROM delivery_items di JOIN deliveries d ON d.delivery_id=di.delivery_id WHERE d.fulfillment_id=? AND di.fulfillment_item_id=? AND d.status!='cancelled'",(fulfillment_id,line["fulfillment_item_id"])).fetchone()[0]) for line in lines}
                requested=item_quantities if item_quantities is not None else {k:v for k,v in remaining.items() if v>0}
                if not isinstance(requested,dict) or not requested: raise CommerceError("DELIVERY_INVALID")
                for item_id,qty in requested.items():
                    if isinstance(qty,bool) or not isinstance(qty,int) or qty<=0 or item_id not in remaining or qty>remaining[item_id]: raise CommerceError("DELIVERY_INVALID")
                cur = db.execute("INSERT INTO deliveries(order_id,fulfillment_id,address,delivery_address_snapshot,delivery_zone_id,delivery_zone_snapshot,customer_delivery_fee,customer_delivery_fee_minor,creation_key_hash,status,collection_amount,collection_amount_minor,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)", (f["order_id"],fulfillment_id,f["delivery_address"],f["delivery_address"],f["delivery_zone_id"],f["delivery_zone_snapshot"],f["delivery_fee_minor"],f["delivery_fee_minor"],key_hash,f["total_minor"],f["total_minor"],now,now))
                delivery_id = cur.lastrowid
                for item_id,qty in requested.items():
                    db.execute("INSERT INTO delivery_items(delivery_id,fulfillment_item_id,quantity,created_at) VALUES(?,?,?,?)", (delivery_id,item_id,qty,now))
                db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,dedupe_key,created_at) VALUES('DELIVERY_CREATED',?,?,?,?,?,?)",(actor.actor_type,actor.actor_ref,'delivery',delivery_id,f'delivery-created:{delivery_id}',now))
                db.commit(); return dict(db.execute("SELECT * FROM deliveries WHERE delivery_id=?",(delivery_id,)).fetchone())
            except Exception: db.rollback(); raise

    def transition(self, delivery_id, target, *, actor):
        actor = require_actor(actor, self.identity_verifier, "delivery.transition", {"delivery_id": delivery_id})
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON"); db.execute("BEGIN IMMEDIATE")
            try:
                row=db.execute("SELECT * FROM deliveries WHERE delivery_id=? AND fulfillment_id IS NOT NULL",(delivery_id,)).fetchone()
                if row is None: raise CommerceError("DELIVERY_INVALID")
                owner=db.execute("SELECT mo.merchant_id FROM deliveries d JOIN fulfillments f ON f.fulfillment_id=d.fulfillment_id JOIN merchant_orders mo ON mo.merchant_order_id=f.merchant_order_id WHERE d.delivery_id=?",(delivery_id,)).fetchone()
                if actor.actor_type == "CUSTOMER" or (actor.actor_type == "MERCHANT" and actor.actor_ref != str(owner[0])): raise CommerceError("FORBIDDEN")
                if target == row["status"]:
                    db.commit(); return dict(row)
                if target not in DELIVERY_TRANSITIONS.get(row["status"],set()): raise CommerceError("INVALID_STATE_TRANSITION")
                now=_now(); db.execute("UPDATE deliveries SET status=?,updated_at=?,assigned_at=CASE WHEN ?='assigned' THEN ? ELSE assigned_at END,shipped_at=CASE WHEN ?='out_for_delivery' THEN ? ELSE shipped_at END,delivered_at=CASE WHEN ?='delivered' THEN ? ELSE delivered_at END WHERE delivery_id=?",(target,now,target,now,target,now,target,now,delivery_id))
                if target == "delivered":
                    others = db.execute("SELECT 1 FROM deliveries WHERE fulfillment_id=? AND delivery_id<>? AND status<>'delivered' LIMIT 1",(row["fulfillment_id"],delivery_id)).fetchone()
                    if not others:
                        db.execute("UPDATE fulfillments SET status='completed',updated_at=? WHERE fulfillment_id=? AND status='ready'",(now,row["fulfillment_id"]))
                        mo_id=db.execute("SELECT merchant_order_id FROM fulfillments WHERE fulfillment_id=?",(row["fulfillment_id"],)).fetchone()[0]
                        mo_order=db.execute("SELECT order_id FROM merchant_orders WHERE merchant_order_id=?",(mo_id,)).fetchone()[0]
                        statuses=[r[0] for r in db.execute("SELECT status FROM merchant_orders WHERE order_id=?",(mo_order,))]
                        from .order_lifecycle import root_status
                        if all(s in {"completed","cancelled"} for s in statuses):
                            db.execute("UPDATE merchant_orders SET status='completed',updated_at=? WHERE merchant_order_id=? AND status='ready'",(now,mo_id))
                            statuses=[r[0] for r in db.execute("SELECT status FROM merchant_orders WHERE order_id=?",(mo_order,))]
                            db.execute("UPDATE orders SET status=?,updated_at=? WHERE order_id=?",(root_status(statuses),now,mo_order))
                db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,created_at) VALUES(?,?,?,?,?,?)",('DELIVERY_'+target.upper(),actor.actor_type,actor.actor_ref,'delivery',delivery_id,now))
                db.commit(); return dict(db.execute("SELECT * FROM deliveries WHERE delivery_id=?",(delivery_id,)).fetchone())
            except Exception: db.rollback(); raise
