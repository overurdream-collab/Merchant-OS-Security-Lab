"""Atomic, session-owned Checkout for the current YER COD commerce flow."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from . import database
from .cart_service import (
    CART_INACTIVE_DAYS,
    _cookie_token,
    _parse_time,
    _stamp,
    _token_hash,
)
from .quote_service import _money, _revision_decimal, quote_revision


class CheckoutError(RuntimeError):
    """Expected Checkout failure with a stable machine-readable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _normal_text(value: object, *, collapse: bool = True) -> str:
    if not isinstance(value, str):
        raise CheckoutError("invalid_checkout_details")
    normalized = unicodedata.normalize("NFC", value)
    normalized = " ".join(normalized.split()) if collapse else normalized.strip()
    if not normalized:
        raise CheckoutError("invalid_checkout_details")
    return normalized


def _normal_phone(value: object) -> str:
    normalized = _normal_text(value, collapse=False)
    # Normalize presentation whitespace/punctuation without claiming that the
    # phone number has been verified or changing its country-code semantics.
    return "".join(char for char in normalized if not char.isspace() and char not in "-().")


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _amount(value: object, code: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise CheckoutError(code) from None
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise CheckoutError(code)
    return amount


def _quantity(value: object, value_type: str) -> int:
    if value_type != "integer" or isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CheckoutError("invalid_quantity")
    return value


class CheckoutService:
    """Create one atomic Root Order from an active session-owned Cart.

    The service intentionally has no network or HTTP dependencies. It expects
    the request cookie header from a future trusted adapter.
    """

    def __init__(self, db_path: str | os.PathLike[str] | None = None, clock=None):
        self.db_path = db_path
        self.clock = clock

    def _now(self) -> datetime:
        value = self.clock() if self.clock is not None else datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        path = self.db_path if self.db_path is not None else database.DB_PATH
        db = sqlite3.connect(str(path), timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            # SQLite ignores attempts to enable FK enforcement inside a txn.
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=15000")
            yield db
        finally:
            db.close()

    @staticmethod
    def _fingerprint_secret() -> bytes:
        secret = os.environ.get("CHECKOUT_FINGERPRINT_SECRET")
        if secret is None or len(secret.encode("utf-8")) < 32:
            raise CheckoutError("checkout_configuration_error")
        return secret.encode("utf-8")

    @staticmethod
    def _fingerprint(secret: bytes, *, cart_id: int, quote_revision_value: str,
                     recipient_name: str, recipient_phone: str,
                     delivery_address: str, payment_method: object) -> str:
        payload = {
            "contract": "merchant-os-checkout-v1",
            "cart_id": cart_id,
            "quote_revision": quote_revision_value,
            "recipient_name": recipient_name,
            "recipient_phone": recipient_phone,
            "delivery_address": delivery_address,
            "payment_method": payment_method,
        }
        return hmac.new(secret, _canonical_json(payload), hashlib.sha256).hexdigest()

    @staticmethod
    def _key_hash(idempotency_key: object) -> str:
        if (not isinstance(idempotency_key, str) or not idempotency_key
                or len(idempotency_key) > 512):
            raise CheckoutError("idempotency_key_invalid")
        return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _result(db: sqlite3.Connection, order_id: int, *, replayed: bool) -> dict:
        order = db.execute(
            "SELECT order_id, status, total, total_minor, currency, payment_status, payment_method "
            "FROM orders WHERE order_id=?", (order_id,),
        ).fetchone()
        if order is None:
            raise CheckoutError("checkout_failed")
        merchant_orders = db.execute(
            """SELECT merchant_order_id, merchant_id, merchant_name_snapshot,
                      products_subtotal, delivery_fee, total, products_subtotal_minor,
                      delivery_fee_minor, total_minor, currency, status, payment_status
               FROM merchant_orders WHERE order_id=? ORDER BY merchant_id""",
            (order_id,),
        ).fetchall()
        return {
            "order_id": order["order_id"], "status": order["status"],
            "total": _money(Decimal(str(order["total_minor"] if order["total_minor"] is not None else order["total"]))), "currency": order["currency"],
            "payment_status": order["payment_status"], "payment_method": order["payment_method"],
            "merchant_orders": [dict(row) for row in merchant_orders],
            "replayed": replayed,
        }

    def checkout(
        self,
        cookie_header: str | None,
        *,
        idempotency_key: str,
        quote_revision_value: str,
        recipient_name: str,
        recipient_phone: str,
        delivery_address: str,
        payment_method: str = "cod",
        cart_id: int | None = None,
    ) -> dict:
        """Create a Root Order; client totals and catalog data are never accepted."""
        token = _cookie_token(cookie_header)
        if not token:
            raise CheckoutError("session_invalid")
        if cart_id is not None and (isinstance(cart_id, bool) or not isinstance(cart_id, int) or cart_id <= 0):
            raise CheckoutError("cart_not_found")
        key_hash = self._key_hash(idempotency_key)
        token_hash = _token_hash(token)
        now = self._now()
        now_s = _stamp(now)

        try:
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    session = db.execute(
                        "SELECT session_id, expires_at FROM sessions "
                        "WHERE token_hash=? AND revoked_at IS NULL", (token_hash,),
                    ).fetchone()
                    if session is None or _parse_time(session["expires_at"]) <= now:
                        raise CheckoutError("session_invalid")
                    session_id = session["session_id"]

                    prior_key = db.execute(
                        "SELECT cart_id, request_fingerprint, order_id FROM checkout_idempotency "
                        "WHERE session_id=? AND key_hash=?", (session_id, key_hash),
                    ).fetchone()
                    target_cart_id = cart_id if cart_id is not None else (
                        prior_key["cart_id"] if prior_key is not None else None
                    )
                    if target_cart_id is None:
                        cart = db.execute(
                            "SELECT * FROM carts WHERE session_id=? AND status='active'",
                            (session_id,),
                        ).fetchone()
                    else:
                        # Scope the lookup by the authenticated session, regardless
                        # of whether the browser supplied the cart ID.
                        cart = db.execute(
                            "SELECT * FROM carts WHERE cart_id=? AND session_id=?",
                            (target_cart_id, session_id),
                        ).fetchone()
                    if cart is None:
                        # After a successful Checkout there is no active Cart.
                        # Resolve the latest already-checked-out Cart for this
                        # authenticated session so a new key can be compared
                        # against its stored request fingerprint without
                        # trusting a browser-supplied cart ID.
                        if target_cart_id is None:
                            cart = db.execute(
                                "SELECT * FROM carts WHERE session_id=? AND status='checked_out' "
                                "ORDER BY checked_out_at DESC, cart_id DESC LIMIT 1",
                                (session_id,),
                            ).fetchone()
                        if cart is None:
                            raise CheckoutError("cart_not_found")
                    if prior_key is not None and cart_id is not None and cart_id != prior_key["cart_id"]:
                        raise CheckoutError("idempotency_conflict")

                    # Normalize customer-controlled details only after the
                    # session and cart ownership boundary has been established.
                    normalized_name = _normal_text(recipient_name)
                    normalized_phone = _normal_phone(recipient_phone)
                    normalized_address = _normal_text(delivery_address)
                    secret = self._fingerprint_secret()
                    fingerprint = self._fingerprint(
                        secret, cart_id=cart["cart_id"], quote_revision_value=quote_revision_value,
                        recipient_name=normalized_name, recipient_phone=normalized_phone,
                        delivery_address=normalized_address, payment_method=payment_method,
                    )
                    if prior_key is not None:
                        if not hmac.compare_digest(prior_key["request_fingerprint"], fingerprint):
                            raise CheckoutError("idempotency_conflict")
                        if (cart["status"] != "checked_out"
                                or cart["checkout_order_id"] != prior_key["order_id"]):
                            raise CheckoutError("checkout_failed")
                        db.execute(
                            "UPDATE sessions SET last_seen_at=?, expires_at=? WHERE session_id=?",
                            (now_s, _stamp(now + timedelta(days=30)), session_id),
                        )
                        result = self._result(db, prior_key["order_id"], replayed=True)
                        db.commit()
                        return result

                    if cart["status"] == "checked_out" or cart["checkout_order_id"] is not None:
                        prior_cart = db.execute(
                            "SELECT request_fingerprint, order_id FROM checkout_idempotency WHERE cart_id=?",
                            (cart["cart_id"],),
                        ).fetchone()
                        if prior_cart is not None:
                            if not hmac.compare_digest(prior_cart["request_fingerprint"], fingerprint):
                                raise CheckoutError("already_checked_out_conflict")
                            if cart["checkout_order_id"] != prior_cart["order_id"]:
                                raise CheckoutError("checkout_failed")
                            result = self._result(db, prior_cart["order_id"], replayed=True)
                            db.commit()
                            return result
                        raise CheckoutError("already_checked_out_conflict")

                    if cart["status"] != "active":
                        if cart["status"] == "expired":
                            raise CheckoutError("cart_expired")
                        raise CheckoutError("cart_not_found")
                    try:
                        if _parse_time(cart["updated_at"]) + timedelta(days=CART_INACTIVE_DAYS) <= now:
                            raise CheckoutError("cart_expired")
                    except ValueError:
                        raise CheckoutError("cart_expired") from None

                    # Refresh rolling session lifetime in the same transaction.
                    db.execute(
                        "UPDATE sessions SET last_seen_at=?, expires_at=? WHERE session_id=?",
                        (now_s, _stamp(now + timedelta(days=30)), session_id),
                    )
                    if cart["currency"] != "YER":
                        raise CheckoutError("unsupported_currency")
                    zone_id = cart["delivery_zone_id"]
                    if zone_id is None:
                        raise CheckoutError("delivery_zone_unavailable")
                    zone_row = db.execute(
                        "SELECT zone_id, zone_code, city_name, display_name, active "
                        "FROM delivery_zones WHERE zone_id=?", (zone_id,),
                    ).fetchone()
                    if zone_row is None or zone_row["active"] != 1:
                        raise CheckoutError("delivery_zone_unavailable")
                    revision_zone = {
                        "zone_id": zone_row["zone_id"], "zone_code": zone_row["zone_code"],
                        "city_name": zone_row["city_name"], "display_name": zone_row["display_name"],
                        "active": zone_row["active"],
                    }

                    rows = db.execute(
                        """SELECT i.offer_id, i.quantity, typeof(i.quantity) AS quantity_type,
                                  o.product_id, o.merchant_id, o.price, o.price_minor, o.currency,
                                  o.active AS offer_active, o.inventory_managed, o.stock,
                                  typeof(o.stock) AS stock_type,
                                  p.name AS product_name, p.sku, p.active AS product_active,
                                  m.name AS merchant_name, m.status AS merchant_status
                           FROM cart_items i
                           LEFT JOIN offers o ON o.offer_id=i.offer_id
                           LEFT JOIN products p ON p.product_id=o.product_id
                           LEFT JOIN merchants m ON m.merchant_id=o.merchant_id
                           WHERE i.cart_id=? ORDER BY o.merchant_id, i.offer_id""",
                        (cart["cart_id"],),
                    ).fetchall()
                    if not rows:
                        raise CheckoutError("cart_empty")

                    groups: dict[int, dict] = {}
                    revision_items: list[dict] = []
                    for row in rows:
                        quantity = _quantity(row["quantity"], row["quantity_type"])
                        if (row["product_id"] is None or row["merchant_id"] is None
                                or row["offer_active"] != 1 or row["product_active"] != 1
                                or row["merchant_status"] != "active"
                                or row["inventory_managed"] not in (0, 1)):
                            raise CheckoutError("offer_unavailable")
                        if row["currency"] != "YER":
                            raise CheckoutError("unsupported_currency")
                        unit_price = _amount(row["price_minor"] if row["price_minor"] is not None else row["price"], "offer_unavailable")
                        revision_items.append({
                            "offer_id": row["offer_id"], "quantity": quantity,
                            "product_id": row["product_id"], "merchant_id": row["merchant_id"],
                            "unit_price": _money(unit_price), "currency": row["currency"],
                            "offer_active": row["offer_active"], "product_active": row["product_active"],
                            "merchant_status": row["merchant_status"],
                            "inventory_managed": row["inventory_managed"],
                            "stock": (_revision_decimal(row["stock"])
                                      if row["inventory_managed"] == 1 else None),
                            "stock_type": (row["stock_type"]
                                           if row["inventory_managed"] == 1 else "ignored"),
                            "product_name": row["product_name"], "sku": row["sku"],
                            "merchant_name": row["merchant_name"],
                        })
                        merchant_id = row["merchant_id"]
                        group = groups.setdefault(merchant_id, {
                            "merchant_id": merchant_id, "merchant_name": row["merchant_name"],
                            "items": [], "subtotal": Decimal("0"),
                        })
                        line_total = unit_price * quantity
                        group["subtotal"] += line_total
                        group["items"].append({
                            "offer_id": row["offer_id"], "product_id": row["product_id"],
                            "merchant_id": merchant_id, "product_name": row["product_name"],
                            "sku": row["sku"], "merchant_name": row["merchant_name"],
                            "unit_price": unit_price, "quantity": quantity,
                            "line_total": line_total, "currency": "YER",
                        })

                    revision_policies: list[dict] = []
                    for merchant_id in sorted(groups):
                        policy = db.execute(
                            """SELECT policy_id, delivery_fee, delivery_fee_minor, currency, active,
                                      merchant_receives_delivery_fee
                               FROM merchant_delivery_policies WHERE merchant_id=? AND zone_id=?""",
                            (merchant_id, zone_id),
                        ).fetchone()
                        if policy is None or policy["active"] != 1:
                            raise CheckoutError("delivery_policy_unavailable")
                        if policy["currency"] != "YER":
                            raise CheckoutError("unsupported_currency")
                        fee = _amount(policy["delivery_fee_minor"] if policy["delivery_fee_minor"] is not None else policy["delivery_fee"], "delivery_policy_unavailable")
                        group = groups[merchant_id]
                        group["delivery_fee"] = fee
                        group["total"] = group["subtotal"] + fee
                        revision_policies.append({
                            "policy_id": policy["policy_id"], "merchant_id": merchant_id,
                            "zone_id": zone_id, "delivery_fee": _money(fee),
                            "currency": policy["currency"], "active": policy["active"],
                            "merchant_receives_delivery_fee": policy["merchant_receives_delivery_fee"],
                        })

                    current_revision = quote_revision(
                        {"cart_id": cart["cart_id"], "delivery_zone_id": zone_id,
                         "currency": cart["currency"]},
                        revision_zone, revision_items, revision_policies,
                    )
                    if not isinstance(quote_revision_value, str) or not hmac.compare_digest(
                            current_revision, quote_revision_value):
                        raise CheckoutError("quote_changed")

                    if payment_method != "cod":
                        raise CheckoutError("invalid_payment_method")

                    # Validate all managed stock before creating any business rows.
                    for group in groups.values():
                        for item in group["items"]:
                            source = next(row for row in rows if row["offer_id"] == item["offer_id"])
                            if source["inventory_managed"] == 1:
                                stock = source["stock"]
                                try:
                                    stock_decimal = Decimal(str(stock))
                                except (InvalidOperation, TypeError, ValueError):
                                    raise CheckoutError("insufficient_stock") from None
                                if (stock is None or not stock_decimal.is_finite() or stock_decimal < 0
                                        or stock_decimal != stock_decimal.to_integral_value()
                                        or stock_decimal < item["quantity"]):
                                    raise CheckoutError("insufficient_stock")

                    fingerprint = self._fingerprint(
                        secret, cart_id=cart["cart_id"], quote_revision_value=quote_revision_value,
                        recipient_name=normalized_name, recipient_phone=normalized_phone,
                        delivery_address=normalized_address, payment_method=payment_method,
                    )

                    customer_cursor = db.execute(
                        """INSERT INTO customers
                           (wa_id, name, phone, first_seen_at, last_seen_at, metadata)
                           VALUES (NULL, ?, ?, ?, ?, NULL)""",
                        (normalized_name, normalized_phone, now_s, now_s),
                    )
                    customer_id = customer_cursor.lastrowid
                    product_total = sum((group["subtotal"] for group in groups.values()), Decimal("0"))
                    delivery_total = sum((group["delivery_fee"] for group in groups.values()), Decimal("0"))
                    grand_total = product_total + delivery_total
                    root_cursor = db.execute(
                        """INSERT INTO orders
                            (customer_id, status, total, currency, delivery_address, payment_status,
                            created_at, updated_at, recipient_name_snapshot,
                            recipient_phone_snapshot, payment_method, total_minor)
                           VALUES (?, 'pending', ?, 'YER', ?, 'unpaid', ?, ?, ?, ?, 'cod', ?)""",
                        (customer_id, float(grand_total), normalized_address, now_s, now_s,
                         normalized_name, normalized_phone, int(grand_total)),
                    )
                    order_id = root_cursor.lastrowid

                    for merchant_id in sorted(groups):
                        group = groups[merchant_id]
                        merchant_cursor = db.execute(
                            """INSERT INTO merchant_orders
                               (order_id, merchant_id, merchant_name_snapshot, products_subtotal,
                               delivery_fee, total, currency, status, payment_status,
                                products_subtotal_minor, delivery_fee_minor, total_minor,
                                merchant_receives_delivery_fee,
                                delivery_zone_id, delivery_zone_snapshot,
                                created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, 'YER', 'pending', 'unpaid', ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (order_id, merchant_id, group["merchant_name"],
                             float(group["subtotal"]), float(group["delivery_fee"]),
                             float(group["total"]), int(group["subtotal"]), int(group["delivery_fee"]),
                             int(group["total"]), int(next(p["merchant_receives_delivery_fee"] for p in revision_policies if p["merchant_id"] == merchant_id)),
                             zone_id, f'{zone_row["zone_code"]}|{zone_row["city_name"]}|{zone_row["display_name"]}', now_s, now_s),
                        )
                        merchant_order_id = merchant_cursor.lastrowid
                        for item in group["items"]:
                            db.execute(
                                """INSERT INTO order_items
                                   (order_id, product_id, quantity, unit_price, offer_id, merchant_id,
                                    currency, line_total, product_name_snapshot, sku_snapshot,
                                    merchant_name_snapshot, merchant_order_id, unit_price_minor, line_total_minor)
                                   VALUES (?, ?, ?, ?, ?, ?, 'YER', ?, ?, ?, ?, ?, ?, ?)""",
                                (order_id, item["product_id"], item["quantity"],
                                 float(item["unit_price"]), item["offer_id"], merchant_id,
                                 float(item["line_total"]), item["product_name"], item["sku"],
                                 group["merchant_name"], merchant_order_id, int(item["unit_price"]),
                                 int(item["line_total"])),
                            )
                            item["order_item_id"] = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                        fulfillment_cursor = db.execute(
                            """INSERT INTO fulfillments
                               (merchant_order_id, fulfillment_number, status, created_at, updated_at)
                               VALUES (?, 1, 'pending', ?, ?)""",
                            (merchant_order_id, now_s, now_s),
                        )
                        db.execute("INSERT INTO commerce_events(event_type,actor_type,entity_type,entity_id,dedupe_key,created_at) VALUES('FULFILLMENT_CREATED','SYSTEM','fulfillment',?,?,?)",
                                   (fulfillment_cursor.lastrowid, f"checkout-fulfillment:{fulfillment_cursor.lastrowid}", now_s))
                        for item in group["items"]:
                            db.execute("INSERT INTO fulfillment_items(fulfillment_id,order_item_id,quantity,created_at) VALUES(?,?,?,?)",
                                       (fulfillment_cursor.lastrowid, item["order_item_id"], item["quantity"], now_s))

                    for group in groups.values():
                        for item in group["items"]:
                            source = next(row for row in rows if row["offer_id"] == item["offer_id"])
                            if source["inventory_managed"] == 1:
                                stock = source["stock"]
                                changed = db.execute(
                                    """UPDATE offers SET stock=stock-?
                                       WHERE offer_id=? AND inventory_managed=1
                                         AND stock IS NOT NULL AND stock>=? AND stock=?""",
                                    (item["quantity"], item["offer_id"], item["quantity"], stock),
                                )
                                if changed.rowcount != 1:
                                    raise CheckoutError("insufficient_stock")
                                db.execute("INSERT INTO inventory_movements(order_item_id,offer_id,movement_type,quantity,dedupe_key,created_at) VALUES(?,?,'STOCK_DECREMENTED',?,?,?)",
                                           (item["order_item_id"], item["offer_id"], item["quantity"], f"checkout:{item['order_item_id']}", now_s))

                    db.execute(
                        """INSERT INTO checkout_idempotency
                           (session_id, cart_id, key_hash, request_fingerprint,
                            quote_revision, order_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (session_id, cart["cart_id"], key_hash, fingerprint,
                         quote_revision_value, order_id, now_s),
                    )
                    changed = db.execute(
                        """UPDATE carts SET status='checked_out', checked_out_at=?,
                                  checkout_order_id=?, updated_at=?
                           WHERE cart_id=? AND session_id=? AND status='active'""",
                        (now_s, order_id, now_s, cart["cart_id"], session_id),
                    )
                    if changed.rowcount != 1:
                        raise CheckoutError("cart_requires_update")
                    db.execute(
                        "INSERT INTO order_events(order_id, status, note, created_at) "
                        "VALUES (?, 'pending', 'Order created', ?)",
                        (order_id, now_s),
                    )
                    db.execute("INSERT INTO commerce_events(event_type,actor_type,entity_type,entity_id,dedupe_key,created_at) VALUES('ORDER_CREATED','SYSTEM','order',?,?,?)",
                               (order_id, f"checkout-order:{order_id}", now_s))
                    result = self._result(db, order_id, replayed=False)
                    db.commit()
                    return result
                except CheckoutError:
                    if db.in_transaction:
                        db.rollback()
                    raise
                except sqlite3.OperationalError as exc:
                    if db.in_transaction:
                        db.rollback()
                    message = str(exc).lower()
                    if "locked" in message or "busy" in message:
                        raise CheckoutError("database_busy") from None
                    raise CheckoutError("checkout_failed") from None
                except sqlite3.Error:
                    if db.in_transaction:
                        db.rollback()
                    raise CheckoutError("checkout_failed") from None
                except Exception:
                    if db.in_transaction:
                        db.rollback()
                    raise CheckoutError("checkout_failed") from None
        except CheckoutError:
            raise
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise CheckoutError("database_busy") from None
            raise CheckoutError("checkout_failed") from None
        except sqlite3.Error:
            raise CheckoutError("checkout_failed") from None
