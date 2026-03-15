import logging
from datetime import datetime
from pathlib import Path

import pytest

from evcc.app import (
    AppConfig,
    TickResult,
    build_output_payload,
    create_home_assistant_client,
    is_schedule_due,
    load_options,
    next_scheduled_run,
    perform_api_cycle,
    process_minute_tick,
    resolve_schedule_start,
    run_api_cycle_with_error_handling,
    sync_soc_at_charge_start_helper,
    sync_schedule_helpers,
    validate_config,
)
from evcc.ha_api import HomeAssistantApiError
from evcc.runtime import NO_SCHEDULE_TIME


class DummyClient:
    def __init__(self) -> None:
        self.actions: list[tuple[str, str]] = []
        self.entity_values = {
            "sensor.ev_current_soc": "20",
            "input_number.ev_target_soc": "80",
            "sensor.ev_battery_capacity": "77",
            "sensor.ev_charger_power": "11",
            "input_number.ev_charge_loss": "10",
            "input_datetime.ev_finish_by": "06:30",
            "input_boolean.nighttime_charging_only": "off",
            "binary_sensor.ev_cable_connected": "on",
            "switch.ev_charger_control": "off",
            "input_boolean.schedule_authorized": "off",
            "input_number.ev_charge_start_soc": "0",
            "input_text.ev_charge_start": "",
            "input_text.ev_charge_end": "",
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

    def turn_on_switch(self, entity_id: str) -> None:
        self.actions.append(("turn_on_switch", entity_id))
        self.entity_values[entity_id] = "on"

    def turn_off_switch(self, entity_id: str) -> None:
        self.actions.append(("turn_off_switch", entity_id))
        self.entity_values[entity_id] = "off"

    def turn_on_input_boolean(self, entity_id: str) -> None:
        self.actions.append(("turn_on_input_boolean", entity_id))
        self.entity_values[entity_id] = "on"

    def turn_off_input_boolean(self, entity_id: str) -> None:
        self.actions.append(("turn_off_input_boolean", entity_id))
        self.entity_values[entity_id] = "off"

    def set_input_number(self, entity_id: str, value: float | int) -> None:
        self.actions.append(("set_input_number", entity_id, value))
        self.entity_values[entity_id] = str(value)

    def set_input_text(self, entity_id: str, value: str) -> None:
        self.actions.append(("set_input_text", entity_id, value))
        self.entity_values[entity_id] = value


class DummyPublisher:
    def __init__(self) -> None:
        self.outputs: list[dict] = []

    def publish_output(self, payload: dict) -> None:
        self.outputs.append(payload)


def build_config(**overrides: str | int) -> AppConfig:
    mapping: dict[str, str | int] = {
        "ev_current_soc_entity": "sensor.ev_current_soc",
        "target_soc_entity": "input_number.ev_target_soc",
        "ev_battery_capacity_entity": "sensor.ev_battery_capacity",
        "charger_speed_entity": "sensor.ev_charger_power",
        "charge_loss_entity": "input_number.ev_charge_loss",
        "finish_by_entity": "input_datetime.ev_finish_by",
        "nighttime_charging_only_entity": "input_boolean.nighttime_charging_only",
        "cable_connected_entity": "binary_sensor.ev_cable_connected",
        "charger_control_switch_entity": "switch.ev_charger_control",
        "schedule_authorized_entity": "input_boolean.schedule_authorized",
        "soc_at_charge_start_helper_entity": "",
        "calculated_start_helper_entity": "",
        "calculated_end_helper_entity": "",
        "pricing_information_entity": "sensor.electricity_prices",
        "mqtt_host": "mqtt.local",
        "mqtt_port": 1883,
    }
    mapping.update(overrides)
    return AppConfig.from_mapping(mapping)


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
    assert "cable_connected_entity" in missing_fields
    assert "charger_control_switch_entity" in missing_fields
    assert "schedule_authorized_entity" in missing_fields
    assert "mqtt_host" in missing_fields


def test_create_home_assistant_client_returns_none_without_token(monkeypatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert create_home_assistant_client() is None


def test_perform_api_cycle_publishes_result() -> None:
    client = DummyClient()
    publisher = DummyPublisher()

    payload = perform_api_cycle(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert publisher.outputs
    assert payload["status"] == "ok"
    assert payload["start"] == "00:15"
    assert payload["end"] == "05:00"
    assert payload["complete_by"] == "06:30"
    assert payload["authorization_enabled"] is False
    assert payload["charger_enabled"] is False
    assert payload["soc_at_charge_start"] == ""
    assert payload["current_soc"] == 20
    assert payload["target_soc"] == 80
    assert payload["cable_state"] == "Plugged"
    assert payload["charge_window_state"] == "Not Reached"
    assert payload["lock_calculation"] is False


def test_api_error_preserves_explicit_exception_type() -> None:
    assert isinstance(HomeAssistantApiError("boom"), RuntimeError)


def test_next_scheduled_run_uses_requested_minutes() -> None:
    current_time = datetime.fromisoformat("2026-03-14T00:02:00+01:00")
    assert next_scheduled_run(current_time) == datetime.fromisoformat(
        "2026-03-14T00:16:00+01:00"
    )


def test_run_api_cycle_with_error_handling_publishes_error_result() -> None:
    class FailingClient(DummyClient):
        def get_state(self, entity_id: str) -> dict:
            raise HomeAssistantApiError("boom")

    publisher = DummyPublisher()

    payload = run_api_cycle_with_error_handling(
        client=FailingClient(),
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert payload["status"] == "boom"
    assert publisher.outputs[-1]["status"] == "boom"


def test_run_api_cycle_with_invalid_nighttime_helper_publishes_error_result() -> None:
    class InvalidNighttimeClient(DummyClient):
        def get_entity_value(self, entity_id: str) -> str:
            if entity_id == "input_boolean.nighttime_charging_only":
                return "unknown"
            return super().get_entity_value(entity_id)

    publisher = DummyPublisher()
    payload = run_api_cycle_with_error_handling(
        client=InvalidNighttimeClient(),
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

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
    assert not is_schedule_due({"status": "ok", "start": NO_SCHEDULE_TIME}, now=now)


def test_build_output_payload_adds_runtime_fields() -> None:
    payload = build_output_payload(
        {"start": "00:15", "end": "05:00", "timestamp": "2026-03-14T00:01:00+01:00", "status": "ok"},
        finish_by=datetime.fromisoformat("2026-03-14T06:30:00+01:00"),
        schedule_authorized=True,
        charger_enabled=False,
        current_soc=47.0,
        target_soc=100.0,
        soc_at_charge_start=None,
    )
    assert payload["complete_by"] == "06:30"
    assert payload["authorization_enabled"] is True
    assert payload["charger_enabled"] is False
    assert payload["soc_at_charge_start"] == ""
    assert payload["current_soc"] == 47
    assert payload["target_soc"] == 100
    assert payload["lock_calculation"] is False


def test_process_minute_tick_turns_on_switch_and_disables_authorization() -> None:
    client = DummyClient()
    publisher = DummyPublisher()
    client.entity_values["input_boolean.schedule_authorized"] = "on"
    published_payload = {
        "start": "00:15",
        "end": "05:00",
        "timestamp": "2026-03-14T00:01:00+01:00",
        "status": "ok",
    }

    result = process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:15:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        soc_at_charge_start=None,
        published_payload=published_payload,
    )

    assert result == TickResult(
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        soc_at_charge_start=20.0,
        published_payload=publisher.outputs[-1],
    )
    assert client.actions == [
        ("turn_off_input_boolean", "input_boolean.schedule_authorized"),
        ("turn_on_switch", "switch.ev_charger_control"),
    ]
    assert publisher.outputs[-1]["authorization_enabled"] is False
    assert publisher.outputs[-1]["charger_enabled"] is True
    assert publisher.outputs[-1]["soc_at_charge_start"] == 20
    assert publisher.outputs[-1]["status"] == "OK"
    assert publisher.outputs[-1]["charge_window_state"] == "In Window"
    assert publisher.outputs[-1]["lock_calculation"] is True


def test_process_minute_tick_does_not_execute_when_authorization_is_off() -> None:
    client = DummyClient()
    publisher = DummyPublisher()
    published_payload = {
        "start": "00:15",
        "end": "05:00",
        "timestamp": "2026-03-14T00:01:00+01:00",
        "status": "ok",
    }

    process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:15:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        soc_at_charge_start=None,
        published_payload=published_payload,
    )

    assert client.actions == []
    assert publisher.outputs[-1]["authorization_enabled"] is False
    assert publisher.outputs[-1]["status"] == "WARN"


def test_process_minute_tick_raises_for_invalid_authorization_helper() -> None:
    client = DummyClient()
    client.entity_values["input_boolean.schedule_authorized"] = "unknown"

    with pytest.raises(
        HomeAssistantApiError,
        match="Invalid input_boolean state for 'schedule_authorized_entity'",
    ):
        process_minute_tick(
            client=client,
            publisher=DummyPublisher(),
            config=build_config(),
            logger=logging.getLogger("test"),
            now=datetime.fromisoformat("2026-03-14T00:15:00+01:00"),
            last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
            soc_at_charge_start=None,
            published_payload={},
        )


def test_process_minute_tick_skips_calculation_while_locked() -> None:
    client = DummyClient()
    publisher = DummyPublisher()
    client.entity_values["switch.ev_charger_control"] = "on"
    client.entity_values["input_boolean.schedule_authorized"] = "on"
    result = process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:16:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        soc_at_charge_start=19.0,
        published_payload={
            "status": "OK",
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "lock_calculation": True,
        },
    )
    assert result.last_calculation_time == datetime.fromisoformat("2026-03-14T00:01:00+01:00")
    assert result.soc_at_charge_start == 19.0
    assert publisher.outputs[-1]["soc_at_charge_start"] == 19
    assert publisher.outputs[-1]["charger_enabled"] is True
    assert publisher.outputs[-1]["status"] == "OK"


def test_process_minute_tick_recalculates_when_lock_releases_at_target_soc() -> None:
    client = DummyClient()
    publisher = DummyPublisher()
    client.entity_values["switch.ev_charger_control"] = "on"
    client.entity_values["sensor.ev_current_soc"] = "80"
    client.entity_values["input_number.ev_target_soc"] = "80"

    result = process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:16:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        soc_at_charge_start=20.0,
        published_payload={
            "status": "OK",
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
        },
    )

    assert result.last_calculation_time == datetime.fromisoformat("2026-03-14T00:16:00+01:00")
    assert publisher.outputs
    assert ("turn_on_input_boolean", "input_boolean.schedule_authorized") in client.actions
    assert ("turn_off_switch", "switch.ev_charger_control") in client.actions
    assert publisher.outputs[-1]["current_soc"] == 80
    assert publisher.outputs[-1]["target_soc"] == 80
    assert publisher.outputs[-1]["authorization_enabled"] is True
    assert publisher.outputs[-1]["charger_enabled"] is False
    assert publisher.outputs[-1]["status"] == "OK"
    assert publisher.outputs[-1]["lock_calculation"] is False


def test_process_minute_tick_only_resets_once_when_target_soc_is_already_reached() -> None:
    class StickyChargerClient(DummyClient):
        def turn_off_switch(self, entity_id: str) -> None:
            self.actions.append(("turn_off_switch", entity_id))

    client = StickyChargerClient()
    publisher = DummyPublisher()
    client.entity_values["switch.ev_charger_control"] = "on"
    client.entity_values["sensor.ev_current_soc"] = "80"
    client.entity_values["input_number.ev_target_soc"] = "80"

    first_result = process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:16:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        soc_at_charge_start=20.0,
        published_payload={
            "status": "OK",
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
        },
    )

    second_result = process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:17:00+01:00"),
        last_calculation_time=first_result.last_calculation_time,
        soc_at_charge_start=first_result.soc_at_charge_start,
        published_payload=first_result.published_payload,
    )

    assert client.actions.count(("turn_off_switch", "switch.ev_charger_control")) == 1
    assert second_result.published_payload["state_machine_rule"] == "auto_reset_soc_reached"


def test_sync_soc_at_charge_start_helper_writes_captured_soc() -> None:
    client = DummyClient()

    sync_soc_at_charge_start_helper(
        client=client,
        config=build_config(
            soc_at_charge_start_helper_entity="input_number.ev_charge_start_soc"
        ),
        soc_at_charge_start=20.0,
    )

    assert client.actions == [("set_input_number", "input_number.ev_charge_start_soc", 20)]


def test_sync_soc_at_charge_start_helper_skips_unchanged_value() -> None:
    client = DummyClient()
    client.entity_values["input_number.ev_charge_start_soc"] = "20"

    sync_soc_at_charge_start_helper(
        client=client,
        config=build_config(
            soc_at_charge_start_helper_entity="input_number.ev_charge_start_soc"
        ),
        soc_at_charge_start=20.0,
    )

    assert client.actions == []


def test_sync_soc_at_charge_start_helper_resets_to_zero_when_unknown() -> None:
    client = DummyClient()
    client.entity_values["input_number.ev_charge_start_soc"] = "20"

    sync_soc_at_charge_start_helper(
        client=client,
        config=build_config(
            soc_at_charge_start_helper_entity="input_number.ev_charge_start_soc"
        ),
        soc_at_charge_start=None,
    )

    assert client.actions == [("set_input_number", "input_number.ev_charge_start_soc", 0)]


def test_process_minute_tick_updates_charge_start_soc_helper_when_charging_starts() -> None:
    client = DummyClient()
    publisher = DummyPublisher()
    client.entity_values["input_boolean.schedule_authorized"] = "on"

    process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(
            soc_at_charge_start_helper_entity="input_number.ev_charge_start_soc"
        ),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:15:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        soc_at_charge_start=None,
        published_payload={
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
        },
    )

    assert ("set_input_number", "input_number.ev_charge_start_soc", 20) in client.actions


def test_process_minute_tick_sets_soc_at_charge_start_when_cable_plugs_in() -> None:
    client = DummyClient()
    publisher = DummyPublisher()
    client.entity_values["binary_sensor.ev_cable_connected"] = "on"
    client.entity_values["sensor.ev_current_soc"] = "33"

    result = process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:17:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:16:00+01:00"),
        soc_at_charge_start=20.0,
        published_payload={
            "status": "OK",
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "cable_state": "Unplugged",
            "charger_enabled": False,
        },
    )

    assert result.soc_at_charge_start == 33.0
    assert publisher.outputs[-1]["soc_at_charge_start"] == 33


def test_process_minute_tick_keeps_soc_at_charge_start_constant_while_charging_is_on() -> None:
    client = DummyClient()
    publisher = DummyPublisher()
    client.entity_values["switch.ev_charger_control"] = "on"
    client.entity_values["sensor.ev_current_soc"] = "25"

    result = process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:17:00+01:00"),
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:16:00+01:00"),
        soc_at_charge_start=20.0,
        published_payload={
            "status": "OK",
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "cable_state": "Plugged",
            "charger_enabled": True,
        },
    )

    assert result.soc_at_charge_start == 20.0
    assert publisher.outputs[-1]["soc_at_charge_start"] == 20


def test_sync_schedule_helpers_write_start_and_end_values() -> None:
    client = DummyClient()

    sync_schedule_helpers(
        client=client,
        config=build_config(
            calculated_start_helper_entity="input_text.ev_charge_start",
            calculated_end_helper_entity="input_text.ev_charge_end",
        ),
        payload={"start": "00:15", "end": "05:00"},
    )

    assert ("set_input_text", "input_text.ev_charge_start", "00:15") in client.actions
    assert ("set_input_text", "input_text.ev_charge_end", "05:00") in client.actions


def test_sync_schedule_helpers_skip_unchanged_values() -> None:
    client = DummyClient()
    client.entity_values["input_text.ev_charge_start"] = "00:15"
    client.entity_values["input_text.ev_charge_end"] = "05:00"

    sync_schedule_helpers(
        client=client,
        config=build_config(
            calculated_start_helper_entity="input_text.ev_charge_start",
            calculated_end_helper_entity="input_text.ev_charge_end",
        ),
        payload={"start": "00:15", "end": "05:00"},
    )

    assert client.actions == []


def test_sync_schedule_helpers_write_placeholder_when_values_missing() -> None:
    client = DummyClient()
    client.entity_values["input_text.ev_charge_start"] = "00:15"
    client.entity_values["input_text.ev_charge_end"] = "05:00"

    sync_schedule_helpers(
        client=client,
        config=build_config(
            calculated_start_helper_entity="input_text.ev_charge_start",
            calculated_end_helper_entity="input_text.ev_charge_end",
        ),
        payload={"start": "", "end": ""},
    )

    assert ("set_input_text", "input_text.ev_charge_start", NO_SCHEDULE_TIME) in client.actions
    assert ("set_input_text", "input_text.ev_charge_end", NO_SCHEDULE_TIME) in client.actions


def test_process_minute_tick_updates_schedule_helpers_from_runtime_payload() -> None:
    client = DummyClient()
    publisher = DummyPublisher()

    process_minute_tick(
        client=client,
        publisher=publisher,
        config=build_config(
            calculated_start_helper_entity="input_text.ev_charge_start",
            calculated_end_helper_entity="input_text.ev_charge_end",
        ),
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        last_calculation_time=None,
        soc_at_charge_start=None,
        published_payload=None,
    )

    assert ("set_input_text", "input_text.ev_charge_start", "00:15") in client.actions
    assert ("set_input_text", "input_text.ev_charge_end", "05:00") in client.actions
