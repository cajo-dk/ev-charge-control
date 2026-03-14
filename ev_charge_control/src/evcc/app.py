from __future__ import annotations

import json
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
from evcc.runtime import (
    build_error_result,
    calculate_result,
    dump_result_payload,
    load_live_inputs,
)


DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_HOME_ASSISTANT_API_URL = "http://supervisor/core/api"
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
    pricing_information_entity: str = ""
    result_helper_entity: str = ""

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "AppConfig":
        normalized = {key: raw.get(key, "") for key in cls.__dataclass_fields__}
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
        return cls(**normalized)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def load_options(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def validate_config(config: AppConfig) -> list[str]:
    missing_fields = []
    required_fields = (
        "ev_current_soc_entity",
        "target_soc_entity",
        "ev_battery_capacity_entity",
        "charger_speed_entity",
        "charge_loss_entity",
        "finish_by_entity",
        "pricing_information_entity",
        "result_helper_entity",
    )
    for field_name in required_fields:
        if not getattr(config, field_name).strip():
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


def perform_api_cycle(
    *,
    client: HomeAssistantClient,
    config: AppConfig,
    logger: logging.Logger,
    now: datetime | None = None,
) -> None:
    live_inputs = load_live_inputs(client, config)
    logger.info(
        "Loaded live inputs from Home Assistant: current_soc=%s target_soc=%s "
        "battery_capacity=%s charger_speed=%s charge_loss=%s finish_by=%s",
        live_inputs.ev_current_soc,
        live_inputs.target_soc,
        live_inputs.ev_battery_capacity,
        live_inputs.charger_speed,
        live_inputs.charge_loss,
        live_inputs.finish_by,
    )
    logger.debug(
        "Loaded pricing payload from Home Assistant: raw_today=%s raw_tomorrow=%s forecast=%s",
        live_inputs.pricing_information.raw_today,
        live_inputs.pricing_information.raw_tomorrow,
        live_inputs.pricing_information.forecast,
    )

    result_payload = calculate_result(live_inputs, now=now)
    client.set_input_text(
        config.result_helper_entity,
        dump_result_payload(result_payload),
    )
    logger.info(
        "Wrote charging result to helper '%s': %s",
        config.result_helper_entity,
        result_payload,
    )


def run_api_cycle_with_error_handling(
    *,
    client: HomeAssistantClient,
    config: AppConfig,
    logger: logging.Logger,
    now: datetime | None = None,
) -> None:
    try:
        perform_api_cycle(client=client, config=config, logger=logger, now=now)
    except HomeAssistantApiError as exc:
        logger.error("Home Assistant API cycle failed: %s", exc)
        try:
            client.set_input_text(
                config.result_helper_entity,
                dump_result_payload(build_error_result(str(exc), now=now)),
            )
            logger.info(
                "Wrote API error status to helper '%s'.",
                config.result_helper_entity,
            )
        except HomeAssistantApiError as write_exc:
            logger.error("Failed to write API error status to helper: %s", write_exc)


def run_scheduler(
    *,
    client: HomeAssistantClient,
    config: AppConfig,
    logger: logging.Logger,
) -> int:
    stop_requested = False

    def handle_shutdown(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    run_api_cycle_with_error_handling(client=client, config=config, logger=logger)

    while not stop_requested:
        current_time = datetime.now().astimezone()
        scheduled_time = next_scheduled_run(current_time)
        logger.info("Next calculation scheduled for %s", scheduled_time.isoformat())

        while not stop_requested:
            now = datetime.now().astimezone()
            remaining = (scheduled_time - now).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 1))

        if stop_requested:
            break

        run_api_cycle_with_error_handling(client=client, config=config, logger=logger)

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
    elif missing_fields:
        logger.warning("Skipping Home Assistant API cycle until configuration is complete.")
        return wait_for_shutdown()

    logger.info("EV Charge Control service is running.")
    return run_scheduler(client=client, config=config, logger=logger)


if __name__ == "__main__":
    sys.exit(main())
