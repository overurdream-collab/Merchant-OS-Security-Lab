import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch

from src.merchant_os import catalog, database, merchants, operations, orders
from src.merchant_os.actors import VerifiedIdentityContext
from src.merchant_os.cart_service import CartService
from src.merchant_os.cancellation_service import CancellationService
from src.merchant_os.checkout_service import CheckoutService
from src.merchant_os.commerce_errors import CommerceError, IdentityRequired
from src.merchant_os.delivery_service import DeliveryService
from src.merchant_os.migrations import apply_migrations
from src.merchant_os.order_lifecycle import transition_merchant_order
from src.merchant_os.quote_service import QuoteService
from src.merchant_os.settlement_service import SettlementService


class _Verifier:
    def verify(self, context, action, resource): return True


class TestPhaseAServices(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=os.path.join(self.tmp.name,"phasea.sqlite")
        self.old=database.DB_PATH; database.DB_PATH=self.path
        database.ensure_schema(); merchants.ensure_merchant_schema(); catalog.ensure_catalog_schema(); orders.ensure_order_schema(); operations.ensure_operations_schema()
        apply_migrations(self.path)
        self.clock=lambda:datetime(2026,9,24,tzinfo=timezone.utc)
        self.cart=CartService(self.path,clock=self.clock); self.quote=QuoteService(self.path,clock=self.clock); self.checkout=CheckoutService(self.path,clock=self.clock)
        with closing(database.get_connection()) as db:
            self.zone=db.execute("INSERT INTO delivery_zones(zone_code,city_name,display_name) VALUES(?,?,?)",("Z-"+str(uuid.uuid4()),"Sanaa","Sanaa")).lastrowid; db.commit()
        self.actor=VerifiedIdentityContext("ADMIN","admin:1","verified-test","test-authority",self.clock().isoformat())
    def tearDown(self): database.DB_PATH=self.old; self.tmp.cleanup()

    def prepare(self, *, stock=3, merchant_count=1):
        access=self.cart.get_or_create_session(); cookie=access.set_cookie.split(";",1)[0]
        cart=self.cart.get_cart(cookie); self.cart.set_delivery_zone(cookie,self.zone,cart_id=cart["cart_id"])
        offers=[]
        for n in range(merchant_count):
            mid=merchants.create_merchant(f"Merchant {n}")
            with closing(database.get_connection()) as db: db.execute("UPDATE merchants SET status='active' WHERE merchant_id=?",(mid,)); db.commit()
            pid=catalog.create_product(f"Product {n}",sku=f"SKU-{uuid.uuid4()}")
            oid=catalog.add_offer(pid,mid,100,stock=stock,inventory_managed=1)
            with closing(database.get_connection()) as db:
                db.execute("INSERT INTO merchant_delivery_policies(merchant_id,zone_id,delivery_fee,delivery_fee_minor,currency,updated_at) VALUES(?,?,5,5,'YER',?)",(mid,self.zone,self.clock().isoformat())); db.commit()
            self.cart.add_item(cookie,oid,1); offers.append((mid,pid,oid))
        revision=self.quote.quote(cookie)["quote_revision"]
        with patch.dict(os.environ,{"CHECKOUT_FINGERPRINT_SECRET":"test-secret-for-phase-a-32-characters"}):
            result=self.checkout.checkout(cookie,idempotency_key="checkout-key",quote_revision_value=revision,recipient_name="Guest",recipient_phone="967700000000",delivery_address="Sanaa",payment_method="cod")
        return cookie,result,offers

    def test_managed_stock_restored_once_on_cancellation(self):
        _,result,offers=self.prepare(stock=2); offer=offers[0][2]
        service=CancellationService(identity_verifier=_Verifier())
        mid=result["merchant_orders"][0]["merchant_order_id"]
        self.assertEqual(service.cancel_merchant_order(mid,actor=self.actor)["status"],"cancelled")
        self.assertEqual(service.cancel_merchant_order(mid,actor=self.actor)["status"],"cancelled")
        with closing(database.get_connection()) as db:
            self.assertEqual(db.execute("SELECT stock FROM offers WHERE offer_id=?",(offer,)).fetchone()[0],2)
            self.assertEqual([tuple(r) for r in db.execute("SELECT movement_type,quantity FROM inventory_movements ORDER BY movement_id").fetchall()],[ ("STOCK_DECREMENTED",1),("STOCK_RESTORED",1)])

    def test_concurrent_duplicate_cancellation_restores_stock_once(self):
        _,result,offers=self.prepare(stock=4); offer=offers[0][2]; mid=result["merchant_orders"][0]["merchant_order_id"]
        service=CancellationService(identity_verifier=_Verifier())
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda _: service.cancel_merchant_order(mid,actor=self.actor)["status"],range(2)))
        self.assertEqual(outcomes,["cancelled","cancelled"])
        with closing(database.get_connection()) as db:
            self.assertEqual(db.execute("SELECT stock FROM offers WHERE offer_id=?",(offer,)).fetchone()[0],4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inventory_movements WHERE movement_type='STOCK_RESTORED'").fetchone()[0],1)

    def test_cancellation_fails_closed_without_verified_actor(self):
        _,result,_=self.prepare(); service=CancellationService(identity_verifier=None)
        with self.assertRaises(IdentityRequired): service.cancel_merchant_order(result["merchant_orders"][0]["merchant_order_id"],actor=None)

    def test_merchant_cannot_cancel_another_merchants_order(self):
        _,result,offers=self.prepare(stock=3,merchant_count=2)
        foreign_merchant=offers[1][0]; target=result["merchant_orders"][0]["merchant_order_id"]
        actor=VerifiedIdentityContext("MERCHANT",str(foreign_merchant),"verified-test","test-authority",self.clock().isoformat())
        with self.assertRaises(CommerceError) as caught: CancellationService(identity_verifier=_Verifier()).cancel_merchant_order(target,actor=actor)
        self.assertEqual(caught.exception.code,"FORBIDDEN")

    def test_order_state_machine_rejects_skip_and_advances_root(self):
        _,result,_=self.prepare(); mo=result["merchant_orders"][0]["merchant_order_id"]
        with self.assertRaises(CommerceError) as caught: transition_merchant_order(mo,"completed",actor=self.actor,verifier=_Verifier())
        self.assertEqual(caught.exception.code,"INVALID_STATE_TRANSITION")
        transition_merchant_order(mo,"confirmed",actor=self.actor,verifier=_Verifier())
        transition_merchant_order(mo,"processing",actor=self.actor,verifier=_Verifier())
        with closing(database.get_connection()) as db: self.assertEqual(db.execute("SELECT status FROM orders WHERE order_id=?",(result["order_id"],)).fetchone()[0],"processing")

    def test_root_cancellation_is_atomic_and_partial_by_merchant(self):
        _,result,_=self.prepare(stock=2,merchant_count=2); mids=[x["merchant_order_id"] for x in result["merchant_orders"]]
        service=CancellationService(identity_verifier=_Verifier()); service.cancel_merchant_order(mids[0],actor=self.actor)
        with closing(database.get_connection()) as db: self.assertEqual(db.execute("SELECT status FROM orders WHERE order_id=?",(result["order_id"],)).fetchone()[0],"partially_cancelled")
        root=service.cancel_root_order(result["order_id"],actor=self.actor)
        self.assertEqual(root["status"],"cancelled")

    def test_settlement_uses_integer_order_snapshots_and_trusted_policy(self):
        _,result,_=self.prepare(); mo=result["merchant_orders"][0]["merchant_order_id"]
        service=SettlementService(identity_verifier=_Verifier(),commission_policy=lambda merchant_id:1000)
        settlement=service.create(mo,actor=self.actor)
        self.assertEqual(settlement["gross_amount_minor"],100)
        self.assertEqual(settlement["commission_amount_minor"],10)
        self.assertEqual(settlement["merchant_amount_minor"],90)
        self.assertEqual(service.create(mo,actor=self.actor)["settlement_id"],settlement["settlement_id"])

    def test_settlement_without_trusted_commission_policy_fails_closed(self):
        _,result,_=self.prepare(); mo=result["merchant_orders"][0]["merchant_order_id"]
        with self.assertRaises(CommerceError): SettlementService(identity_verifier=_Verifier(),commission_policy=None).create(mo,actor=self.actor)

    def test_delivery_is_fulfillment_bound_and_snapshots_address(self):
        _,result,_=self.prepare(); mo=result["merchant_orders"][0]["merchant_order_id"]
        transition_merchant_order(mo,"confirmed",actor=self.actor,verifier=_Verifier())
        transition_merchant_order(mo,"processing",actor=self.actor,verifier=_Verifier())
        transition_merchant_order(mo,"ready",actor=self.actor,verifier=_Verifier())
        with closing(database.get_connection()) as db: fid=db.execute("SELECT fulfillment_id FROM fulfillments WHERE merchant_order_id=?",(mo,)).fetchone()[0]
        delivery=DeliveryService(identity_verifier=_Verifier()); row=delivery.create_for_fulfillment(fid,actor=self.actor,idempotency_key="delivery-1")
        self.assertEqual(row["fulfillment_id"],fid); self.assertEqual(row["delivery_address_snapshot"],"Sanaa")
        delivery.transition(row["delivery_id"],"assigned",actor=self.actor)
        delivery.transition(row["delivery_id"],"out_for_delivery",actor=self.actor)
        self.assertEqual(delivery.transition(row["delivery_id"],"delivered",actor=self.actor)["status"],"delivered")
        self.assertEqual(delivery.create_for_fulfillment(fid,actor=self.actor,idempotency_key="delivery-1")["delivery_id"],row["delivery_id"])

    def test_offer_money_rejects_fractional_yer(self):
        mid=merchants.create_merchant("Seller")
        pid=catalog.create_product("Part")
        with self.assertRaisesRegex(ValueError,"integer_yer"):
            catalog.add_offer(pid,mid,1.5)


if __name__=="__main__": unittest.main()
