from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from evcc.ha_api import HomeAssistantApiError, HomeAssistantClient
from evcc.mqtt_output import MQTTOutputPublisher
from evcc.runtime import (
    build_error_result,
    calculate_result,
    load_live_inputs,
    parse_finish_by_value,
    parse_input_boolean_value,
    parse_percentage_value,
)


DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_HOME_ASSISTANT_API_URL = "http://supervisor/core/api"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_MQTT_TOPIC_PREFIX = "ev_charge_control"
RUN_MINUTES = (1, 16, 31, 46)
SUPPORTED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


@dataclass(slots=True)
class AppConfig:
    log_level: str = DEFAULT_LOG_LEVEL
    ev_current_soc_entity: str = ""
    target_soc_entity: str = ""
    ev_battery_capacity_entity: str = ""
    charger_speed_entity: str = ""
    charge_loss_entity: str = ""
    finish_by_entity: str = ""
    nighttime_charging_only_entity: str = ""
    charger_control_switch_entity: str = ""
    schedule_authorized_entity: str = ""
    pricing_information_entity: str = ""
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
class ExecutionState:
    current_soc: float
    target_soc: float
    finish_by: datetime
    charger_enabled: bool
    schedule_authorized: bool


@dataclass(slots=True)
class TickResult:
    last_calculation_time: datetime | None
    soc_at_charge_start: float | None
    published_payload: dict[str, Any] | None


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def load_options(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return __import__("json").load(path.open("r", encoding="utf-8"))


def validate_config(config: AppConfig) -> list[str]:
    missing_fields = []
    required_fields = (
        "ev_current_soc_entity",
        "target_soc_entity",
        "ev_battery_capacity_entity",
        "charger_speed_entity",
        "charge_loss_entity",
        "finish_by_entity",
        "nighttime_charging_only_entity",
        "charger_control_switch_entity",
        "schedule_authorized_entity",
        "pricing_information_entity",
        "mqtt_host",
    )
    for field_name in required_fields:
        value = getattr(config, field_name)
        if isinstance(value, str) and not value.strip():
            missing_fields.append(field_name)
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


def create_home_assistant_client() -> HomeAssistantClient | None:
    token = os.getenv("SUPERVISOR_TOKEN", "").strip()
    if not token:
        return None
    base_url = os.getenv("HOME_ASSISTANT_API_URL", DEFAULT_HOME_ASSISTANT_API_URL)
    return HomeAssistantClient(base_url=base_url, token=token)


def create_mqtt_publisher(config: AppConfig, logger: logging.Logger) -> MQTTOutputPublisher:
    return MQTTOutputPublisher(
        host=config.mqtt_host,
        port=config.mqtt_port,
        username=config.mqtt_username or None,
        password=config.mqtt_password or None,
        discovery_prefix=config.mqtt_discovery_prefix,
        topic_prefix=config.mqtt_topic_prefix,
        logger=logger,
    )


def perform_api_cycle(
    *,
    client: HomeAssistantClient,
    publisher: MQTTOutputPublisher,
    config: AppConfig,
    logger: logging.Logger,
    now: datetime | None = None,
    soc_at_charge_start: float | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now().astimezone()
    execution_state = load_execution_state(client, config, now=current_time)
    live_inputs = load_live_inputs(client, config)
    logger.info(
        "Loaded live inputs from Home Assistant: current_soc=%s target_soc=%s "
        "battery_capacity=%s charger_speed=%s charge_loss=%s finish_by=%s "
        "nighttime_charging_only=%s",
        live_inputs.ev_current_soc,
        live_inputs.target_soc,
        live_inputs.ev_battery_capacity,
        live_inputs.charger_speed,
        live_inputs.charge_loss,
        live_inputs.finish_by,
        live_inputs.nighttime_charging_only,
    )
    logger.debug(
        "Loaded pricing payload from Home Assistant: raw_today=%s raw_tomorrow=%s forecast=%s",
        live_inputs.pricing_information.raw_today,
        live_inputs.pricing_information.raw_tomorrow,
        live_inputs.pricing_information.forecast,
    )

    result_payload = calculate_result(live_inputs, now=current_time)
    output_payload = build_output_payload(
        result_payload,
        finish_by=execution_state.finish_by,
        schedule_authorized=execution_state.schedule_authorized,
        charger_enabled=execution_state.charger_enabled,
        current_soc=execution_state.current_soc,
        target_soc=execution_state.target_soc,
        soc_at_charge_start=soc_at_charge_start,
    )
    publisher.publish_output(output_payload)
    logger.info("Published charging result over MQTT: %s", output_payload)
    return output_payload


def run_api_cycle_with_error_handling(
    *,
    client: HomeAssistantClient,
    publisher: MQTTOutputPublisher,
    config: AppConfig,
    logger: logging.Logger,
    now: datetime | None = None,
    soc_at_charge_start: float | None = None,
) -> dict[str, Any]:
    try:
        return perform_api_cycle(
            client=client,
            publisher=publisher,
            config=config,
            logger=logger,
            now=now,
            soc_at_charge_start=soc_at_charge_start,
        )
    except HomeAssistantApiError as exc:
        logger.error("Home Assistant API cycle failed: %s", exc)
        error_payload = build_error_result(str(exc), now=now)
        output_payload = enrich_payload_from_current_state(
            client=client,
            config=config,
            payload=error_payload,
            now=now or datetime.now().astimezone(),
            soc_at_charge_start=soc_at_charge_start,
        )
        publisher.publish_output(output_payload)
        logger.info("Published API error status over MQTT.")
        return output_payload


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


def load_execution_state(
    client: HomeAssistantClient,
    config: AppConfig,
    *,
    now: datetime,
) -> ExecutionState:
    return ExecutionState(
        current_soc=parse_percentage_value(
            client.get_entity_value(config.ev_current_soc_entity),
            "ev_current_soc",
        ),
        target_soc=parse_percentage_value(
            client.get_entity_value(config.target_soc_entity),
            "target_soc",
        ),
        finish_by=parse_finish_by_value(
            client.get_entity_value(config.finish_by_entity),
            now,
        ),
        charger_enabled=_parse_switch_state(
            client.get_entity_value(config.charger_control_switch_entity),
            "charger_control_switch_entity",
        ),
        schedule_authorized=parse_input_boolean_value(
            client.get_entity_value(config.schedule_authorized_entity),
            "schedule_authorized_entity",
        ),
    )


def should_unlock_schedule(state: ExecutionState, *, now: datetime) -> bool:
    return state.current_soc >= state.target_soc or now >= state.finish_by


def build_output_payload(
    payload: dict[str, Any],
    *,
    finish_by: datetime | None,
    schedule_authorized: bool,
    charger_enabled: bool,
    current_soc: float | None,
    target_soc: float | None,
    soc_at_charge_start: float | None,
) -> dict[str, Any]:
    output_payload = dict(payload)
    output_payload["complete_by"] = finish_by.strftime("%H:%M") if finish_by else ""
    output_payload["authorization_enabled"] = schedule_authorized
    output_payload["charger_enabled"] = charger_enabled
    output_payload["soc_at_charge_start"] = _format_soc_value(soc_at_charge_start)
    output_payload["current_soc"] = _format_soc_value(current_soc)
    output_payload["target_soc"] = _format_soc_value(target_soc)
    return output_payload


def enrich_payload_from_current_state(
    *,
    client: HomeAssistantClient,
    config: AppConfig,
    payload: dict[str, Any],
    now: datetime,
    soc_at_charge_start: float | None,
) -> dict[str, Any]:
    try:
        state = load_execution_state(client, config, now=now)
    except HomeAssistantApiError:
        return build_output_payload(
            payload,
            finish_by=None,
            schedule_authorized=False,
            charger_enabled=False,
            current_soc=None,
            target_soc=None,
            soc_at_charge_start=soc_at_charge_start,
        )

    return build_output_payload(
        payload,
        finish_by=state.finish_by,
        schedule_authorized=state.schedule_authorized,
        charger_enabled=state.charger_enabled,
        current_soc=state.current_soc,
        target_soc=state.target_soc,
        soc_at_charge_start=soc_at_charge_start,
    )


def is_schedule_due(result_payload: dict[str, Any] | None, *, now: datetime) -> bool:
    if not result_payload:
        return False

    status = str(result_payload.get("status", "")).strip().lower()
    start = str(result_payload.get("start", "")).strip()
    timestamp = str(result_payload.get("timestamp", "")).strip()
    if status != "ok" or not start or not timestamp:
        return False

    return now >= resolve_schedule_start(start=start, timestamp=timestamp, now=now)


def resolve_schedule_start(*, start: str, timestamp: str, now: datetime) -> datetime:
    try:
        created_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HomeAssistantApiError(
            f"Could not parse result payload timestamp: {timestamp}"
        ) from exc

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


def execute_due_schedule(
    *,
    client: HomeAssistantClient,
    config: AppConfig,
    logger: logging.Logger,
) -> None:
    client.turn_on_switch(config.charger_control_switch_entity)
    client.turn_off_input_boolean(config.schedule_authorized_entity)
    logger.info(
        "Started charging via switch '%s' and disabled authorization helper '%s'.",
        config.charger_control_switch_entity,
        config.schedule_authorized_entity,
    )


def process_minute_tick(
    *,
    client: HomeAssistantClient,
    publisher: MQTTOutputPublisher,
    config: AppConfig,
    logger: logging.Logger,
    now: datetime,
    last_calculation_time: datetime | None,
    soc_at_charge_start: float | None,
    published_payload: dict[str, Any] | None,
) -> TickResult:
    state = load_execution_state(client, config, now=now)
    soc_at_charge_start = _resolve_soc_at_charge_start(
        existing_value=soc_at_charge_start,
        published_payload=published_payload,
        state=state,
    )

    if state.charger_enabled and not should_unlock_schedule(state, now=now):
        published_payload = write_runtime_output(
            publisher=publisher,
            state=state,
            now=now,
            soc_at_charge_start=soc_at_charge_start,
            published_payload=published_payload,
        )
        logger.info(
            "Charger switch '%s' is on; schedule updates remain locked.",
            config.charger_control_switch_entity,
        )
        return TickResult(last_calculation_time, soc_at_charge_start, published_payload)

    if should_run_calculation(now, last_calculation_time):
        published_payload = run_api_cycle_with_error_handling(
            client=client,
            publisher=publisher,
            config=config,
            logger=logger,
            now=now,
            soc_at_charge_start=soc_at_charge_start,
        )
        last_calculation_time = now
        state = load_execution_state(client, config, now=now)
        soc_at_charge_start = _resolve_soc_at_charge_start(
            existing_value=soc_at_charge_start,
            published_payload=published_payload,
            state=state,
        )

    if state.charger_enabled:
        published_payload = write_runtime_output(
            publisher=publisher,
            state=state,
            now=now,
            soc_at_charge_start=soc_at_charge_start,
            published_payload=published_payload,
        )
        logger.debug(
            "Charger switch '%s' is on but schedule lock has been released.",
            config.charger_control_switch_entity,
        )
        return TickResult(last_calculation_time, soc_at_charge_start, published_payload)

    if not state.schedule_authorized:
        published_payload = write_runtime_output(
            publisher=publisher,
            state=state,
            now=now,
            soc_at_charge_start=soc_at_charge_start,
            published_payload=published_payload,
        )
        return TickResult(last_calculation_time, soc_at_charge_start, published_payload)

    if is_schedule_due(published_payload, now=now):
        soc_at_charge_start = state.current_soc
        execute_due_schedule(client=client, config=config, logger=logger)
        state = load_execution_state(client, config, now=now)

    published_payload = write_runtime_output(
        publisher=publisher,
        state=state,
        now=now,
        soc_at_charge_start=soc_at_charge_start,
        published_payload=published_payload,
    )
    return TickResult(last_calculation_time, soc_at_charge_start, published_payload)


def run_scheduler(
    *,
    client: HomeAssistantClient,
    publisher: MQTTOutputPublisher,
    config: AppConfig,
    logger: logging.Logger,
) -> int:
    stop_requested = False

    def handle_shutdown(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    publisher.start()

    startup_time = datetime.now().astimezone().replace(second=0, microsecond=0)
    published_payload = run_api_cycle_with_error_handling(
        client=client,
        publisher=publisher,
        config=config,
        logger=logger,
        now=startup_time,
    )
    last_calculation_time: datetime | None = startup_time
    soc_at_charge_start: float | None = None
    try:
        state = load_execution_state(client, config, now=startup_time)
        soc_at_charge_start = _resolve_soc_at_charge_start(
            existing_value=None,
            published_payload=published_payload,
            state=state,
        )
        if (
            not state.charger_enabled
            and state.schedule_authorized
            and is_schedule_due(published_payload, now=startup_time)
        ):
            soc_at_charge_start = state.current_soc
            execute_due_schedule(client=client, config=config, logger=logger)
            state = load_execution_state(client, config, now=startup_time)
        published_payload = write_runtime_output(
            publisher=publisher,
            state=state,
            now=startup_time,
            soc_at_charge_start=soc_at_charge_start,
            published_payload=published_payload,
        )
    except HomeAssistantApiError as exc:
        logger.error("Execution check failed at startup: %s", exc)

    while not stop_requested:
        current_time = datetime.now().astimezone()
        logger.info("Next calculation scheduled for %s", next_scheduled_run(current_time).isoformat())
        next_tick = current_time.replace(second=0, microsecond=0) + timedelta(minutes=1)

        while not stop_requested:
            now = datetime.now().astimezone()
            remaining = (next_tick - now).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 1))

        if stop_requested:
            break

        tick_time = datetime.now().astimezone().replace(second=0, microsecond=0)
        try:
            tick_result = process_minute_tick(
                client=client,
                publisher=publisher,
                config=config,
                logger=logger,
                now=tick_time,
                last_calculation_time=last_calculation_time,
                soc_at_charge_start=soc_at_charge_start,
                published_payload=published_payload,
            )
            last_calculation_time = tick_result.last_calculation_time
            soc_at_charge_start = tick_result.soc_at_charge_start
            published_payload = tick_result.published_payload
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
        logger.warning(
            "Configuration is incomplete. Missing required options: %s",
            ", ".join(missing_fields),
        )
    else:
        logger.info("Configuration loaded successfully.")

    client = create_home_assistant_client()
    if client is None:
        logger.error(
            "SUPERVISOR_TOKEN is not available. Home Assistant API integration is disabled."
        )
        return wait_for_shutdown()
    if missing_fields:
        logger.warning("Skipping Home Assistant API cycle until configuration is complete.")
        return wait_for_shutdown()

    publisher = create_mqtt_publisher(config, logger)
    logger.info("EV Charge Control service is running.")
    return run_scheduler(client=client, publisher=publisher, config=config, logger=logger)


def _parse_switch_state(value: str | float | int | None, field_name: str) -> bool:
    if value is None:
        raise HomeAssistantApiError(f"Missing value for '{field_name}'.")
    normalized = str(value).strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False
    raise HomeAssistantApiError(f"Invalid switch state for '{field_name}': {value}")


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


def _format_soc_value(value: float | None) -> float | int | str:
    if value is None:
        return ""
    if float(value).is_integer():
        return int(value)
    return round(value, 3)


def _parse_mqtt_port(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MQTT_PORT
    return parsed if parsed > 0 else DEFAULT_MQTT_PORT


def write_runtime_output(
    *,
    publisher: MQTTOutputPublisher,
    state: ExecutionState,
    now: datetime,
    soc_at_charge_start: float | None,
    published_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    base_payload = published_payload or build_error_result("No schedule calculated.", now=now)
    output_payload = build_output_payload(
        base_payload,
        finish_by=state.finish_by,
        schedule_authorized=state.schedule_authorized,
        charger_enabled=state.charger_enabled,
        current_soc=state.current_soc,
        target_soc=state.target_soc,
        soc_at_charge_start=soc_at_charge_start,
    )
    publisher.publish_output(output_payload)
    return output_payload


if __name__ == "__main__":
    sys.exit(main())
