import json
import logging
from datetime import datetime
from pathlib import Path

from evcc.app import (
    AppConfig,
    create_home_assistant_client,
    load_options,
    next_scheduled_run,
    perform_api_cycle,
    run_api_cycle_with_error_handling,
    validate_config,
)
from evcc.ha_api import HomeAssistantApiError


class DummyClient:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def get_entity_value(self, entity_id: str) -> str:
        return {
            "sensor.ev_current_soc": "20",
            "input_number.ev_target_soc": "80",
            "sensor.ev_battery_capacity": "77",
            "sensor.ev_charger_power": "11",
            "input_number.ev_charge_loss": "10",
            "input_datetime.ev_finish_by": "06:30",
        }[entity_id]

    def get_state(self, entity_id: str) -> dict:
        if entity_id != "sensor.electricity_prices":
            raise AssertionError(f"Unexpected entity: {entity_id}")
        return {
            "state": "ok",
            "attributes": {
                "raw_today": [
                    {"hour": "2026-03-14T00:15:00+01:00", "price": 1.2},
                    {"hour": "2026-03-14T00:30:00+01:00", "price": 1.1},
                    {"hour": "2026-03-14T00:45:00+01:00", "price": 1.0},
                    {"hour": "2026-03-14T01:00:00+01:00", "price": 0.9},
                    {"hour": "2026-03-14T01:15:00+01:00", "price": 0.8},
                    {"hour": "2026-03-14T01:30:00+01:00", "price": 0.7},
                    {"hour": "2026-03-14T01:45:00+01:00", "price": 0.6},
                    {"hour": "2026-03-14T02:00:00+01:00", "price": 0.5},
                    {"hour": "2026-03-14T02:15:00+01:00", "price": 0.4},
                    {"hour": "2026-03-14T02:30:00+01:00", "price": 0.3},
                    {"hour": "2026-03-14T02:45:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T03:00:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T03:15:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T03:30:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T03:45:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T04:00:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T04:15:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T04:30:00+01:00", "price": 0.2},
                    {"hour": "2026-03-14T04:45:00+01:00", "price": 0.2},
                ],
                "raw_tomorrow": None,
                "forecast": [{"hour": "2026-03-15T00:00:00+01:00", "price": 1.1}],
            },
        }

    def set_input_text(self, entity_id: str, value: str) -> None:
        self.writes.append((entity_id, value))


def test_app_config_normalizes_log_level() -> None:
    config = AppConfig.from_mapping({"log_level": "fatal"})
    assert config.log_level == "CRITICAL"


def test_load_options_returns_empty_mapping_for_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "options.json"
    assert load_options(missing_path) == {}


def test_validate_config_reports_missing_required_fields() -> None:
    missing_fields = validate_config(AppConfig())
    assert "ev_current_soc_entity" in missing_fields
    assert "result_helper_entity" in missing_fields


def test_create_home_assistant_client_returns_none_without_token(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert create_home_assistant_client() is None


def test_perform_api_cycle_writes_placeholder_result(caplog) -> None:
    client = DummyClient()
    config = AppConfig.from_mapping(
        {
            "ev_current_soc_entity": "sensor.ev_current_soc",
            "target_soc_entity": "input_number.ev_target_soc",
            "ev_battery_capacity_entity": "sensor.ev_battery_capacity",
            "charger_speed_entity": "sensor.ev_charger_power",
            "charge_loss_entity": "input_number.ev_charge_loss",
            "finish_by_entity": "input_datetime.ev_finish_by",
            "pricing_information_entity": "sensor.electricity_prices",
            "result_helper_entity": "input_text.evcc_result",
        }
    )

    perform_api_cycle(
        client=client,
        config=config,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert client.writes
    assert client.writes[0][0] == "input_text.evcc_result"
    payload = json.loads(client.writes[0][1])
    assert payload["status"] == "ok"
    assert payload["start"] == "00:15"
    assert payload["end"] == "05:00"


def test_api_error_preserves_explicit_exception_type() -> None:
    assert isinstance(HomeAssistantApiError("boom"), RuntimeError)


def test_next_scheduled_run_uses_requested_minutes() -> None:
    current_time = datetime.fromisoformat("2026-03-14T00:02:00+01:00")
    assert next_scheduled_run(current_time) == datetime.fromisoformat(
        "2026-03-14T00:16:00+01:00"
    )


def test_run_api_cycle_with_error_handling_writes_error_result() -> None:
    class FailingClient(DummyClient):
        def get_state(self, entity_id: str) -> dict:
            raise HomeAssistantApiError("boom")

    client = FailingClient()
    config = AppConfig.from_mapping(
        {
            "ev_current_soc_entity": "sensor.ev_current_soc",
            "target_soc_entity": "input_number.ev_target_soc",
            "ev_battery_capacity_entity": "sensor.ev_battery_capacity",
            "charger_speed_entity": "sensor.ev_charger_power",
            "charge_loss_entity": "input_number.ev_charge_loss",
            "finish_by_entity": "input_datetime.ev_finish_by",
            "pricing_information_entity": "sensor.electricity_prices",
            "result_helper_entity": "input_text.evcc_result",
        }
    )

    run_api_cycle_with_error_handling(
        client=client,
        config=config,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    payload = json.loads(client.writes[0][1])
    assert payload["status"] == "boom"
