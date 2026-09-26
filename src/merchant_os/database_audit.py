"""Read-only schema and relationship audit for the legacy SQLite database."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .migrations import MigrationError, migration_status


CORE_TABLES = (
    "customers", "merchants", "products", "offers", "orders", "order_items",
    "order_events", "deliveries", "settlements", "returns", "conversations",
    "messages", "customer_messages", "merchant_contacts", "merchant_scores",
    "outreach", "webhook_events", "whatsapp_statuses",
)


def _connect_readonly(path: str | os.PathLike[str]) -> sqlite3.Connection:
    absolute = Path(path).resolve()
    db = sqlite3.connect(absolute.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def audit_database(path: str | os.PathLike[str]) -> dict:
    """Inspect a database without writing to it; ambiguous legacy links are reported."""
    absolute = str(Path(path).resolve())
    db = _connect_readonly(path)
    try:
        table_names = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        user_version = db.execute("PRAGMA user_version").fetchone()[0]
        try:
            history = migration_status(db)
            migration_error = None
        except MigrationError as exc:
            history = []
            migration_error = str(exc)

        counts = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in sorted(table_names)
        }
        missing_core_tables = [table for table in CORE_TABLES if table not in table_names]
        fk_violations = [dict(row) for row in db.execute("PRAGMA foreign_key_check")]
        orphans: list[dict] = []
        warnings: list[dict] = []

        def orphan(label: str, sql: str, params: tuple = ()) -> None:
            if sql.split()[0].upper() == "SELECT":
                rows = [dict(row) for row in db.execute(sql, params)]
                if rows:
                    orphans.append({"relationship": label, "count": len(rows), "rows": rows})

        def has(*tables: str) -> bool:
            return all(table in table_names for table in tables)

        if has("offers", "products"):
            orphan("offers without product", """
                SELECT o.offer_id, o.product_id FROM offers o
                LEFT JOIN products p ON p.product_id=o.product_id WHERE p.product_id IS NULL
            """)
            cols = {row[1] for row in db.execute("PRAGMA table_info(offers)")}
            merchant_col = "merchant_id" if "merchant_id" in cols else None
            if merchant_col and has("merchants"):
                orphan("offers without merchant", """
                    SELECT o.offer_id, o.merchant_id, o.merchant_name FROM offers o
                    LEFT JOIN merchants m ON m.merchant_id=o.merchant_id
                    WHERE o.merchant_id IS NULL OR m.merchant_id IS NULL
                """)
                unlinked = [dict(row) for row in db.execute("""
                    SELECT o.offer_id, o.merchant_name, COUNT(m.merchant_id) AS exact_name_matches
                    FROM offers o LEFT JOIN merchants m ON m.name=o.merchant_name
                    WHERE o.merchant_id IS NULL
                    GROUP BY o.offer_id, o.merchant_name
                """)]
                if unlinked:
                    warnings.append({"relationship": "unlinked offers; exact-name matches are candidates only", "count": len(unlinked), "rows": unlinked})
            elif "merchant_name" in cols and has("merchants"):
                unmatched = [dict(row) for row in db.execute("""
                    SELECT o.offer_id, o.merchant_name FROM offers o
                    WHERE NOT EXISTS (SELECT 1 FROM merchants m WHERE m.name=o.merchant_name)
                """)]
                ambiguous = [dict(row) for row in db.execute("""
                    SELECT o.offer_id, o.merchant_name, COUNT(m.merchant_id) AS matching_merchants
                    FROM offers o JOIN merchants m ON m.name=o.merchant_name
                    GROUP BY o.offer_id, o.merchant_name HAVING COUNT(m.merchant_id) > 1
                """)]
                if unmatched:
                    warnings.append({"relationship": "offers with no exact merchant-name match", "count": len(unmatched), "rows": unmatched})
                if ambiguous:
                    warnings.append({"relationship": "offers with ambiguous merchant-name match", "count": len(ambiguous), "rows": ambiguous})
            elif "merchant_name" in cols:
                orphan("offers with blank merchant name", """
                    SELECT offer_id, merchant_name FROM offers
                    WHERE merchant_name IS NULL OR TRIM(merchant_name)=''
                """)

        if has("orders", "customers"):
            orphan("orders without customer", """
                SELECT o.order_id, o.customer_id FROM orders o
                LEFT JOIN customers c ON c.customer_id=o.customer_id WHERE c.customer_id IS NULL
            """)
        if has("order_items", "orders"):
            orphan("order items without order", """
                SELECT i.order_item_id, i.order_id FROM order_items i
                LEFT JOIN orders o ON o.order_id=i.order_id WHERE o.order_id IS NULL
            """)
        if has("order_items", "products"):
            orphan("order items without product", """
                SELECT i.order_item_id, i.product_id FROM order_items i
                LEFT JOIN products p ON p.product_id=i.product_id WHERE p.product_id IS NULL
            """)
        if has("deliveries", "orders"):
            orphan("deliveries without order", """
                SELECT d.delivery_id, d.order_id FROM deliveries d
                LEFT JOIN orders o ON o.order_id=d.order_id WHERE d.order_id IS NULL OR o.order_id IS NULL
            """)
        if has("settlements", "orders"):
            orphan("settlements without order", """
                SELECT s.settlement_id, s.order_id FROM settlements s
                LEFT JOIN orders o ON o.order_id=s.order_id WHERE s.order_id IS NULL OR o.order_id IS NULL
            """)
            if has("merchants"):
                unmatched = [dict(row) for row in db.execute("""
                    SELECT s.settlement_id, s.merchant_name, s.order_id FROM settlements s
                    WHERE NOT EXISTS (SELECT 1 FROM merchants m WHERE m.name=s.merchant_name)
                """)]
                if unmatched:
                    warnings.append({"relationship": "settlements with no exact merchant-name match", "count": len(unmatched), "rows": unmatched})
        if has("returns", "orders"):
            orphan("returns without order", """
                SELECT r.return_id, r.order_id FROM returns r
                LEFT JOIN orders o ON o.order_id=r.order_id WHERE r.order_id IS NULL OR o.order_id IS NULL
            """)
        if has("order_events", "orders"):
            orphan("order events without order", """
                SELECT e.event_id, e.order_id FROM order_events e
                LEFT JOIN orders o ON o.order_id=e.order_id WHERE e.order_id IS NULL OR o.order_id IS NULL
            """)

        if has("sessions", "customers"):
            orphan("sessions with missing customer", """
                SELECT s.session_id, s.customer_id FROM sessions s
                LEFT JOIN customers c ON c.customer_id=s.customer_id
                WHERE s.customer_id IS NOT NULL AND c.customer_id IS NULL
            """)
        if has("carts", "sessions"):
            orphan("carts without session", """
                SELECT ca.cart_id, ca.session_id FROM carts ca
                LEFT JOIN sessions s ON s.session_id=ca.session_id
                WHERE s.session_id IS NULL
            """)
        if has("carts", "customers"):
            orphan("carts with missing customer", """
                SELECT ca.cart_id, ca.customer_id FROM carts ca
                LEFT JOIN customers c ON c.customer_id=ca.customer_id
                WHERE ca.customer_id IS NOT NULL AND c.customer_id IS NULL
            """)
        if has("carts", "delivery_zones"):
            orphan("carts with missing delivery zone", """
                SELECT ca.cart_id, ca.delivery_zone_id FROM carts ca
                LEFT JOIN delivery_zones z ON z.zone_id=ca.delivery_zone_id
                WHERE ca.delivery_zone_id IS NOT NULL AND z.zone_id IS NULL
            """)
        if has("carts"):
            orphan("carts with missing merge target", """
                SELECT ca.cart_id, ca.merged_into_cart_id FROM carts ca
                LEFT JOIN carts target ON target.cart_id=ca.merged_into_cart_id
                WHERE ca.merged_into_cart_id IS NOT NULL AND target.cart_id IS NULL
            """)
        if has("carts", "orders"):
            orphan("carts with missing checkout order", """
                SELECT ca.cart_id, ca.checkout_order_id FROM carts ca
                LEFT JOIN orders o ON o.order_id=ca.checkout_order_id
                WHERE ca.checkout_order_id IS NOT NULL AND o.order_id IS NULL
            """)
        if has("cart_items", "carts"):
            orphan("cart items without cart", """
                SELECT i.cart_item_id, i.cart_id FROM cart_items i
                LEFT JOIN carts ca ON ca.cart_id=i.cart_id WHERE ca.cart_id IS NULL
            """)
        if has("cart_items", "offers"):
            orphan("cart items without offer", """
                SELECT i.cart_item_id, i.offer_id FROM cart_items i
                LEFT JOIN offers o ON o.offer_id=i.offer_id WHERE o.offer_id IS NULL
            """)
        if has("merchant_delivery_policies", "merchants"):
            orphan("delivery policies without merchant", """
                SELECT p.policy_id, p.merchant_id FROM merchant_delivery_policies p
                LEFT JOIN merchants m ON m.merchant_id=p.merchant_id WHERE m.merchant_id IS NULL
            """)
        if has("merchant_delivery_policies", "delivery_zones"):
            orphan("delivery policies without zone", """
                SELECT p.policy_id, p.zone_id FROM merchant_delivery_policies p
                LEFT JOIN delivery_zones z ON z.zone_id=p.zone_id WHERE z.zone_id IS NULL
            """)

        if "money_migration_issues" in table_names:
            issues = [dict(row) for row in db.execute(
                "SELECT table_name,row_id,legacy_column,legacy_value,reason FROM money_migration_issues ORDER BY table_name,row_id,legacy_column"
            )]
            if issues:
                warnings.append({"relationship": "legacy money values require manual integer-YER review", "count": len(issues), "rows": issues})
        if has("inventory_movements", "order_items", "offers"):
            orphan("inventory movements inconsistent with order item/offer", """
                SELECT im.movement_id,im.order_item_id,im.offer_id FROM inventory_movements im
                LEFT JOIN order_items oi ON oi.order_item_id=im.order_item_id AND oi.offer_id=im.offer_id
                WHERE oi.order_item_id IS NULL
            """)
        if has("fulfillment_items", "fulfillments", "order_items"):
            orphan("fulfillment items outside merchant order", """
                SELECT fi.fulfillment_item_id,fi.fulfillment_id,fi.order_item_id
                FROM fulfillment_items fi JOIN fulfillments f ON f.fulfillment_id=fi.fulfillment_id
                LEFT JOIN order_items oi ON oi.order_item_id=fi.order_item_id AND oi.merchant_order_id=f.merchant_order_id
                WHERE oi.order_item_id IS NULL
            """)
        if has("delivery_items", "deliveries", "fulfillment_items"):
            orphan("delivery items cross fulfillment", """
                SELECT di.delivery_item_id,di.delivery_id,di.fulfillment_item_id
                FROM delivery_items di JOIN deliveries d ON d.delivery_id=di.delivery_id
                LEFT JOIN fulfillment_items fi ON fi.fulfillment_item_id=di.fulfillment_item_id AND fi.fulfillment_id=d.fulfillment_id
                WHERE fi.fulfillment_item_id IS NULL
            """)
        if has("deliveries", "fulfillments", "merchant_orders"):
            orphan("delivery fulfillment/order mismatch", """
                SELECT d.delivery_id,d.order_id,d.fulfillment_id FROM deliveries d
                JOIN fulfillments f ON f.fulfillment_id=d.fulfillment_id
                JOIN merchant_orders mo ON mo.merchant_order_id=f.merchant_order_id
                WHERE mo.order_id<>d.order_id
            """)
        if has("settlements", "merchant_orders"):
            orphan("settlement merchant order mismatch", """
                SELECT s.settlement_id,s.order_id,s.merchant_order_id FROM settlements s
                JOIN merchant_orders mo ON mo.merchant_order_id=s.merchant_order_id
                WHERE mo.order_id<>s.order_id
            """)

        if missing_core_tables:
            warnings.append({"relationship": "missing expected core tables", "count": len(missing_core_tables), "rows": missing_core_tables})
        if migration_error:
            warnings.append({"relationship": "migration metadata inconsistency", "count": 1, "rows": [migration_error]})

        return {
            "database_path": absolute,
            "user_version": user_version,
            "migration_history": history,
            "migration_error": migration_error,
            "row_counts": counts,
            "missing_core_tables": missing_core_tables,
            "foreign_key_violations": fk_violations,
            "orphaned_records": orphans,
            "ambiguous_or_suspicious_links": warnings,
        }
    finally:
        db.close()
