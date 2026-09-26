"""Thin internal application facade; business rules stay in domain services."""
from .catalog import find_products
from .commerce_errors import commerce_checkout_error
from .checkout_service import CheckoutError

class CommerceService:
    def __init__(self, *, cart, quote, checkout, orders=None, cancellation=None, delivery=None, settlement=None):
        self.cart_service=cart; self.quote_service=quote; self.checkout_service=checkout
        self.order_service=orders; self.cancellation_service=cancellation
        self.delivery_service=delivery; self.settlement_service=settlement
    def catalog(self, query, limit=5): return find_products(query, limit)
    def offers(self, query, limit=5): return self.catalog(query, limit)
    def cart(self, *args, **kwargs): return self.cart_service.get_cart(*args, **kwargs)
    def add_to_cart(self, *args, **kwargs): return self.cart_service.add_item(*args, **kwargs)
    def update_cart_quantity(self, *args, **kwargs): return self.cart_service.update_quantity(*args, **kwargs)
    def remove_from_cart(self, *args, **kwargs): return self.cart_service.remove_item(*args, **kwargs)
    def clear_cart(self, *args, **kwargs): return self.cart_service.clear_cart(*args, **kwargs)
    def set_cart_delivery_zone(self, *args, **kwargs): return self.cart_service.set_delivery_zone(*args, **kwargs)
    def quote(self, *args, **kwargs): return self.quote_service.quote(*args, **kwargs)
    def checkout(self, *args, **kwargs):
        try: return self.checkout_service.checkout(*args, **kwargs)
        except CheckoutError as exc: raise commerce_checkout_error(exc) from exc
    def orders(self, order_id): return self.order_service.get_order(order_id)
    def cancel(self, *args, **kwargs): return self.cancellation_service.cancel_merchant_order(*args, **kwargs)
    def delivery(self, *args, **kwargs): return self.delivery_service.transition(*args, **kwargs)
    def settlement(self, *args, **kwargs): return self.settlement_service.create(*args, **kwargs)
