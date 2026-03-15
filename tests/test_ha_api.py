import json
from urllib import error

import pytest

from evcc.ha_api import HomeAssistantApiError, HomeAssistantClient


class DummyResponse:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def close(self) -> None:
        return None

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_get_state_attaches_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_headers: dict[str, str] = {}

    def fake_urlopen(request, timeout):
        captured_headers.update(dict(request.header_items()))
        return DummyResponse(json.dumps({"state": "42", "attributes": {}}))

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    payload = client.get_state("sensor.foo")

    assert payload["state"] == "42"
    assert captured_headers["Authorization"] == "Bearer secret"


def test_set_input_text_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse("[]")

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    client.set_input_text("input_text.evcc_result", "{\"status\": \"ok\"}")

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/services/input_text/set_value")
    assert captured["body"]["entity_id"] == "input_text.evcc_result"


def test_set_input_number_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse("[]")

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    client.set_input_number("input_number.ev_charge_start_soc", 42)

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/services/input_number/set_value")
    assert captured["body"]["entity_id"] == "input_number.ev_charge_start_soc"
    assert captured["body"]["value"] == 42


def test_turn_on_switch_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse("[]")

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    client.turn_on_switch("switch.ev_charger_control")

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/services/switch/turn_on")
    assert captured["body"]["entity_id"] == "switch.ev_charger_control"


def test_turn_off_switch_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse("[]")

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    client.turn_off_switch("switch.ev_charger_control")

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/services/switch/turn_off")
    assert captured["body"]["entity_id"] == "switch.ev_charger_control"


def test_turn_on_input_boolean_posts_expected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse("[]")

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    client.turn_on_input_boolean("input_boolean.schedule_authorized")

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/services/input_boolean/turn_on")
    assert captured["body"]["entity_id"] == "input_boolean.schedule_authorized"


def test_turn_off_input_boolean_posts_expected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return DummyResponse("[]")

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    client.turn_off_input_boolean("input_boolean.schedule_authorized")

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/services/input_boolean/turn_off")
    assert captured["body"]["entity_id"] == "input_boolean.schedule_authorized"


def test_http_error_raises_clear_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        raise error.HTTPError(
            request.full_url,
            500,
            "Server Error",
            hdrs=None,
            fp=DummyResponse("{\"message\": \"boom\"}"),
        )

    monkeypatch.setattr("evcc.ha_api.request.urlopen", fake_urlopen)
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    with pytest.raises(HomeAssistantApiError, match="HTTP 500"):
        client.get_state("sensor.foo")


def test_malformed_json_raises_clear_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "evcc.ha_api.request.urlopen",
        lambda request, timeout: DummyResponse("not-json"),
    )
    client = HomeAssistantClient(base_url="http://example/api", token="secret")

    with pytest.raises(HomeAssistantApiError, match="malformed JSON"):
        client.get_state("sensor.foo")
