from telegram_reader import features
from telegram_reader.features import FEATURES, Feature, allowed_requests


def test_write_is_registered_unavailable_and_high_risk():
    f = FEATURES["write"]
    assert f.title == "Sending messages"
    assert f.risk == "high"
    assert f.available is False


def test_allowed_requests_ignores_unavailable(monkeypatch):
    monkeypatch.setitem(
        FEATURES,
        "demo",
        Feature("demo", "Demo", "d", "low", True, requests=("SendMessageRequest",)),
    )
    assert allowed_requests(frozenset({"demo"})) == frozenset({"SendMessageRequest"})
    assert allowed_requests(frozenset({"write"})) == frozenset()
    assert allowed_requests(frozenset({"unknown"})) == frozenset()
