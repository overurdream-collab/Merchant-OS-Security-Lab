"""Merchant-order settlements derived only from immutable order snapshots."""
from datetime import datetime, timezone
from . import database
from .actors import require_actor
from .commerce_errors import CommerceError

TRANSITIONS={"pending":{"due"},"due":{"confirmed","reversed"},"confirmed":{"paid","reversed"},"paid":set(),"reversed":set()}
def _now(): return datetime.now(timezone.utc).isoformat()

class SettlementService:
    def __init__(self, *, identity_verifier, commission_policy):
        self.identity_verifier=identity_verifier; self.commission_policy=commission_policy
    def create(self, merchant_order_id, *, actor):
        actor=require_actor(actor,self.identity_verifier,"settlement.create",{"merchant_order_id":merchant_order_id})
        if self.commission_policy is None: raise CommerceError("SETTLEMENT_INVALID",detail="commission_policy_missing")
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON"); db.execute("BEGIN IMMEDIATE")
            try:
                mo=db.execute("SELECT * FROM merchant_orders WHERE merchant_order_id=?",(merchant_order_id,)).fetchone()
                if mo is None: raise CommerceError("ORDER_NOT_FOUND")
                if actor.actor_type == "CUSTOMER" or (actor.actor_type == "MERCHANT" and actor.actor_ref != str(mo["merchant_id"])): raise CommerceError("FORBIDDEN")
                existing=db.execute("SELECT * FROM settlements WHERE merchant_order_id=?",(merchant_order_id,)).fetchone()
                if existing: db.commit(); return dict(existing)
                # Trusted policy adapter receives the merchant ID; request data never supplies the rate.
                bps=self.commission_policy(mo["merchant_id"])
                if isinstance(bps,bool) or not isinstance(bps,int) or not 0<=bps<=10000: raise CommerceError("SETTLEMENT_INVALID")
                gross=mo["products_subtotal_minor"]
                if gross is None: raise CommerceError("SETTLEMENT_INVALID",detail="historical_minor_amount_missing")
                commission=(gross*bps)//10000
                receives=int(mo["merchant_receives_delivery_fee"])
                delivery_minor=int(mo["delivery_fee_minor"] or 0) if receives else 0
                merchant=gross-commission+delivery_minor; now=_now()
                cur=db.execute("INSERT INTO settlements(order_id,merchant_name,gross_amount,commission_amount,merchant_amount,status,created_at,merchant_order_id,currency,commission_rate_bps,merchant_receives_delivery_fee,delivery_fee_snapshot,gross_amount_minor,commission_amount_minor,merchant_amount_minor,delivery_fee_minor) VALUES(?,?,?,?,?,'pending',?,?,?,?,?,?,?,?,?,?)",(mo["order_id"],mo["merchant_name_snapshot"],mo["products_subtotal"],mo["products_subtotal"]*bps/10000,merchant,now,merchant_order_id,'YER',bps,receives,mo["delivery_fee"],gross,commission,merchant,mo["delivery_fee_minor"] or 0))
                sid=cur.lastrowid
                db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,dedupe_key,created_at) VALUES('SETTLEMENT_CREATED',?,?,?,?,?,?)",(actor.actor_type,actor.actor_ref,'settlement',sid,f'settlement-created:{merchant_order_id}',now))
                db.commit(); return dict(db.execute("SELECT * FROM settlements WHERE settlement_id=?",(sid,)).fetchone())
            except Exception: db.rollback(); raise
    def transition(self, settlement_id, target, *, actor):
        actor=require_actor(actor,self.identity_verifier,"settlement.transition",{"settlement_id":settlement_id})
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON"); db.execute("BEGIN IMMEDIATE")
            try:
                row=db.execute("SELECT * FROM settlements WHERE settlement_id=? AND merchant_order_id IS NOT NULL",(settlement_id,)).fetchone()
                if row is None: raise CommerceError("SETTLEMENT_INVALID")
                mo=db.execute("SELECT merchant_id FROM merchant_orders WHERE merchant_order_id=?",(row["merchant_order_id"],)).fetchone()
                if actor.actor_type == "CUSTOMER" or (actor.actor_type == "MERCHANT" and actor.actor_ref != str(mo[0])): raise CommerceError("FORBIDDEN")
                if target == row["status"]:
                    db.commit(); return dict(row)
                if target not in TRANSITIONS.get(row["status"],set()): raise CommerceError("INVALID_STATE_TRANSITION")
                now=_now(); db.execute("UPDATE settlements SET status=?,settled_at=CASE WHEN ?='paid' THEN ? ELSE settled_at END WHERE settlement_id=?",(target,target,now,settlement_id))
                db.execute("INSERT INTO commerce_events(event_type,actor_type,actor_ref,entity_type,entity_id,created_at) VALUES(?,?,?,?,?,?)",('SETTLEMENT_'+target.upper(),actor.actor_type,actor.actor_ref,'settlement',settlement_id,now))
                db.commit(); return dict(db.execute("SELECT * FROM settlements WHERE settlement_id=?",(settlement_id,)).fetchone())
            except Exception: db.rollback(); raise
