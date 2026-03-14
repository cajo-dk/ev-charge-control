import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from evcc.app import (
    AppConfig,
    create_home_assistant_client,
    is_schedule_due,
    load_options,
    next_scheduled_run,
    perform_api_cycle,
    process_minute_tick,
    resolve_schedule_start,
    run_api_cycle_with_error_handling,
    validate_config,
)
from evcc.ha_api import HomeAssistantApiError


class DummyClient:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.entity_values = {
            "sensor.ev_current_soc": "20",
            "input_number.ev_target_soc": "80",
            "sensor.ev_battery_capacity": "77",
            "sensor.ev_charger_power": "11",
            "input_number.ev_charge_loss": "10",
            "input_datetime.ev_finish_by": "06:30",
            "input_boolean.nighttime_charging_only": "off",
            "switch.ev_charger_control": "off",
            "input_boolean.schedule_authorized": "off",
            "input_text.evcc_result": json.dumps(
                {
                    "start": "",
                    "end": "",
                    "timestamp": "2026-03-14T00:01:00+01:00",
                    "status": "ok",
                }
            ),
        }

    def get_entity_value(self, entity_id: str) -> str:
        return self.entity_values[entity_id]

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
        self.entity_values[entity_id] = value

    def turn_on_switch(self, entity_id: str) -> None:
        self.actions.append(("turn_on_switch", entity_id))
        self.entity_values[entity_id] = "on"

    def turn_off_input_boolean(self, entity_id: str) -> None:
        self.actions.append(("turn_off_input_boolean", entity_id))
        self.entity_values[entity_id] = "off"


def build_config() -> AppConfig:
    return AppConfig.from_mapping(
        {
            "ev_current_soc_entity": "sensor.ev_current_soc",
            "target_soc_entity": "input_number.ev_target_soc",
            "ev_battery_capacity_entity": "sensor.ev_battery_capacity",
            "charger_speed_entity": "sensor.ev_charger_power",
            "charge_loss_entity": "input_number.ev_charge_loss",
            "finish_by_entity": "input_datetime.ev_finish_by",
            "nighttime_charging_only_entity": "input_boolean.nighttime_charging_only",
            "charger_control_switch_entity": "switch.ev_charger_control",
            "schedule_authorized_entity": "input_boolean.schedule_authorized",
            "pricing_information_entity": "sensor.electricity_prices",
            "result_helper_entity": "input_text.evcc_result",
        }
    )


def test_app_config_normalizes_log_level() -> None:
    config = AppConfig.from_mapping({"log_level": "fatal"})
    assert config.log_level == "CRITICAL"


def test_load_options_returns_empty_mapping_for_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "options.json"
    assert load_options(missing_path) == {}


def test_validate_config_reports_missing_required_fields() -> None:
    missing_fields = validate_config(AppConfig())
    assert "ev_current_soc_entity" in missing_fields
    assert "nighttime_charging_only_entity" in missing_fields
    assert "charger_control_switch_entity" in missing_fields
    assert "schedule_authorized_entity" in missing_fields
    assert "result_helper_entity" in missing_fields


def test_create_home_assistant_client_returns_none_without_token(monkeypatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert create_home_assistant_client() is None


def test_perform_api_cycle_writes_placeholder_result() -> None:
    client = DummyClient()
    config = build_config()

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

    run_api_cycle_with_error_handling(
        client=client,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    payload = json.loads(client.writes[0][1])
    assert payload["status"] == "boom"


def test_run_api_cycle_with_invalid_nighttime_helper_writes_error_result() -> None:
    class InvalidNighttimeClient(DummyClient):
        def get_entity_value(self, entity_id: str) -> str:
            if entity_id == "input_boolean.nighttime_charging_only":
                return "unknown"
            return super().get_entity_value(entity_id)

    client = InvalidNighttimeClient()

    run_api_cycle_with_error_handling(
        client=client,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    payload = json.loads(client.writes[0][1])
    assert payload["status"] == (
        "Invalid input_boolean state for 'nighttime_charging_only_entity': unknown"
    )


def test_resolve_schedule_start_rolls_to_next_day_when_needed() -> None:
    now = datetime.fromisoformat("2026-03-15T00:05:00+01:00")
    resolved = resolve_schedule_start(
        start="00:15",
        timestamp="2026-03-14T23:46:00+01:00",
        now=now,
    )

    assert resolved == datetime.fromisoformat("2026-03-15T00:15:00+01:00")


def test_is_schedule_due_ignores_blank_or_error_payloads() -> None:
    now = datetime.fromisoformat("2026-03-14T00:20:00+01:00")
    assert not is_schedule_due(None, now=now)
    assert not is_schedule_due({"status": "boom", "start": "00:15"}, now=now)
    assert not is_schedule_due({"status": "ok", "start": ""}, now=now)


def test_process_minute_tick_turns_on_switch_and_disables_authorization() -> None:
    client = DummyClient()
    client.entity_values["input_boolean.schedule_authorized"] = "on"
    client.entity_values["input_text.evcc_result"] = json.dumps(
        {
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
        }
    )

    result = process_minute_tick(
        client=client,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:15:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert result == datetime.fromisoformat("2026-03-14T00:01:00+01:00")
    assert client.actions == [
        ("turn_on_switch", "switch.ev_charger_control"),
        ("turn_off_input_boolean", "input_boolean.schedule_authorized"),
    ]


def test_process_minute_tick_does_not_execute_when_authorization_is_off() -> None:
    client = DummyClient()
    client.entity_values["input_text.evcc_result"] = json.dumps(
        {
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
        }
    )

    process_minute_tick(
        client=client,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:15:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert client.actions == []


def test_process_minute_tick_raises_for_invalid_authorization_helper() -> None:
    client = DummyClient()
    client.entity_values["input_boolean.schedule_authorized"] = "unknown"

    with pytest.raises(
        HomeAssistantApiError,
        match="Invalid input_boolean state for 'schedule_authorized_entity'",
    ):
        process_minute_tick(
            client=client,
            config=build_config(),
            logger=logging.getLogger("test"),
            now=datetime.fromisoformat("2026-03-14T00:15:00+01:00"),
            last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        )


def test_process_minute_tick_skips_calculation_while_locked() -> None:
    client = DummyClient()
    client.entity_values["switch.ev_charger_control"] = "on"
    client.entity_values["sensor.ev_current_soc"] = "20"
    client.entity_values["input_number.ev_target_soc"] = "80"

    result = process_minute_tick(
        client=client,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:16:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert result == datetime.fromisoformat("2026-03-14T00:01:00+01:00")
    assert client.writes == []


def test_process_minute_tick_recalculates_when_lock_releases_at_target_soc() -> None:
    client = DummyClient()
    client.entity_values["switch.ev_charger_control"] = "on"
    client.entity_values["sensor.ev_current_soc"] = "80"
    client.entity_values["input_number.ev_target_soc"] = "80"

    result = process_minute_tick(
        client=client,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:16:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert result == datetime.fromisoformat("2026-03-14T00:16:00+01:00")
    assert client.writes
