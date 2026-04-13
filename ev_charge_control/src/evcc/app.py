from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from evcc.ha_api import HomeAssistantApiError
from evcc.mqtt_output import MQTTOutputPublisher
from evcc.runtime import (
    NO_SCHEDULE_TIME,
    LiveInputs,
    PricingPayload,
    build_error_result,
    calculate_result,
    parse_finish_by_value,
    parse_percentage_value,
)
from evcc.state_machine import (
    CABLE_PLUGGED,
    CABLE_UNPLUGGED,
    WINDOW_IN_WINDOW,
    WINDOW_NOT_REACHED,
    WINDOW_PAST_WINDOW,
    StateMachineContext,
    StateMachineDecision,
    evaluate_state_machine,
)


DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_MQTT_TOPIC_PREFIX = "ev_charge_control"
RUN_MINUTES = (1, 16, 31, 46)
SUPPORTED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


@dataclass(slots=True)
class AppConfig:
    log_level: str = DEFAULT_LOG_LEVEL
    mqtt_host: str = ""
    mqtt_port: int = DEFAULT_MQTT_PORT
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_discovery_prefix: str = DEFAULT_MQTT_DISCOVERY_PREFIX
    mqtt_topic_prefix: str = DEFAULT_MQTT_TOPIC_PREFIX

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "AppConfig":
        normalized = {key: raw.get(key, getattr(cls(), key)) for key in cls.__dataclass_fields__}
        log_level = str(normalized.get("log_level", DEFAULT_LOG_LEVEL)).upper()
        if log_level == "TRACE":
            log_level = "DEBUG"
        if log_level == "NOTICE":
            log_level = "INFO"
        if log_level == "FATAL":
            log_level = "CRITICAL"
        if log_level not in SUPPORTED_LOG_LEVELS:
            log_level = DEFAULT_LOG_LEVEL
        normalized["log_level"] = log_level
        normalized["mqtt_port"] = _parse_mqtt_port(normalized.get("mqtt_port", DEFAULT_MQTT_PORT))
        return cls(**normalized)


@dataclass(slots=True)
class RuntimeSnapshot:
    current_soc: str | None = None
    target_soc: str | None = None
    battery_capacity: str | None = None
    charger_speed: str | None = None
    charge_loss: str | None = None
    finish_by: str | None = None
    nighttime_charging_only: bool = False
    cable_connected: bool = False
    schedule_authorized: bool = False
    charger_state: bool = False
    charger_command: bool = False
    pricing_information: str = ""
    start_requests: int = 0


@dataclass(slots=True)
class ExecutionState:
    cable: str
    current_soc: float | None
    target_soc: float | None
    finish_by: datetime | None
    charger_enabled: bool
    schedule_authorized: bool
    charger_command: bool


@dataclass(slots=True)
class RuntimeMemory:
    last_calculation_time: datetime | None = None
    soc_at_charge_start: float | None = None
    published_payload: dict[str, Any] | None = None
    completion_time: str | None = None
    last_charger_enabled: bool | None = None


@dataclass(slots=True)
class TickResult:
    last_calculation_time: datetime | None
    soc_at_charge_start: float | None
    published_payload: dict[str, Any] | None
    completion_time: str | None
    last_charger_enabled: bool | None


@dataclass(slots=True)
class StatusDetails:
    message: str
    level: int
    completion_time: str | None


class MqttStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._changed = threading.Event()
        self._version = 0
        self._snapshot = RuntimeSnapshot()

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                current_soc=self._snapshot.current_soc,
                target_soc=self._snapshot.target_soc,
                battery_capacity=self._snapshot.battery_capacity,
                charger_speed=self._snapshot.charger_speed,
                charge_loss=self._snapshot.charge_loss,
                finish_by=self._snapshot.finish_by,
                nighttime_charging_only=self._snapshot.nighttime_charging_only,
                cable_connected=self._snapshot.cable_connected,
                schedule_authorized=self._snapshot.schedule_authorized,
                charger_state=self._snapshot.charger_state,
                charger_command=self._snapshot.charger_command,
                pricing_information=self._snapshot.pricing_information,
                start_requests=self._snapshot.start_requests,
            )

    def version(self) -> int:
        with self._lock:
            return self._version

    def wait_for_change(self, timeout: float) -> bool:
        return self._changed.wait(timeout)

    def clear_change_flag(self) -> None:
        self._changed.clear()

    def handle_message(self, message_type: str, key: str, payload: str) -> None:
        if message_type == "button" and key == "start":
            self.press_start()
            return
        if message_type == "sensor" and key == "charger_state":
            self.update_value(key, payload)
            return
        if message_type == "control":
            self.update_value(key, payload)

    def press_start(self) -> None:
        with self._lock:
            self._snapshot.start_requests += 1
            self._mark_changed_locked()

    def consume_start_requests(self) -> int:
        with self._lock:
            count = self._snapshot.start_requests
            self._snapshot.start_requests = 0
            return count

    def update_value(self, key: str, payload: str) -> bool:
        parser = _STORE_PARSERS.get(key)
        if parser is None:
            raise HomeAssistantApiError(f"Unsupported MQTT field '{key}'.")
        parsed = parser(payload)
        with self._lock:
            current = getattr(self._snapshot, key)
            if current == parsed:
                return False
            setattr(self._snapshot, key, parsed)
            self._mark_changed_locked()
            return True

    def set_internal_value(self, key: str, value: Any) -> bool:
        with self._lock:
            current = getattr(self._snapshot, key)
            if current == value:
                return False
            setattr(self._snapshot, key, value)
            self._mark_changed_locked()
            return True

    def _mark_changed_locked(self) -> None:
        self._version += 1
        self._changed.set()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def load_options(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.load(path.open("r", encoding="utf-8"))


def validate_config(config: AppConfig) -> list[str]:
    missing_fields = []
    if not config.mqtt_host.strip():
        missing_fields.append("mqtt_host")
    return missing_fields


def wait_for_shutdown() -> int:
    stop_requested = False

    def handle_shutdown(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    while not stop_requested:
        time.sleep(1)
    return 0


def next_scheduled_run(current_time: datetime) -> datetime:
    aligned = current_time.replace(second=0, microsecond=0)
    for minute in RUN_MINUTES:
        candidate = aligned.replace(minute=minute)
        if candidate > current_time:
            return candidate
    return (aligned.replace(minute=RUN_MINUTES[0]) + timedelta(hours=1)).replace(
        second=0,
        microsecond=0,
    )


def create_mqtt_publisher(
    config: AppConfig,
    logger: logging.Logger,
    store: MqttStateStore | None = None,
) -> MQTTOutputPublisher:
    publisher = MQTTOutputPublisher(
        host=config.mqtt_host,
        port=config.mqtt_port,
        username=config.mqtt_username or None,
        password=config.mqtt_password or None,
        discovery_prefix=config.mqtt_discovery_prefix,
        topic_prefix=config.mqtt_topic_prefix,
        logger=logger,
    )
    if store is not None:
        publisher.set_message_handler(store.handle_message)
    return publisher


def should_run_calculation(
    current_time: datetime,
    last_calculation_time: datetime | None,
) -> bool:
    if current_time.minute not in RUN_MINUTES:
        return False
    if last_calculation_time is None:
        return True
    return last_calculation_time.replace(second=0, microsecond=0) != current_time.replace(
        second=0,
        microsecond=0,
    )


def load_execution_state(snapshot: RuntimeSnapshot, *, now: datetime) -> ExecutionState:
    return ExecutionState(
        cable=CABLE_PLUGGED if snapshot.cable_connected else CABLE_UNPLUGGED,
        current_soc=_try_parse_percentage(snapshot.current_soc, "current_soc"),
        target_soc=_try_parse_percentage(snapshot.target_soc, "target_soc"),
        finish_by=_try_parse_finish_by(snapshot.finish_by, now),
        charger_enabled=snapshot.charger_state,
        schedule_authorized=snapshot.schedule_authorized,
        charger_command=snapshot.charger_command,
    )


def should_unlock_schedule(state: ExecutionState, *, now: datetime) -> bool:
    if state.current_soc is not None and state.target_soc is not None and state.current_soc >= state.target_soc:
        return True
    return bool(state.finish_by and now >= state.finish_by)


def derive_charge_window(
    published_payload: dict[str, Any] | None,
    *,
    now: datetime,
) -> str | None:
    if not published_payload:
        return None

    start = str(published_payload.get("start", "")).strip()
    end = str(published_payload.get("end", "")).strip()
    timestamp = str(published_payload.get("timestamp", "")).strip()
    if not start or not end or not timestamp or start == NO_SCHEDULE_TIME or end == NO_SCHEDULE_TIME:
        return None

    start_at = resolve_schedule_start(start=start, timestamp=timestamp, now=now)
    end_at = resolve_schedule_end(start=start, end=end, timestamp=timestamp, now=now)
    if now < start_at:
        return WINDOW_NOT_REACHED
    if now <= end_at:
        return WINDOW_IN_WINDOW
    return WINDOW_PAST_WINDOW


def evaluate_runtime_state(
    *,
    state: ExecutionState,
    now: datetime,
    published_payload: dict[str, Any] | None,
) -> tuple[StateMachineDecision, str | None]:
    charge_window = derive_charge_window(published_payload, now=now)
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=state.cable,
            authorized=state.schedule_authorized,
            charging=state.charger_enabled,
            soc_reached=(
                state.current_soc is not None
                and state.target_soc is not None
                and state.current_soc >= state.target_soc
            ),
            charge_window=charge_window,
        )
    )
    return decision, charge_window


def perform_calculation(snapshot: RuntimeSnapshot, *, now: datetime) -> dict[str, Any]:
    return calculate_result(load_live_inputs_from_snapshot(snapshot), now=now)


def run_calculation_with_error_handling(snapshot: RuntimeSnapshot, *, now: datetime) -> dict[str, Any]:
    try:
        return perform_calculation(snapshot, now=now)
    except HomeAssistantApiError as exc:
        return build_error_result(str(exc), now=now)


def build_output_payload(
    payload: dict[str, Any],
    *,
    finish_by: datetime | None,
    schedule_authorized: bool,
    charger_enabled: bool,
    charger_command: bool,
    current_soc: float | None,
    target_soc: float | None,
    soc_at_charge_start: float | None,
    cable_state: str | None = None,
    charge_window_state: str | None = None,
    lock_calculation: bool | None = None,
    status: str | None = None,
    status_message: str = "Ready",
    status_level: int = 0,
) -> dict[str, Any]:
    output_payload = dict(payload)
    if status is not None:
        output_payload["status"] = status
    output_payload["complete_by"] = finish_by.strftime("%H:%M") if finish_by else ""
    output_payload["authorization_enabled"] = schedule_authorized
    output_payload["charger_enabled"] = charger_enabled
    output_payload["charger_command"] = charger_command
    output_payload["soc_at_charge_start"] = _format_soc_value(soc_at_charge_start)
    output_payload["current_soc"] = _format_soc_value(current_soc)
    output_payload["target_soc"] = _format_soc_value(target_soc)
    output_payload["cable_state"] = cable_state or ""
    output_payload["charge_window_state"] = charge_window_state or ""
    output_payload["status_message"] = status_message
    output_payload["status_level"] = status_level
    output_payload["lock_calculation"] = (
        lock_calculation
        if lock_calculation is not None
        else bool(output_payload.get("lock_calculation", False))
    )
    return output_payload


def is_schedule_due(result_payload: dict[str, Any] | None, *, now: datetime) -> bool:
    if not result_payload:
        return False

    start = str(result_payload.get("start", "")).strip()
    timestamp = str(result_payload.get("timestamp", "")).strip()
    if not start or not timestamp or start == NO_SCHEDULE_TIME:
        return False
    return now >= resolve_schedule_start(start=start, timestamp=timestamp, now=now)


def resolve_schedule_start(*, start: str, timestamp: str, now: datetime) -> datetime:
    try:
        created_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HomeAssistantApiError(f"Could not parse result payload timestamp: {timestamp}") from exc

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    created_at = created_at.astimezone(now.tzinfo)

    parsed_start: datetime | None = None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_start = datetime.strptime(start, fmt)
            break
        except ValueError:
            continue
    if parsed_start is None:
        raise HomeAssistantApiError(f"Could not parse result payload start time: {start}")

    scheduled_start = created_at.replace(
        hour=parsed_start.hour,
        minute=parsed_start.minute,
        second=0,
        microsecond=0,
    )
    if scheduled_start < created_at:
        scheduled_start += timedelta(days=1)
    return scheduled_start


def resolve_schedule_end(*, start: str, end: str, timestamp: str, now: datetime) -> datetime:
    start_at = resolve_schedule_start(start=start, timestamp=timestamp, now=now)
    end_at = _resolve_schedule_clock(end=end, timestamp=timestamp, now=now)
    if end_at <= start_at:
        end_at += timedelta(days=1)
    return end_at


def _resolve_schedule_clock(*, end: str, timestamp: str, now: datetime) -> datetime:
    try:
        created_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HomeAssistantApiError(f"Could not parse result payload timestamp: {timestamp}") from exc

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    created_at = created_at.astimezone(now.tzinfo)

    parsed_end: datetime | None = None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_end = datetime.strptime(end, fmt)
            break
        except ValueError:
            continue
    if parsed_end is None:
        raise HomeAssistantApiError(f"Could not parse result payload end time: {end}")

    return created_at.replace(
        hour=parsed_end.hour,
        minute=parsed_end.minute,
        second=0,
        microsecond=0,
    )


def process_runtime_tick(
    *,
    store: MqttStateStore,
    publisher: MQTTOutputPublisher,
    logger: logging.Logger,
    now: datetime,
    memory: RuntimeMemory,
    force_recalculate: bool,
) -> TickResult:
    snapshot = store.snapshot()
    state = load_execution_state(snapshot, now=now)
    soc_at_charge_start = _resolve_soc_at_charge_start(
        existing_value=memory.soc_at_charge_start,
        published_payload=memory.published_payload,
        state=state,
    )
    if _did_cable_transition_to_plugged(memory.published_payload, state):
        soc_at_charge_start = state.current_soc

    completion_time = _update_completion_time(
        previous_completion=memory.completion_time,
        previous_charger_enabled=memory.last_charger_enabled,
        state=state,
        now=now,
    )

    _apply_start_requests(
        store=store,
        publisher=publisher,
        state=state,
        now=now,
        published_payload=memory.published_payload,
        logger=logger,
    )
    snapshot = store.snapshot()
    state = load_execution_state(snapshot, now=now)

    previous_status = str((memory.published_payload or {}).get("status", "OK"))
    previous_lock = bool((memory.published_payload or {}).get("lock_calculation", False))
    previous_rule = str((memory.published_payload or {}).get("state_machine_rule", ""))

    decision, charge_window = evaluate_runtime_state(
        state=state,
        now=now,
        published_payload=memory.published_payload,
    )
    effective_status = decision.status or previous_status
    effective_lock = (
        decision.lock_calculation
        if decision.lock_calculation is not None
        else previous_lock
    )
    effective_rule = decision.rule or previous_rule
    _apply_state_machine_decision(
        store=store,
        publisher=publisher,
        state=state,
        decision=decision,
        logger=logger,
    )

    snapshot = store.snapshot()
    state = load_execution_state(snapshot, now=now)
    charge_window = derive_charge_window(memory.published_payload, now=now)

    if not effective_lock and (force_recalculate or should_run_calculation(now, memory.last_calculation_time)):
        calculation_payload = run_calculation_with_error_handling(snapshot, now=now)
        memory.last_calculation_time = now
        if str(calculation_payload.get("status", "")) != "ok":
            logger.error("Calculation failed: %s", calculation_payload["status"])
        memory.published_payload = calculation_payload
        if calculation_payload.get("start") != NO_SCHEDULE_TIME:
            completion_time = None

        decision, charge_window = evaluate_runtime_state(
            state=state,
            now=now,
            published_payload=memory.published_payload,
        )
        effective_status = decision.status or str(memory.published_payload.get("status", effective_status))
        effective_lock = (
            decision.lock_calculation
            if decision.lock_calculation is not None
            else bool(memory.published_payload.get("lock_calculation", effective_lock))
        )
        effective_rule = decision.rule or effective_rule
        _apply_state_machine_decision(
            store=store,
            publisher=publisher,
            state=state,
            decision=decision,
            logger=logger,
        )
        snapshot = store.snapshot()
        state = load_execution_state(snapshot, now=now)

    base_payload = memory.published_payload or build_error_result("No schedule calculated.", now=now)
    base_payload["state_machine_rule"] = effective_rule
    status_details = derive_status_details(
        state=state,
        published_payload=base_payload,
        now=now,
        completion_time=completion_time,
    )
    output_payload = build_output_payload(
        base_payload,
        finish_by=state.finish_by,
        schedule_authorized=state.schedule_authorized,
        charger_enabled=state.charger_enabled,
        charger_command=state.charger_command,
        current_soc=state.current_soc,
        target_soc=state.target_soc,
        soc_at_charge_start=soc_at_charge_start,
        cable_state=state.cable,
        charge_window_state=charge_window,
        lock_calculation=effective_lock,
        status=effective_status,
        status_message=status_details.message,
        status_level=status_details.level,
    )
    publisher.publish_runtime_state(snapshot=snapshot, payload=output_payload)
    if _should_log_charge_progress(now=now, state=state):
        logger.info("Charge progress over MQTT: %s", output_payload)

    return TickResult(
        last_calculation_time=memory.last_calculation_time,
        soc_at_charge_start=soc_at_charge_start,
        published_payload=output_payload,
        completion_time=status_details.completion_time,
        last_charger_enabled=state.charger_enabled,
    )


def run_scheduler(
    *,
    publisher: MQTTOutputPublisher,
    store: MqttStateStore,
    logger: logging.Logger,
) -> int:
    stop_requested = False

    def handle_shutdown(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        store.clear_change_flag()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    publisher.start()
    memory = RuntimeMemory()

    startup_time = datetime.now().astimezone().replace(second=0, microsecond=0)
    tick_result = process_runtime_tick(
        store=store,
        publisher=publisher,
        logger=logger,
        now=startup_time,
        memory=memory,
        force_recalculate=True,
    )
    memory.last_calculation_time = tick_result.last_calculation_time
    memory.soc_at_charge_start = tick_result.soc_at_charge_start
    memory.published_payload = tick_result.published_payload
    memory.completion_time = tick_result.completion_time
    memory.last_charger_enabled = tick_result.last_charger_enabled

    while not stop_requested:
        current_time = datetime.now().astimezone()
        next_tick = current_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
        timeout = max((next_tick - current_time).total_seconds(), 0.0)
        changed = store.wait_for_change(timeout)
        store.clear_change_flag()
        if stop_requested:
            break

        tick_time = datetime.now().astimezone().replace(second=0, microsecond=0)
        try:
            tick_result = process_runtime_tick(
                store=store,
                publisher=publisher,
                logger=logger,
                now=tick_time,
                memory=memory,
                force_recalculate=changed,
            )
            memory.last_calculation_time = tick_result.last_calculation_time
            memory.soc_at_charge_start = tick_result.soc_at_charge_start
            memory.published_payload = tick_result.published_payload
            memory.completion_time = tick_result.completion_time
            memory.last_charger_enabled = tick_result.last_charger_enabled
        except HomeAssistantApiError as exc:
            logger.error("Minute execution tick failed: %s", exc)

    publisher.stop()
    return 0


def main() -> int:
    options_path = Path(os.getenv("OPTIONS_PATH", DEFAULT_OPTIONS_PATH))
    raw_options = load_options(options_path)
    config = AppConfig.from_mapping(raw_options)

    configure_logging(config.log_level)
    logger = logging.getLogger("evcc")

    logger.info("Starting EV Charge Control")
    logger.info("Using options file: %s", options_path)

    missing_fields = validate_config(config)
    if missing_fields:
        logger.warning("Configuration is incomplete. Missing required options: %s", ", ".join(missing_fields))
        return wait_for_shutdown()

    store = MqttStateStore()
    publisher = create_mqtt_publisher(config, logger, store)
    logger.info("EV Charge Control service is running.")
    return run_scheduler(publisher=publisher, store=store, logger=logger)


def load_live_inputs_from_snapshot(snapshot: RuntimeSnapshot) -> LiveInputs:
    pricing_payload = _parse_pricing_payload(snapshot.pricing_information)
    return LiveInputs(
        ev_current_soc=snapshot.current_soc,
        target_soc=snapshot.target_soc,
        ev_battery_capacity=snapshot.battery_capacity,
        charger_speed=snapshot.charger_speed,
        charge_loss=snapshot.charge_loss,
        finish_by=snapshot.finish_by,
        nighttime_charging_only=snapshot.nighttime_charging_only,
        pricing_information=pricing_payload,
    )


def derive_status_details(
    *,
    state: ExecutionState,
    published_payload: dict[str, Any],
    now: datetime,
    completion_time: str | None,
) -> StatusDetails:
    status = str(published_payload.get("status", "ok"))
    if status != "ok":
        return StatusDetails(status, 100, completion_time)

    start = str(published_payload.get("start", "")).strip()
    end = str(published_payload.get("end", "")).strip()
    timestamp = str(published_payload.get("timestamp", "")).strip()
    if state.charger_enabled and start and end and timestamp and end != NO_SCHEDULE_TIME:
        end_at = resolve_schedule_end(start=start, end=end, timestamp=timestamp, now=now)
        remaining = _format_countdown(max(end_at - now, timedelta()))
        return StatusDetails(f"Charge session active - expected finish in {remaining}", 20, None)

    charge_window = derive_charge_window(published_payload, now=now)
    if (
        charge_window == WINDOW_NOT_REACHED
        and state.schedule_authorized
        and start
        and start != NO_SCHEDULE_TIME
        and timestamp
    ):
        start_at = resolve_schedule_start(start=start, timestamp=timestamp, now=now)
        remaining = _format_countdown(max(start_at - now, timedelta()))
        return StatusDetails(f"Charge session planned - expected start in {remaining}", 10, None)

    if completion_time and not state.charger_enabled and state.current_soc is not None and state.target_soc is not None:
        if state.current_soc >= state.target_soc:
            return StatusDetails(f"Charge session completed at {completion_time}", 10, completion_time)

    if (
        state.cable == CABLE_PLUGGED
        and state.current_soc is not None
        and state.target_soc is not None
        and state.current_soc < state.target_soc
        and not state.schedule_authorized
        and not state.charger_enabled
    ):
        return StatusDetails(
            "Automatic charging is disabled. Press Start to begin.",
            50,
            None,
        )

    if state.cable == CABLE_UNPLUGGED:
        return StatusDetails("Ready", 0, None)
    return StatusDetails("Ready", 0, None)


def _apply_start_requests(
    *,
    store: MqttStateStore,
    publisher: MQTTOutputPublisher,
    state: ExecutionState,
    now: datetime,
    published_payload: dict[str, Any] | None,
    logger: logging.Logger,
) -> None:
    presses = store.consume_start_requests()
    if presses <= 0:
        return
    _set_control_value(store, publisher, "schedule_authorized", True)
    logger.info("Received MQTT Start button press; authorization enabled.")
    charge_window = derive_charge_window(published_payload, now=now)
    if (
        state.cable == CABLE_PLUGGED
        and state.current_soc is not None
        and state.target_soc is not None
        and state.current_soc < state.target_soc
        and charge_window == WINDOW_IN_WINDOW
    ):
        _set_control_value(store, publisher, "charger_command", True)
        logger.info("Start button triggered charger command because the session is already in window.")


def _apply_state_machine_decision(
    *,
    store: MqttStateStore,
    publisher: MQTTOutputPublisher,
    state: ExecutionState,
    decision: StateMachineDecision,
    logger: logging.Logger,
) -> None:
    if decision.set_authorized is not None and decision.set_authorized != state.schedule_authorized:
        _set_control_value(store, publisher, "schedule_authorized", decision.set_authorized)
        logger.info("State machine set authorization to %s.", decision.set_authorized)
    if decision.set_charging is not None and decision.set_charging != state.charger_command:
        _set_control_value(store, publisher, "charger_command", decision.set_charging)
        logger.info("State machine set charger command to %s.", decision.set_charging)


def _resolve_soc_at_charge_start(
    *,
    existing_value: float | None,
    published_payload: dict[str, Any] | None,
    state: ExecutionState,
) -> float | None:
    if existing_value is not None:
        return existing_value

    payload_value = None if published_payload is None else published_payload.get("soc_at_charge_start")
    if payload_value in {"", None}:
        return state.current_soc if state.charger_enabled else None

    try:
        return float(payload_value)
    except (TypeError, ValueError):
        return state.current_soc if state.charger_enabled else None


def _did_cable_transition_to_plugged(
    published_payload: dict[str, Any] | None,
    state: ExecutionState,
) -> bool:
    previous_cable_state = str((published_payload or {}).get("cable_state", ""))
    return previous_cable_state == CABLE_UNPLUGGED and state.cable == CABLE_PLUGGED


def _update_completion_time(
    *,
    previous_completion: str | None,
    previous_charger_enabled: bool | None,
    state: ExecutionState,
    now: datetime,
) -> str | None:
    if state.cable == CABLE_UNPLUGGED:
        return None
    if state.current_soc is not None and state.target_soc is not None and state.current_soc < state.target_soc:
        previous_completion = None
    if (
        previous_charger_enabled is True
        and not state.charger_enabled
        and state.current_soc is not None
        and state.target_soc is not None
        and state.current_soc >= state.target_soc
    ):
        return now.strftime("%H:%M")
    return previous_completion


def _should_log_charge_progress(*, now: datetime, state: ExecutionState) -> bool:
    return state.charger_enabled and now.minute % 15 == 0


def _set_control_value(
    store: MqttStateStore,
    publisher: MQTTOutputPublisher,
    key: str,
    value: Any,
) -> None:
    if store.set_internal_value(key, value):
        publisher.publish_control_state(key, value)


def _format_countdown(duration: timedelta) -> str:
    total_minutes = max(int(duration.total_seconds() // 60), 0)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def _parse_pricing_payload(raw: str | None) -> PricingPayload:
    if raw is None or not str(raw).strip():
        raise HomeAssistantApiError("Missing value for 'pricing_information'.")
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise HomeAssistantApiError("Could not parse pricing_information JSON.") from exc
    if not isinstance(payload, dict):
        raise HomeAssistantApiError("pricing_information must be a JSON object.")

    raw_today = payload.get("raw_today")
    raw_tomorrow = payload.get("raw_tomorrow")
    forecast = payload.get("forecast")
    if not isinstance(raw_today, list):
        raise HomeAssistantApiError("pricing_information.raw_today must be a list.")
    if raw_tomorrow is not None and not isinstance(raw_tomorrow, list):
        raise HomeAssistantApiError("pricing_information.raw_tomorrow must be a list or null.")
    if forecast is not None and not isinstance(forecast, list):
        raise HomeAssistantApiError("pricing_information.forecast must be a list or null.")

    return PricingPayload(
        raw_today=raw_today,
        raw_tomorrow=raw_tomorrow,
        forecast=forecast,
    )


def _parse_mqtt_port(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MQTT_PORT
    if parsed <= 0 or parsed > 65535:
        return DEFAULT_MQTT_PORT
    return parsed


def _try_parse_percentage(value: str | None, field_name: str) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return parse_percentage_value(value, field_name)
    except HomeAssistantApiError:
        return None


def _try_parse_finish_by(value: str | None, now: datetime) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        return parse_finish_by_value(value, now)
    except HomeAssistantApiError:
        return None


def _format_soc_value(value: float | None) -> int | float | str:
    if value is None:
        return ""
    if float(value).is_integer():
        return int(value)
    return round(value, 3)


def _parse_switch_payload(payload: str) -> bool:
    normalized = str(payload).strip().lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no"}:
        return False
    raise HomeAssistantApiError(f"Invalid switch payload: {payload}")


def _parse_percentage_payload(payload: str) -> str:
    parsed = parse_percentage_value(payload, "percentage")
    return _format_number_string(parsed)


def _parse_positive_number_payload(payload: str) -> str:
    normalized = str(payload).strip()
    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise HomeAssistantApiError(f"Invalid numeric payload: {payload}") from exc
    if parsed <= 0:
        raise HomeAssistantApiError(f"Numeric payload must be greater than zero: {payload}")
    return _format_number_string(parsed)


def _parse_finish_by_payload(payload: str) -> str:
    parsed = parse_finish_by_value(payload, datetime.now().astimezone())
    return parsed.strftime("%H:%M")


def _parse_pricing_payload_text(payload: str) -> str:
    parsed = _parse_pricing_payload(payload)
    return json.dumps(
        {
            "raw_today": parsed.raw_today,
            "raw_tomorrow": parsed.raw_tomorrow,
            "forecast": parsed.forecast,
        },
        separators=(",", ":"),
    )


def _format_number_string(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(round(value, 3))


_STORE_PARSERS: dict[str, Any] = {
    "current_soc": _parse_percentage_payload,
    "target_soc": _parse_percentage_payload,
    "battery_capacity": _parse_positive_number_payload,
    "charger_speed": _parse_positive_number_payload,
    "charge_loss": _parse_percentage_payload,
    "finish_by": _parse_finish_by_payload,
    "nighttime_charging_only": _parse_switch_payload,
    "cable_connected": _parse_switch_payload,
    "schedule_authorized": _parse_switch_payload,
    "charger_state": _parse_switch_payload,
    "charger_command": _parse_switch_payload,
    "pricing_information": _parse_pricing_payload_text,
}
