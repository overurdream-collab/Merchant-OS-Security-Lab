from src.merchant_os.metrics import MetricsEngine
from src.merchant_os.unified_data import BusinessEvent


def test_metrics_are_based_on_observed_events():
    events = [
        BusinessEvent("merchant_contacted", "merchant", "m1", "2026-01-01T10:00:00+00:00", source="facebook"),
        BusinessEvent("merchant_response", "merchant", "m1", "2026-01-01T10:02:00+00:00", source="whatsapp", evidence_id="e1", confidence=0.9),
        BusinessEvent("order_created", "order", "o1", "2026-01-01T11:00:00+00:00", value=1000, currency="YER", source="order_system"),
        BusinessEvent("order_delivered", "order", "o1", "2026-01-02T11:00:00+00:00", source="delivery"),
        BusinessEvent("payment_collected", "order", "o1", "2026-01-02T11:05:00+00:00", value=1000, currency="YER", source="cashier"),
        BusinessEvent("commission_earned", "order", "o1", "2026-01-02T11:06:00+00:00", value=100, currency="YER", source="settlement"),
    ]
    result = MetricsEngine().summarize(events)
    assert result["orders"]["created"] == 1
    assert result["orders"]["delivered"] == 1
    assert result["financial"]["commission_observed"] == 100
    assert result["conversion"]["merchant_contact_to_response"] == 1.0
    assert result["response_time"]["average_seconds"] == 120.0


def test_missing_events_do_not_create_fake_rates():
    result = MetricsEngine().summarize([])
    assert result["conversion"]["merchant_contact_to_response"] is None
    assert result["delivery"]["delivery_rate"] is None
    assert result["financial"]["commission_observed"] == 0
