from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from evcc.ha_api import HomeAssistantApiError, HomeAssistantClient


@dataclass(slots=True)
class PricingPayload:
    raw_today: list[dict[str, Any]]
    raw_tomorrow: list[dict[str, Any]] | None
    forecast: list[dict[str, Any]] | None


@dataclass(slots=True)
class LiveInputs:
    ev_current_soc: str | float | int | None
    target_soc: str | float | int | None
    ev_battery_capacity: str | float | int | None
    charger_speed: str | float | int | None
    charge_loss: str | float | int | None
    finish_by: str | float | int | None
    pricing_information: PricingPayload


def load_live_inputs(client: HomeAssistantClient, config: Any) -> LiveInputs:
    pricing_state = client.get_state(config.pricing_information_entity)
    attributes = pricing_state.get("attributes")
    if not isinstance(attributes, dict):
        raise HomeAssistantApiError("Pricing entity did not contain valid attributes.")

    return LiveInputs(
        ev_current_soc=client.get_entity_value(config.ev_current_soc_entity),
        target_soc=client.get_entity_value(config.target_soc_entity),
        ev_battery_capacity=client.get_entity_value(config.ev_battery_capacity_entity),
        charger_speed=client.get_entity_value(config.charger_speed_entity),
        charge_loss=client.get_entity_value(config.charge_loss_entity),
        finish_by=client.get_entity_value(config.finish_by_entity),
        pricing_information=PricingPayload(
            raw_today=_coerce_price_list(attributes.get("raw_today"), "raw_today"),
            raw_tomorrow=_coerce_optional_price_list(
                attributes.get("raw_tomorrow"), "raw_tomorrow"
            ),
            forecast=_coerce_optional_price_list(attributes.get("forecast"), "forecast"),
        ),
    )


def build_placeholder_result(now: datetime | None = None) -> dict[str, str]:
    timestamp = (now or datetime.now().astimezone()).isoformat()
    return {
        "start": "",
        "end": "",
        "timestamp": timestamp,
        "status": "ok",
    }


def build_error_result(message: str, now: datetime | None = None) -> dict[str, str]:
    payload = build_placeholder_result(now)
    payload["status"] = message[:255]
    return payload


def dump_result_payload(payload: dict[str, str]) -> str:
    return json.dumps(payload)


def _coerce_price_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise HomeAssistantApiError(f"Pricing field '{field_name}' must be a list.")
    return value


def _coerce_optional_price_list(
    value: Any, field_name: str
) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    return _coerce_price_list(value, field_name)
