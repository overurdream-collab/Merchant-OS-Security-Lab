from .database import get_connection


def merchant_snapshot(merchant_id):
    with get_connection() as db:
        merchant = db.execute("SELECT * FROM merchants WHERE merchant_id=?", (merchant_id,)).fetchone()
        if not merchant:
            return None
        products = db.execute("""
            SELECT COUNT(*) AS count FROM offers o
            JOIN products p ON p.product_id=o.product_id
            WHERE o.merchant_name=(SELECT name FROM merchants WHERE merchant_id=?)
        """, (merchant_id,)).fetchone()["count"]
        return {"merchant": dict(merchant), "active_offers": products}


def weekly_operations_snapshot():
    with get_connection() as db:
        orders = db.execute("SELECT COUNT(*) AS count, COALESCE(SUM(total),0) AS gross FROM orders").fetchone()
        deliveries = db.execute("SELECT COUNT(*) AS count FROM deliveries").fetchone()
        settlements = db.execute("SELECT COUNT(*) AS count, COALESCE(SUM(commission_amount),0) AS commission FROM settlements").fetchone()
        return {
            "orders": dict(orders),
            "deliveries": dict(deliveries),
            "settlements": dict(settlements),
        }
