"""Session-bound guest sessions and multi-merchant cart operations.

This module is a service layer only. It does not expose HTTP routes or checkout.
Callers must send ``cookie_header`` from the request and return the supplied
Set-Cookie value in the response. Browser-provided cart/customer IDs are never
used to resolve ownership.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Iterator, Protocol

from . import database


SESSION_DAYS = 30
CART_INACTIVE_DAYS = 30
SESSION_COOKIE_NAME = "merchant_os_session"


class CartServiceError(Exception):
    """Base class for expected cart and session errors."""


class SessionInvalid(CartServiceError):
    pass


class CartNotFound(CartServiceError):
    """Used for both missing carts and carts owned by another session."""


class OfferUnavailable(CartServiceError):
    pass


class InvalidQuantity(CartServiceError):
    pass


class DeliveryZoneUnavailable(CartServiceError):
    pass


class IdentityVerificationRequired(CartServiceError):
    pass


@dataclass(frozen=True)
class VerifiedIdentityContext:
    customer_id: int
    verification_id: str
    verified_by: str
    verified_at: str

    def __post_init__(self):
        if isinstance(self.customer_id, bool) or not isinstance(self.customer_id, int) or self.customer_id <= 0:
            raise ValueError("verified_customer_id_must_be_positive_integer")
        if not all(value.strip() for value in (self.verification_id, self.verified_by, self.verified_at)):
            raise ValueError("verified_identity_context_incomplete")


class IdentityVerifier(Protocol):
    """Trusted application adapter for a future verified-identity mechanism."""

    def verify(self, context: VerifiedIdentityContext) -> bool:
        ...


@dataclass(frozen=True)
class SessionAccess:
    session_id: str
    created_at: str
    expires_at: str
    set_cookie: str
    is_new: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def _set_cookie(token: str, *, secure: bool, max_age: int = SESSION_DAYS * 86400) -> str:
    cookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = token
    morsel = cookie[SESSION_COOKIE_NAME]
    morsel["path"] = "/"
    morsel["max-age"] = str(max_age)
    morsel["httponly"] = True
    morsel["samesite"] = "Lax"
    if secure:
        morsel["secure"] = True
    return morsel.OutputString()


class CartService:
    """Operate carts only after resolving a valid server-issued session token."""

    def __init__(self, db_path: str | Path | None = None, clock=None,
                 identity_verifier: IdentityVerifier | None = None):
        self.db_path = db_path
        self.clock = clock or _utc_now
        self.identity_verifier = identity_verifier

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        path = self.db_path if self.db_path is not None else database.DB_PATH
        db = sqlite3.connect(str(path), timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=15000")
            yield db
        finally:
            db.close()

    @staticmethod
    def _begin(db: sqlite3.Connection) -> None:
        # Serializes active-cart creation and quantity mutations across workers.
        db.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _commit(db: sqlite3.Connection) -> None:
        db.commit()

    @staticmethod
    def _rollback(db: sqlite3.Connection) -> None:
        if db.in_transaction:
            db.rollback()

    def get_or_create_session(self, cookie_header: str | None = None, *, is_https: bool = False) -> SessionAccess:
        token = _cookie_token(cookie_header)
        now = self._now()
        now_s = _stamp(now)
        expires_s = _stamp(now + timedelta(days=SESSION_DAYS))
        with self._connection() as db:
            self._begin(db)
            try:
                row = None
                if token:
                    row = db.execute(
                        "SELECT * FROM sessions WHERE token_hash=? AND revoked_at IS NULL",
                        (_token_hash(token),),
                    ).fetchone()
                if row is not None and _parse_time(row["expires_at"]) > now:
                    db.execute(
                        "UPDATE sessions SET last_seen_at=?, expires_at=? WHERE session_id=?",
                        (now_s, expires_s, row["session_id"]),
                    )
                    access = SessionAccess(row["session_id"], row["created_at"], expires_s,
                                           _set_cookie(token, secure=is_https), False)
                else:
                    if row is not None:
                        db.execute("UPDATE sessions SET revoked_at=? WHERE session_id=?",
                                   (now_s, row["session_id"]))
                        expired_before = _stamp(now - timedelta(days=CART_INACTIVE_DAYS))
                        db.execute(
                            """UPDATE carts SET status='expired', updated_at=?
                               WHERE session_id=? AND status='active' AND updated_at<=?""",
                            (now_s, row["session_id"], expired_before),
                        )
                    raw_token = secrets.token_urlsafe(32)
                    session_id = str(uuid.uuid4())
                    db.execute(
                        """INSERT INTO sessions
                           (session_id, token_hash, customer_id, created_at, last_seen_at, expires_at, revoked_at)
                           VALUES (?, ?, NULL, ?, ?, ?, NULL)""",
                        (session_id, _token_hash(raw_token), now_s, now_s, expires_s),
                    )
                    access = SessionAccess(session_id, now_s, expires_s,
                                           _set_cookie(raw_token, secure=is_https), True)
                self._commit(db)
                return access
            except Exception:
                self._rollback(db)
                raise

    def rotate_session_token(self, cookie_header: str,
                             identity_verification: VerifiedIdentityContext,
                             *, is_https: bool = False) -> SessionAccess:
        """Rotate a token only after an injected verifier accepts identity evidence.

        This method intentionally does not accept a customer ID or verification
        claim as separate browser input. Authentication/verification is outside
        V1; the trusted application must provide a verifier adapter.
        """
        if (self.identity_verifier is None or not isinstance(identity_verification, VerifiedIdentityContext)
                or not identity_verification.verification_id.strip()
                or self.identity_verifier.verify(identity_verification) is not True):
            raise IdentityVerificationRequired("verified_identity_context_required")
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        now = self._now()
        now_s = _stamp(now)
        expires_s = _stamp(now + timedelta(days=SESSION_DAYS))
        raw_token = secrets.token_urlsafe(32)
        with self._connection() as db:
            self._begin(db)
            try:
                row = db.execute(
                    "SELECT session_id, created_at, expires_at FROM sessions WHERE token_hash=? AND revoked_at IS NULL",
                    (_token_hash(token),),
                ).fetchone()
                if row is None or _parse_time(row["expires_at"]) <= now:
                    raise SessionInvalid("session_invalid")
                db.execute(
                    "UPDATE sessions SET token_hash=?, last_seen_at=?, expires_at=? WHERE session_id=?",
                    (_token_hash(raw_token), now_s, expires_s, row["session_id"]),
                )
                self._commit(db)
                return SessionAccess(row["session_id"], row["created_at"], expires_s,
                                    _set_cookie(raw_token, secure=is_https), False)
            except Exception:
                self._rollback(db)
                raise

    def _resolve_session(self, db: sqlite3.Connection, token: str) -> sqlite3.Row:
        now = self._now()
        token_hash = _token_hash(token)
        row = db.execute(
            "SELECT * FROM sessions WHERE token_hash=? AND revoked_at IS NULL", (token_hash,)
        ).fetchone()
        if row is None or _parse_time(row["expires_at"]) <= now:
            raise SessionInvalid("session_invalid")
        now_s = _stamp(now)
        expires_s = _stamp(now + timedelta(days=SESSION_DAYS))
        db.execute("UPDATE sessions SET last_seen_at=?, expires_at=? WHERE session_id=?",
                   (now_s, expires_s, row["session_id"]))
        return row

    @staticmethod
    def _validate_quantity(quantity: int) -> None:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise InvalidQuantity("quantity_must_be_positive_integer")

    @staticmethod
    def _offer(db: sqlite3.Connection, offer_id: int) -> sqlite3.Row:
        if isinstance(offer_id, bool) or not isinstance(offer_id, int):
            raise OfferUnavailable("offer_unavailable")
        row = db.execute(
            """SELECT o.offer_id, o.product_id, o.merchant_id, o.price, o.currency,
                      o.active AS offer_active, p.name AS product_name, p.sku,
                      p.active AS product_active, m.name AS merchant_name, m.status AS merchant_status
               FROM offers o
               JOIN products p ON p.product_id=o.product_id
               LEFT JOIN merchants m ON m.merchant_id=o.merchant_id
               WHERE o.offer_id=?""", (offer_id,),
        ).fetchone()
        valid_price = False
        if row is not None:
            try:
                valid_price = math.isfinite(float(row["price"])) and float(row["price"]) >= 0
            except (TypeError, ValueError, OverflowError):
                valid_price = False
        if (row is None or not valid_price or row["offer_active"] != 1 or row["product_active"] != 1
                or row["merchant_id"] is None or row["merchant_status"] != "active"
                or row["currency"] != "YER"):
            raise OfferUnavailable("offer_unavailable")
        return row

    def _active_cart(self, db: sqlite3.Connection, session: sqlite3.Row) -> sqlite3.Row:
        cart = db.execute(
            "SELECT * FROM carts WHERE session_id=? AND status='active'",
            (session["session_id"],),
        ).fetchone()
        now = self._now()
        if cart is not None and _parse_time(cart["updated_at"]) + timedelta(days=CART_INACTIVE_DAYS) <= now:
            db.execute("UPDATE carts SET status='expired', updated_at=? WHERE cart_id=?",
                       (_stamp(now), cart["cart_id"]))
            cart = None
        if cart is None:
            if session["customer_id"] is not None:
                linked_cart = db.execute(
                    "SELECT cart_id, session_id FROM carts WHERE customer_id=? AND status='active'",
                    (session["customer_id"],),
                ).fetchone()
                if linked_cart is not None and linked_cart["session_id"] != session["session_id"]:
                    # Do not leak or reassign the other session's cart. A future
                    # verified-identity merge operation must resolve this case.
                    raise CartNotFound("cart_not_found")
            now_s = _stamp(now)
            cursor = db.execute(
                """INSERT INTO carts
                   (session_id, customer_id, delivery_zone_id, currency, status, created_at, updated_at)
                   VALUES (?, ?, NULL, 'YER', 'active', ?, ?)""",
                (session["session_id"], session["customer_id"], now_s, now_s),
            )
            cart = db.execute("SELECT * FROM carts WHERE cart_id=?", (cursor.lastrowid,)).fetchone()
        return cart

    def get_cart(self, cookie_header: str, *, cart_id: int | None = None) -> dict:
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        with self._connection() as db:
            self._begin(db)
            try:
                session = self._resolve_session(db, token)
                if cart_id is None:
                    cart = self._active_cart(db, session)
                else:
                    cart = db.execute(
                        "SELECT * FROM carts WHERE cart_id=? AND session_id=?",
                        (cart_id, session["session_id"]),
                    ).fetchone()
                    if cart is None:
                        raise CartNotFound("cart_not_found")
                    if cart["status"] != "active":
                        raise CartNotFound("cart_not_found")
                    if _parse_time(cart["updated_at"]) + timedelta(days=CART_INACTIVE_DAYS) <= self._now():
                        db.execute("UPDATE carts SET status='expired', updated_at=? WHERE cart_id=?",
                                   (_stamp(self._now()), cart["cart_id"]))
                        self._commit(db)
                        raise CartNotFound("cart_not_found")
                now_s = _stamp(self._now())
                db.execute("UPDATE carts SET updated_at=? WHERE cart_id=?", (now_s, cart["cart_id"]))
                result = self._read_cart(db, cart["cart_id"])
                self._commit(db)
                return result
            except Exception:
                self._rollback(db)
                raise

    def set_delivery_zone(self, cookie_header: str, zone_id: int, *, cart_id: int | None = None) -> dict:
        """Set the single active delivery zone on the session-owned cart."""
        if isinstance(zone_id, bool) or not isinstance(zone_id, int) or zone_id <= 0:
            raise DeliveryZoneUnavailable("delivery_zone_unavailable")
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        with self._connection() as db:
            self._begin(db)
            try:
                session = self._resolve_session(db, token)
                cart = self._active_cart(db, session) if cart_id is None else self._owned_active_cart(
                    db, session, cart_id
                )
                zone = db.execute(
                    "SELECT zone_id, zone_code, city_name, display_name FROM delivery_zones "
                    "WHERE zone_id=? AND active=1",
                    (zone_id,),
                ).fetchone()
                if zone is None:
                    raise DeliveryZoneUnavailable("delivery_zone_unavailable")
                now_s = _stamp(self._now())
                db.execute(
                    "UPDATE carts SET delivery_zone_id=?, updated_at=? WHERE cart_id=? AND session_id=?",
                    (zone_id, now_s, cart["cart_id"], session["session_id"]),
                )
                self._commit(db)
                return {"cart_id": cart["cart_id"], "delivery_zone": dict(zone)}
            except Exception:
                self._rollback(db)
                raise

    def add_item(self, cookie_header: str, offer_id: int, quantity: int = 1) -> dict:
        self._validate_quantity(quantity)
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        with self._connection() as db:
            self._begin(db)
            try:
                session = self._resolve_session(db, token)
                offer = self._offer(db, offer_id)
                cart = self._active_cart(db, session)
                now_s = _stamp(self._now())
                try:
                    db.execute(
                        """INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(cart_id, offer_id) DO UPDATE SET
                               quantity=cart_items.quantity + excluded.quantity,
                               updated_at=excluded.updated_at""",
                        (cart["cart_id"], offer["offer_id"], quantity, now_s, now_s),
                    )
                except sqlite3.IntegrityError as exc:
                    if "cart_offer_ineligible" in str(exc):
                        raise OfferUnavailable("offer_unavailable") from exc
                    raise
                db.execute("UPDATE carts SET updated_at=? WHERE cart_id=?", (now_s, cart["cart_id"]))
                result = self._read_cart(db, cart["cart_id"])
                self._commit(db)
                return result
            except Exception:
                self._rollback(db)
                raise

    def update_quantity(self, cookie_header: str, offer_id: int, quantity: int, *, cart_id: int | None = None) -> dict:
        self._validate_quantity(quantity)
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        with self._connection() as db:
            self._begin(db)
            try:
                session = self._resolve_session(db, token)
                cart = self._owned_active_cart(db, session, cart_id)
                self._offer(db, offer_id)
                updated = db.execute(
                    "UPDATE cart_items SET quantity=?, updated_at=? WHERE cart_id=? AND offer_id=?",
                    (quantity, _stamp(self._now()), cart["cart_id"], offer_id),
                )
                if not updated.rowcount:
                    raise CartNotFound("cart_item_not_found")
                now_s = _stamp(self._now())
                db.execute("UPDATE carts SET updated_at=? WHERE cart_id=?", (now_s, cart["cart_id"]))
                result = self._read_cart(db, cart["cart_id"])
                self._commit(db)
                return result
            except Exception:
                self._rollback(db)
                raise

    def remove_item(self, cookie_header: str, offer_id: int, *, cart_id: int | None = None) -> dict:
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        with self._connection() as db:
            self._begin(db)
            try:
                session = self._resolve_session(db, token)
                cart = self._owned_active_cart(db, session, cart_id)
                db.execute("DELETE FROM cart_items WHERE cart_id=? AND offer_id=?", (cart["cart_id"], offer_id))
                now_s = _stamp(self._now())
                db.execute("UPDATE carts SET updated_at=? WHERE cart_id=?", (now_s, cart["cart_id"]))
                result = self._read_cart(db, cart["cart_id"])
                self._commit(db)
                return result
            except Exception:
                self._rollback(db)
                raise

    def clear_cart(self, cookie_header: str, *, cart_id: int | None = None) -> dict:
        token = _cookie_token(cookie_header)
        if not token:
            raise SessionInvalid("session_invalid")
        with self._connection() as db:
            self._begin(db)
            try:
                session = self._resolve_session(db, token)
                cart = self._owned_active_cart(db, session, cart_id)
                db.execute("DELETE FROM cart_items WHERE cart_id=?", (cart["cart_id"],))
                now_s = _stamp(self._now())
                db.execute("UPDATE carts SET updated_at=? WHERE cart_id=?", (now_s, cart["cart_id"]))
                result = self._read_cart(db, cart["cart_id"])
                self._commit(db)
                return result
            except Exception:
                self._rollback(db)
                raise

    def _owned_active_cart(self, db: sqlite3.Connection, session: sqlite3.Row,
                           cart_id: int | None) -> sqlite3.Row:
        if cart_id is None:
            cart = self._active_cart(db, session)
        else:
            cart = db.execute(
                "SELECT * FROM carts WHERE cart_id=? AND session_id=? AND status='active'",
                (cart_id, session["session_id"]),
            ).fetchone()
            if cart is None:
                raise CartNotFound("cart_not_found")
        now = self._now()
        if _parse_time(cart["updated_at"]) + timedelta(days=CART_INACTIVE_DAYS) <= now:
            db.execute("UPDATE carts SET status='expired', updated_at=? WHERE cart_id=?",
                       (_stamp(now), cart["cart_id"]))
            self._commit(db)
            raise CartNotFound("cart_not_found")
        return cart

    def _read_cart(self, db: sqlite3.Connection, cart_id: int) -> dict:
        rows = db.execute(
            """SELECT i.cart_item_id, i.offer_id, i.quantity, i.created_at, i.updated_at,
                      o.product_id, o.merchant_id, o.price, o.currency, o.active AS offer_active,
                      p.name AS product_name, p.sku, p.active AS product_active,
                      m.name AS merchant_name, m.status AS merchant_status
               FROM cart_items i
               LEFT JOIN offers o ON o.offer_id=i.offer_id
               LEFT JOIN products p ON p.product_id=o.product_id
               LEFT JOIN merchants m ON m.merchant_id=o.merchant_id
               WHERE i.cart_id=?
               ORDER BY m.merchant_id, p.name, i.offer_id""", (cart_id,),
        ).fetchall()
        groups: dict[int, dict] = {}
        unavailable = []
        for row in rows:
            eligible = (row["offer_id"] is not None and row["product_id"] is not None
                        and row["merchant_id"] is not None and row["offer_active"] == 1
                        and row["product_active"] == 1 and row["merchant_status"] == "active"
                        and row["currency"] == "YER")
            if not eligible:
                unavailable.append({
                    "cart_item_id": row["cart_item_id"], "offer_id": row["offer_id"],
                    "quantity": row["quantity"], "reason": "offer_unavailable",
                })
                continue
            merchant_id = row["merchant_id"]
            group = groups.setdefault(merchant_id, {
                "merchant_id": merchant_id, "merchant_name": row["merchant_name"],
                "currency": "YER", "items": [], "products_subtotal": 0.0,
            })
            line_total = float(row["price"]) * row["quantity"]
            group["items"].append({
                "cart_item_id": row["cart_item_id"], "offer_id": row["offer_id"],
                "product_id": row["product_id"], "product_name": row["product_name"],
                "sku": row["sku"], "quantity": row["quantity"],
                "unit_price": float(row["price"]), "currency": "YER", "line_total": line_total,
            })
            group["products_subtotal"] += line_total
        merchant_groups = list(groups.values())
        return {
            "cart_id": cart_id, "currency": "YER", "merchant_groups": merchant_groups,
            "products_total": sum(group["products_subtotal"] for group in merchant_groups),
            "unavailable_items": unavailable,
        }
