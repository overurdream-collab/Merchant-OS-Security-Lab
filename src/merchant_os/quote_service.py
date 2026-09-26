"""Read-only server-side cart quotes using current catalog and delivery data.

This module creates no cart, order, delivery, payment, or settlement records.
The caller must provide the session cookie; optional cart IDs are always scoped
to the session resolved from that cookie.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Iterator

from . import database
from .cart_service import (
    CART_INACTIVE_DAYS,
    SESSION_COOKIE_NAME,
    CartNotFound,
    InvalidQuantity,
    SessionInvalid,
    _parse_time,
)


class QuoteError(Exception):
    """Base class for expected quote validation errors."""


class DeliveryZoneRequired(QuoteError):
    pass


class QuoteDeliveryZoneUnavailable(QuoteError):
    pass


class DeliveryPolicyUnavailable(QuoteError):
    pass


class QuoteOfferUnavailable(QuoteError):
    pass


class QuoteCurrencyInvalid(QuoteError):
    pass


def _cookie_token(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    parsed = SimpleCookie()
    try:
        parsed.load(cookie_header)
    except Exception:
        return None
    morsel = parsed.get(SESSION_COOKIE_NAME)
    return morsel.value if morsel else None


def _decimal_amount(value: object, *, error: type[QuoteError], label: str) -> Decimal:
    try:
        # REAL is the existing storage type. Decimal avoids adding binary-float
        # error during the subsequent multiplication and summation.
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise error(label) from None
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise error(label)
    return amount


def _canonical_amount(minor: object, legacy: object, *, error: type[QuoteError], label: str) -> Decimal:
    if minor is not None:
        if isinstance(minor, bool) or not isinstance(minor, int) or minor < 0:
            raise error(label)
        return Decimal(minor)
    return _decimal_amount(legacy, error=error, label=label)


def _money(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _revision_decimal(value: object) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if number.is_finite():
        return _money(number)
    return str(number)


def quote_revision(cart: dict, zone: dict, items: list[dict], policies: list[dict]) -> str:
    """Hash canonical server-derived inputs that define this quote and eligibility."""
    canonical = {
        "contract": "merchant-os-quote-v1",
        "cart": {
            "cart_id": cart["cart_id"],
            "delivery_zone_id": cart["delivery_zone_id"],
            "currency": cart["currency"],
        },
        "zone": zone,
        "items": sorted(items, key=lambda item: (item["merchant_id"] or -1, item["offer_id"])),
        "policies": sorted(policies, key=lambda policy: (policy["merchant_id"], policy["zone_id"])),
    }
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class QuoteService:
    """Calculate an ephemeral quote from a session-owned active cart."""

    def __init__(self, db_path: str | Path | None = None, clock=None):
        self.db_path = db_path
        self.clock = clock

    def _now(self):
        value = self.clock() if self.clock is not None else datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        path = self.db_path if self.db_path is not None else database.DB_PATH
        readonly_uri = Path(path).resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(readonly_uri, uri=True, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=15000")
            yield db
        finally:
            db.close()

    def quote(self, cookie_header: str | None, *, cart_id: int | None = None) -> dict:
        """Return a current YER quote without changing persistent state."""
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = self._now()

        with self._connection() as db:
            # A single read transaction gives a consistent view across cart,
            # catalog, zone, and policy queries while keeping Quote read-only.
            db.execute("BEGIN")
            try:
                session = db.execute(
                    "SELECT session_id, expires_at FROM sessions "
                    "WHERE token_hash=? AND revoked_at IS NULL",
                    (token_hash,),
                ).fetchone()
                if session is None or _parse_time(session["expires_at"]) <= now:
                    raise SessionInvalid("session_invalid")

                if cart_id is None:
                    cart = db.execute(
                        "SELECT * FROM carts WHERE session_id=? AND status='active'",
                        (session["session_id"],),
                    ).fetchone()
                else:
                    cart = db.execute(
                        "SELECT * FROM carts WHERE cart_id=? AND session_id=? AND status='active'",
                        (cart_id, session["session_id"]),
                    ).fetchone()
                if cart is None or _parse_time(cart["updated_at"]) + timedelta(days=CART_INACTIVE_DAYS) <= now:
                    raise CartNotFound("cart_not_found")
                if cart["currency"] != "YER":
                    raise QuoteCurrencyInvalid("cart_currency_must_be_yer")
                zone_id = cart["delivery_zone_id"]
                if zone_id is None:
                    raise DeliveryZoneRequired("delivery_zone_required")
                zone = db.execute(
                    "SELECT zone_id, zone_code, city_name, display_name, active "
                    "FROM delivery_zones WHERE zone_id=?",
                    (zone_id,),
                ).fetchone()
                if zone is None or zone["active"] != 1:
                    raise QuoteDeliveryZoneUnavailable("delivery_zone_unavailable")
                revision_zone = {
                    "zone_id": zone["zone_id"], "zone_code": zone["zone_code"],
                    "city_name": zone["city_name"], "display_name": zone["display_name"],
                    "active": zone["active"],
                }

                rows = db.execute(
                    """SELECT i.cart_item_id, i.offer_id, i.quantity,
                              typeof(i.quantity) AS quantity_type,
                              o.product_id, o.merchant_id, o.price, o.price_minor, o.currency,
                              o.active AS offer_active, o.inventory_managed, o.stock,
                              typeof(o.stock) AS stock_type,
                              p.name AS product_name, p.sku, p.active AS product_active,
                              m.name AS merchant_name, m.status AS merchant_status
                       FROM cart_items i
                       LEFT JOIN offers o ON o.offer_id=i.offer_id
                       LEFT JOIN products p ON p.product_id=o.product_id
                       LEFT JOIN merchants m ON m.merchant_id=o.merchant_id
                       WHERE i.cart_id=?
                       ORDER BY o.merchant_id, p.name, i.offer_id""",
                    (cart["cart_id"],),
                ).fetchall()

                groups: dict[int, dict] = {}
                decimal_subtotals: dict[int, Decimal] = {}
                revision_items = []
                for row in rows:
                    quantity = row["quantity"]
                    if row["quantity_type"] != "integer" or isinstance(quantity, bool) or quantity <= 0:
                        raise InvalidQuantity("quantity_must_be_positive_integer")
                    if (row["product_id"] is None or row["merchant_id"] is None
                            or row["offer_active"] != 1 or row["product_active"] != 1
                            or row["merchant_status"] != "active"):
                        raise QuoteOfferUnavailable("offer_unavailable")
                    if row["currency"] != "YER":
                        raise QuoteCurrencyInvalid("offer_currency_must_be_yer")
                    price = _canonical_amount(
                        row["price_minor"], row["price"], error=QuoteOfferUnavailable, label="offer_price_invalid"
                    )
                    revision_items.append({
                        "offer_id": row["offer_id"], "quantity": quantity,
                        "product_id": row["product_id"], "merchant_id": row["merchant_id"],
                        "unit_price": _money(price), "currency": row["currency"],
                        "offer_active": row["offer_active"],
                        "product_active": row["product_active"],
                        "merchant_status": row["merchant_status"],
                        "inventory_managed": row["inventory_managed"],
                        # Stock is relevant to the revision only when the Offer
                        # explicitly manages inventory; unmanaged stock is not
                        # a purchase constraint in V1.
                        "stock": (_revision_decimal(row["stock"])
                                  if row["inventory_managed"] == 1 else None),
                        "stock_type": (row["stock_type"]
                                       if row["inventory_managed"] == 1 else "ignored"),
                        "product_name": row["product_name"], "sku": row["sku"],
                        "merchant_name": row["merchant_name"],
                    })
                    merchant_id = row["merchant_id"]
                    line_total = price * quantity
                    group = groups.setdefault(merchant_id, {
                        "merchant_id": merchant_id,
                        "merchant_name": row["merchant_name"],
                        "currency": "YER",
                        "items": [],
                    })
                    group["items"].append({
                        "cart_item_id": row["cart_item_id"],
                        "offer_id": row["offer_id"],
                        "product_id": row["product_id"],
                        "product_name": row["product_name"],
                        "sku": row["sku"],
                        "quantity": quantity,
                        "unit_price": _money(price),
                        "currency": "YER",
                        "line_total": _money(line_total),
                    })
                    decimal_subtotals[merchant_id] = decimal_subtotals.get(merchant_id, Decimal("0")) + line_total

                product_total = Decimal("0")
                delivery_total = Decimal("0")
                revision_policies = []
                for merchant_id in sorted(groups):
                    policy = db.execute(
                        """SELECT policy_id, delivery_fee, delivery_fee_minor, currency, active,
                                  merchant_receives_delivery_fee
                           FROM merchant_delivery_policies
                           WHERE merchant_id=? AND zone_id=?""",
                        (merchant_id, zone_id),
                    ).fetchone()
                    if policy is None or policy["active"] != 1:
                        raise DeliveryPolicyUnavailable("delivery_policy_unavailable")
                    if policy["currency"] != "YER":
                        raise QuoteCurrencyInvalid("delivery_policy_currency_must_be_yer")
                    fee = _canonical_amount(
                        policy["delivery_fee_minor"], policy["delivery_fee"], error=DeliveryPolicyUnavailable,
                        label="delivery_policy_fee_invalid",
                    )
                    revision_policies.append({
                        "policy_id": policy["policy_id"], "merchant_id": merchant_id,
                        "zone_id": zone_id, "delivery_fee": _money(fee),
                        "currency": policy["currency"], "active": policy["active"],
                        "merchant_receives_delivery_fee": policy["merchant_receives_delivery_fee"],
                    })
                    subtotal = decimal_subtotals[merchant_id]
                    merchant_total = subtotal + fee
                    groups[merchant_id].update({
                        "delivery_policy_id": policy["policy_id"],
                        "products_subtotal": _money(subtotal),
                        "delivery_fee": _money(fee),
                        "delivery_total": _money(fee),
                        "merchant_total": _money(merchant_total),
                    })
                    product_total += subtotal
                    delivery_total += fee

                result = {
                    "cart_id": cart["cart_id"],
                    "currency": "YER",
                    "delivery_zone": {
                        "zone_id": zone["zone_id"],
                        "zone_code": zone["zone_code"],
                        "city_name": zone["city_name"],
                        "display_name": zone["display_name"],
                    },
                    "merchant_groups": [groups[key] for key in sorted(groups)],
                    "product_total": _money(product_total),
                    "delivery_total": _money(delivery_total),
                    "grand_total": _money(product_total + delivery_total),
                    "quoted_at": now.isoformat(),
                    "quote_revision": quote_revision(
                        {"cart_id": cart["cart_id"], "delivery_zone_id": zone_id,
                         "currency": cart["currency"]},
                        revision_zone, revision_items, revision_policies,
                    ),
                }
                db.commit()
                return result
            except Exception:
                if db.in_transaction:
                    db.rollback()
                raise
