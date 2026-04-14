import json
import logging
import threading
from datetime import datetime
from pathlib import Path

import pytest

from evcc.app import (
    AppConfig,
    MqttStateStore,
    RuntimeMemory,
    build_output_payload,
    create_home_assistant_client,
    derive_status_details,
    load_live_inputs_from_snapshot,
    load_options,
    next_scheduled_run,
    process_runtime_tick,
    restore_missing_controls_from_home_assistant,
    validate_config,
    wait_for_initial_mqtt_restore,
)
from evcc.ha_api import HomeAssistantApiError


PRICING_ATTRIBUTES = {
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
}


class DummyPublisher:
    def __init__(self) -> None:
        self.control_states: list[tuple[str, object]] = []
        self.runtime_payloads: list[dict] = []

    def wait_until_connected(self, timeout: float) -> bool:
        return True

    def publish_control_state(self, key: str, value: object) -> None:
        self.control_states.append((key, value))

    def publish_runtime_state(self, *, snapshot, payload: dict) -> None:
        self.runtime_payloads.append(payload)


class DummyClient:
    def __init__(self) -> None:
        self.actions: list[tuple[str, str]] = []
        self.charger_state = "connected_requesting_charge"
        self.pricing_attributes = PRICING_ATTRIBUTES
        self.entity_values: dict[str, str] = {
            "number.ev_charge_control_current_soc": "80",
            "number.ev_charge_control_target_soc": "90",
            "number.ev_charge_control_battery_capacity": "71.4",
            "number.ev_charge_control_charger_speed": "11",
            "number.ev_charge_control_charge_loss": "10",
            "text.ev_charge_control_finish_by": "06:30",
            "switch.ev_charge_control_nighttime_charging_only": "off",
            "switch.ev_charge_control_schedule_authorized": "off",
            "switch.ev_charge_control_start_stop": "off",
            "switch.ev_charge_control_continuous_power": "off",
        }

    def get_state(self, entity_id: str) -> dict:
        if entity_id == "sensor.energi_data_service":
            return {"state": "ok", "attributes": self.pricing_attributes}
        if entity_id == "sensor.ev_charger_state":
            return {"state": self.charger_state, "attributes": {}}
        if entity_id in self.entity_values:
            return {"state": self.entity_values[entity_id], "attributes": {}}
        raise AssertionError(f"Unexpected entity state request: {entity_id}")

    def get_entity_value(self, entity_id: str) -> str:
        if entity_id == "sensor.ev_charger_state":
            return self.charger_state
        if entity_id in self.entity_values:
            return self.entity_values[entity_id]
        raise AssertionError(f"Unexpected entity value request: {entity_id}")

    def turn_on_switch(self, entity_id: str) -> None:
        self.actions.append(("turn_on_switch", entity_id))

    def turn_off_switch(self, entity_id: str) -> None:
        self.actions.append(("turn_off_switch", entity_id))


def build_config(**overrides: str | int) -> AppConfig:
    mapping: dict[str, str | int] = {
        "mqtt_host": "mqtt.local",
        "mqtt_port": 1883,
        "pricing_information_entity": "sensor.energi_data_service",
        "charger_control_switch_entity": "switch.ev_charger_control",
        "charger_state_sensor_entity": "sensor.ev_charger_state",
    }
    mapping.update(overrides)
    return AppConfig.from_mapping(mapping)


def seed_store(**overrides: str | bool) -> MqttStateStore:
    store = MqttStateStore()
    values: dict[str, str | bool] = {
        "current_soc": "20",
        "target_soc": "80",
        "battery_capacity": "77",
        "charger_speed": "11",
        "charge_loss": "10",
        "finish_by": "06:30",
        "nighttime_charging_only": False,
        "schedule_authorized": False,
        "start_stop": False,
        "continuous_power": False,
    }
    values.update(overrides)
    for key, value in values.items():
        if isinstance(value, bool):
            store.update_value(key, "ON" if value else "OFF")
        else:
            store.update_value(key, value)
    store.clear_change_flag()
    return store


def test_app_config_normalizes_log_level() -> None:
    config = AppConfig.from_mapping({"log_level": "fatal"})
    assert config.log_level == "CRITICAL"


def test_load_options_returns_empty_mapping_for_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "options.json"
    assert load_options(missing_path) == {}


def test_validate_config_reports_required_fields() -> None:
    missing_fields = validate_config(AppConfig())
    assert missing_fields == [
        "mqtt_host",
        "pricing_information_entity",
        "charger_control_switch_entity",
        "charger_state_sensor_entity",
    ]


def test_create_home_assistant_client_returns_none_without_token(monkeypatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert create_home_assistant_client() is None


def test_next_scheduled_run_uses_requested_minutes() -> None:
    current_time = datetime.fromisoformat("2026-03-14T00:02:00+01:00")
    assert next_scheduled_run(current_time) == datetime.fromisoformat("2026-03-14T00:16:00+01:00")


def test_store_rejects_invalid_percentage_payload() -> None:
    store = MqttStateStore()
    with pytest.raises(HomeAssistantApiError, match="between 0 and 100"):
        store.update_value("current_soc", "101")


def test_store_accepts_retained_control_state_message() -> None:
    store = MqttStateStore()
    store.handle_message("control_state", "target_soc", "90")
    assert store.snapshot().target_soc == "90"


def test_store_persists_and_restores_control_values(tmp_path: Path) -> None:
    state_path = tmp_path / "runtime_state.json"
    store = MqttStateStore(state_path=state_path)
    store.update_value("current_soc", "80")
    store.update_value("target_soc", "90")
    store.update_value("battery_capacity", "71.4")
    store.update_value("charger_speed", "11")
    store.update_value("charge_loss", "10")
    store.update_value("finish_by", "06:30")
    store.update_value("nighttime_charging_only", "OFF")
    store.update_value("schedule_authorized", "ON")

    restored = MqttStateStore(state_path=state_path).snapshot()
    assert restored.current_soc == "80"
    assert restored.target_soc == "90"
    assert restored.finish_by == "06:30"
    assert restored.schedule_authorized is True


def test_store_does_not_persist_internal_home_assistant_state(tmp_path: Path) -> None:
    state_path = tmp_path / "runtime_state.json"
    store = MqttStateStore(state_path=state_path)
    store.set_internal_value("pricing_information", json.dumps(PRICING_ATTRIBUTES))
    store.set_internal_value("charger_state", "charging")

    restored = MqttStateStore(state_path=state_path).snapshot()
    assert restored.pricing_information == ""
    assert restored.charger_state == "disconnected"


def test_wait_for_initial_mqtt_restore_waits_for_retained_values() -> None:
    store = MqttStateStore()

    def restore_values() -> None:
        store.handle_message("control_state", "current_soc", "80")
        store.handle_message("control_state", "target_soc", "90")
        store.handle_message("control_state", "battery_capacity", "71.4")
        store.handle_message("control_state", "charger_speed", "11")
        store.handle_message("control_state", "charge_loss", "10")
        store.handle_message("control_state", "finish_by", "06:30")

    timer = threading.Timer(0.05, restore_values)
    timer.start()
    try:
        wait_for_initial_mqtt_restore(
            publisher=DummyPublisher(),
            store=store,
            logger=logging.getLogger("test"),
            restore_timeout=0.5,
        )
    finally:
        timer.join()

    snapshot = store.snapshot()
    assert snapshot.current_soc == "80"
    assert snapshot.target_soc == "90"
    assert snapshot.finish_by == "06:30"


def test_wait_for_initial_mqtt_restore_returns_after_timeout_when_values_missing() -> None:
    store = MqttStateStore()

    wait_for_initial_mqtt_restore(
        publisher=DummyPublisher(),
        store=store,
        logger=logging.getLogger("test"),
        restore_timeout=0.01,
    )

    snapshot = store.snapshot()
    assert snapshot.current_soc is None
    assert snapshot.finish_by is None


def test_restore_missing_controls_from_home_assistant_uses_evcc_entities() -> None:
    store = MqttStateStore()
    client = DummyClient()

    remaining = restore_missing_controls_from_home_assistant(
        client=client,
        store=store,
        logger=logging.getLogger("test"),
    )

    snapshot = store.snapshot()
    assert remaining == []
    assert snapshot.current_soc == "80"
    assert snapshot.target_soc == "90"
    assert snapshot.battery_capacity == "71.4"
    assert snapshot.charger_speed == "11"
    assert snapshot.charge_loss == "10"
    assert snapshot.finish_by == "06:30"


def test_load_live_inputs_from_snapshot_parses_pricing_json() -> None:
    store = seed_store()
    store.set_internal_value("pricing_information", json.dumps(PRICING_ATTRIBUTES))
    snapshot = store.snapshot()
    live_inputs = load_live_inputs_from_snapshot(snapshot)
    assert live_inputs.ev_current_soc == "20"
    assert live_inputs.pricing_information.raw_today


def test_process_runtime_tick_syncs_home_assistant_pricing_and_waiting_status() -> None:
    store = seed_store(schedule_authorized=True)
    publisher = DummyPublisher()
    client = DummyClient()
    memory = RuntimeMemory()

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        memory=memory,
        force_recalculate=True,
    )

    payload = result.published_payload
    assert payload["status"] == "OK"
    assert payload["start"] == "00:15"
    assert payload["end"] == "05:00"
    assert payload["status_message"] == "Charge session planned - expected start in 00:14"
    assert payload["status_level"] == 10
    assert payload["pricing_information"]["raw_today"]


def test_process_runtime_tick_publishes_active_status_from_charger_sensor() -> None:
    store = seed_store(schedule_authorized=True)
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "charging"
    memory = RuntimeMemory(
        last_calculation_time=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        published_payload={
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
            "lock_calculation": True,
        },
        soc_at_charge_start=20.0,
        charger_command=True,
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T02:00:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert result.published_payload["status_message"] == "Charge session active - expected finish at 05:00"
    assert result.published_payload["status_level"] == 20
    assert result.published_payload["charger_state"] == "charging"


def test_process_runtime_tick_latches_completion_status() -> None:
    store = seed_store(current_soc="80", target_soc="80", schedule_authorized=False)
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "connected_finished_idle"
    memory = RuntimeMemory(
        published_payload={
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
            "lock_calculation": False,
        },
        last_charger_enabled=True,
        soc_at_charge_start=20.0,
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T05:10:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert result.published_payload["status_message"] == "Charge session completed at 05:10"
    assert result.published_payload["status_level"] == 10


def test_process_runtime_tick_publishes_disabled_message() -> None:
    store = seed_store(schedule_authorized=False)
    publisher = DummyPublisher()
    client = DummyClient()
    memory = RuntimeMemory(
        published_payload={
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
        }
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:05:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert result.published_payload["status_message"] == "Automatic charging is disabled. Toggle Start / Stop to begin."
    assert result.published_payload["status_level"] == 50


def test_process_runtime_tick_publishes_ready_when_disconnected() -> None:
    store = seed_store()
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "disconnected"
    memory = RuntimeMemory(
        published_payload={"start": "--:--", "end": "--:--", "timestamp": "2026-03-14T00:01:00+01:00", "status": "ok"}
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:05:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert result.published_payload["status_message"] == "Ready"
    assert result.published_payload["status_level"] == 0


def test_process_runtime_tick_resting_without_schedule_does_not_report_system_failure() -> None:
    store = seed_store()
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "disconnected"

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:05:00+01:00"),
        memory=RuntimeMemory(),
        force_recalculate=False,
    )

    assert result.published_payload["status_message"] == "Ready"
    assert result.published_payload["status_level"] == 0


def test_process_runtime_tick_clears_schedule_when_authorization_is_off() -> None:
    store = seed_store(schedule_authorized=False)
    publisher = DummyPublisher()
    client = DummyClient()
    memory = RuntimeMemory(
        published_payload={"start": "23:15", "end": "00:00", "timestamp": "2026-03-14T18:00:00+01:00", "status": "ok"}
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T18:19:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert result.published_payload["start"] == "--:--"
    assert result.published_payload["end"] == "--:--"


def test_process_runtime_tick_clears_schedule_when_unplugged_even_if_authorized() -> None:
    store = seed_store(schedule_authorized=True)
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "disconnected"
    memory = RuntimeMemory(
        published_payload={"start": "23:15", "end": "00:00", "timestamp": "2026-03-14T18:00:00+01:00", "status": "ok"}
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T18:19:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert result.published_payload["start"] == "--:--"
    assert result.published_payload["end"] == "--:--"


def test_process_runtime_tick_raises_for_unsupported_charger_state() -> None:
    store = seed_store()
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "mystery"

    with pytest.raises(HomeAssistantApiError, match="Unsupported charger state"):
        process_runtime_tick(
            client=client,
            config=build_config(),
            store=store,
            publisher=publisher,
            logger=logging.getLogger("test"),
            now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
            memory=RuntimeMemory(),
            force_recalculate=True,
        )


def test_process_runtime_tick_turns_on_selected_charger_switch() -> None:
    store = seed_store(schedule_authorized=True)
    publisher = DummyPublisher()
    client = DummyClient()
    memory = RuntimeMemory(
        published_payload={
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
            "lock_calculation": False,
        }
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:20:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert ("turn_on_switch", "switch.ev_charger_control") in client.actions
    assert result.charger_command is True


def test_start_stop_toggle_starts_charging_and_disables_automatic_schedule() -> None:
    store = seed_store(schedule_authorized=True, start_stop=True)
    publisher = DummyPublisher()
    client = DummyClient()
    memory = RuntimeMemory(
        published_payload={
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
        }
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:20:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert ("schedule_authorized", False) in publisher.control_states
    assert ("turn_on_switch", "switch.ev_charger_control") in client.actions
    assert result.charger_command is True
    assert result.published_payload["start"] == "--:--"
    assert result.published_payload["end"] == "--:--"


def test_start_stop_toggle_off_stops_manual_charging() -> None:
    store = seed_store(schedule_authorized=False, start_stop=False)
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "charging"
    memory = RuntimeMemory(
        charger_command=True,
        last_start_stop=True,
        published_payload={"start": "--:--", "end": "--:--", "timestamp": "2026-03-14T00:01:00+01:00", "status": "ok"},
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:20:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert ("turn_off_switch", "switch.ev_charger_control") in client.actions
    assert result.charger_command is False


def test_process_runtime_tick_keeps_manual_charging_active_without_schedule() -> None:
    store = seed_store(schedule_authorized=False, start_stop=True)
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "charging"
    memory = RuntimeMemory(
        charger_command=True,
        last_start_stop=True,
        published_payload={"start": "--:--", "end": "--:--", "timestamp": "2026-03-14T00:01:00+01:00", "status": "ok"},
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:20:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert result.published_payload["status_message"] == "Charge session active"
    assert result.published_payload["status_level"] == 20


def test_manual_charge_session_stops_at_target_when_continuous_power_is_off() -> None:
    store = seed_store(
        current_soc="80",
        target_soc="80",
        schedule_authorized=False,
        start_stop=True,
        continuous_power=False,
    )
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "charging"
    memory = RuntimeMemory(
        charger_command=True,
        last_start_stop=True,
        published_payload={"start": "--:--", "end": "--:--", "timestamp": "2026-03-14T00:01:00+01:00", "status": "ok"},
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:20:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert ("start_stop", False) in publisher.control_states
    assert ("turn_off_switch", "switch.ev_charger_control") in client.actions
    assert result.charger_command is False
    assert result.last_start_stop is False


def test_process_runtime_tick_keeps_charger_off_when_unauthorized_and_requesting_charge() -> None:
    store = seed_store(schedule_authorized=False, continuous_power=False, start_stop=False)
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "connected_requesting_charge"
    memory = RuntimeMemory(
        charger_command=True,
        published_payload={"start": "--:--", "end": "--:--", "timestamp": "2026-03-14T00:01:00+01:00", "status": "ok"},
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:20:10+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert ("turn_off_switch", "switch.ev_charger_control") in client.actions
    assert result.charger_command is False


def test_process_runtime_tick_continuous_power_keeps_charger_command_after_target() -> None:
    store = seed_store(
        current_soc="80",
        target_soc="80",
        schedule_authorized=True,
        continuous_power=True,
    )
    publisher = DummyPublisher()
    client = DummyClient()
    client.charger_state = "charging"
    memory = RuntimeMemory(
        charger_command=True,
        published_payload={
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status": "ok",
            "lock_calculation": True,
        },
    )

    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T05:00:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert ("turn_off_switch", "switch.ev_charger_control") not in client.actions
    assert result.charger_command is True


def test_process_runtime_tick_republishes_status_immediately_when_charger_state_changes() -> None:
    store = seed_store(schedule_authorized=True)
    publisher = DummyPublisher()
    client = DummyClient()
    memory = RuntimeMemory(
        published_payload={
            "status": "OK",
            "start": "00:15",
            "end": "05:00",
            "timestamp": "2026-03-14T00:01:00+01:00",
            "status_message": "Charge session planned - expected start in 00:14",
            "status_level": 10,
            "lock_calculation": False,
        }
    )

    process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:05:00+01:00"),
        memory=memory,
        force_recalculate=False,
    )
    memory.last_runtime_snapshot = store.snapshot()
    memory.published_payload = publisher.runtime_payloads[-1]
    memory.last_charger_enabled = False

    client.charger_state = "charging"
    result = process_runtime_tick(
        client=client,
        config=build_config(),
        store=store,
        publisher=publisher,
        logger=logging.getLogger("test"),
        now=datetime.fromisoformat("2026-03-14T00:05:01+01:00"),
        memory=memory,
        force_recalculate=False,
    )

    assert len(publisher.runtime_payloads) == 2
    assert result.published_payload["status_level"] == 20
    assert result.published_payload["charger_state"] == "charging"


def test_process_runtime_tick_logs_state_changes_without_price_details(caplog: pytest.LogCaptureFixture) -> None:
    store = seed_store(schedule_authorized=True)
    publisher = DummyPublisher()
    client = DummyClient()
    memory = RuntimeMemory()

    with caplog.at_level(logging.INFO):
        process_runtime_tick(
            client=client,
            config=build_config(),
            store=store,
            publisher=publisher,
            logger=logging.getLogger("test"),
            now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
            memory=memory,
            force_recalculate=True,
        )

    info_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert any(message.startswith("State changed: status_message=") for message in info_messages)
    assert all("pricing_information" not in message for message in info_messages)


def test_build_output_payload_includes_status_and_pricing_fields() -> None:
    payload = build_output_payload(
        {"status": "ok", "start": "00:15", "end": "05:00"},
        finish_by=datetime.fromisoformat("2026-03-14T06:30:00+01:00"),
        schedule_authorized=True,
        charger_enabled=False,
        charger_command=False,
        current_soc=20.0,
        target_soc=80.0,
        soc_at_charge_start=None,
        cable_state="Plugged",
        charge_window_state="Not Reached",
        status_message="Ready",
        status_level=0,
        charger_state="connected_requesting_charge",
        pricing_information={"raw_today": []},
    )
    assert payload["status_message"] == "Ready"
    assert payload["status_level"] == 0
    assert payload["charger_command"] is False
    assert payload["charger_state"] == "connected_requesting_charge"
    assert payload["pricing_information"] == {"raw_today": []}


def test_derive_status_details_keeps_error_precedence() -> None:
    from evcc.app import load_execution_state

    store = seed_store()
    store.set_internal_value("charger_state", "connected_requesting_charge")
    state = load_execution_state(store.snapshot(), now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"))
    details = derive_status_details(
        state=state,
        published_payload={"status": "boom"},
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        completion_time=None,
    )
    assert details.message == "boom"
    assert details.level == 100


def test_derive_status_details_treats_uppercase_ok_as_non_error() -> None:
    from evcc.app import load_execution_state

    store = seed_store(schedule_authorized=True)
    store.set_internal_value("charger_state", "connected_finished_idle")
    state = load_execution_state(store.snapshot(), now=datetime.fromisoformat("2026-03-14T18:19:00+01:00"))
    details = derive_status_details(
        state=state,
        published_payload={
            "status": "OK",
            "start": "23:15",
            "end": "00:00",
            "timestamp": "2026-03-14T18:00:00+01:00",
        },
        now=datetime.fromisoformat("2026-03-14T18:19:00+01:00"),
        completion_time=None,
    )
    assert details.message == "Charge session planned - expected start in 04:56"
    assert details.level == 10
