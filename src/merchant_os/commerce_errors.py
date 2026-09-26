"""Stable machine-readable errors for new Commerce Core services."""


class CommerceError(RuntimeError):
    def __init__(self, code: str, *, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code)


class IdentityRequired(CommerceError):
    def __init__(self):
        super().__init__("IDENTITY_REQUIRED")


CHECKOUT_ERROR_CODES = {
    "session_invalid": "SESSION_INVALID", "cart_not_found": "CART_NOT_FOUND",
    "cart_expired": "CART_EXPIRED", "cart_empty": "CART_EMPTY",
    "delivery_zone_unavailable": "DELIVERY_ZONE_INVALID", "quote_changed": "QUOTE_STALE",
    "invalid_quantity": "INVALID_QUANTITY", "offer_unavailable": "OFFER_UNAVAILABLE",
    "unsupported_currency": "UNSUPPORTED_CURRENCY",
    "delivery_policy_unavailable": "DELIVERY_POLICY_MISSING",
    "invalid_payment_method": "INVALID_PAYMENT_METHOD",
    "insufficient_stock": "INSUFFICIENT_STOCK", "idempotency_conflict": "CHECKOUT_CONFLICT",
    "already_checked_out_conflict": "CHECKOUT_CONFLICT", "database_busy": "DATABASE_BUSY",
    "checkout_failed": "CHECKOUT_FAILED", "checkout_configuration_error": "CHECKOUT_CONFIGURATION_ERROR",
}


def commerce_checkout_error(exc):
    """Translate legacy CheckoutError codes at the facade without changing that API."""
    code=CHECKOUT_ERROR_CODES.get(getattr(exc,"code",None),"CHECKOUT_FAILED")
    return CommerceError(code)
