from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from evcc.ha_api import HomeAssistantApiError, HomeAssistantClient

PRICE_INTERVAL = timedelta(minutes=15)


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
    nighttime_charging_only: bool
    pricing_information: PricingPayload


@dataclass(slots=True)
class PricePoint:
    starts_at: datetime
    price: float


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
        nighttime_charging_only=_parse_input_boolean_state(
            client.get_entity_value(config.nighttime_charging_only_entity),
            "nighttime_charging_only_entity",
        ),
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


def calculate_result(
    live_inputs: LiveInputs,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    current_time = _ensure_aware_now(now)
    current_soc = _parse_percentage(live_inputs.ev_current_soc, "ev_current_soc")
    target_soc = _parse_percentage(live_inputs.target_soc, "target_soc")
    battery_capacity = _parse_positive_float(
        live_inputs.ev_battery_capacity, "ev_battery_capacity"
    )
    charger_speed = _parse_positive_float(live_inputs.charger_speed, "charger_speed")
    charge_loss = _parse_percentage(live_inputs.charge_loss, "charge_loss")
    finish_by = _parse_finish_by(live_inputs.finish_by, current_time)

    if target_soc <= current_soc:
        return build_placeholder_result(current_time)

    effective_power = charger_speed * (1 - (charge_loss / 100))
    if effective_power <= 0:
        raise HomeAssistantApiError("Effective charger power must be greater than zero.")

    required_energy = ((target_soc - current_soc) / 100) * battery_capacity
    slots_needed = math.ceil((required_energy / effective_power) / 0.25)
    if slots_needed <= 0:
        return build_placeholder_result(current_time)

    earliest_start = (
        next_midnight_boundary(current_time)
        if live_inputs.nighttime_charging_only
        else next_quarter_boundary(current_time)
    )
    pricing = _normalize_pricing(live_inputs.pricing_information, current_time)
    start_time, end_time = _find_cheapest_window(
        pricing=pricing,
        earliest_start=earliest_start,
        finish_by=finish_by,
        slots_needed=slots_needed,
    )

    return {
        "start": start_time.strftime("%H:%M"),
        "end": end_time.strftime("%H:%M"),
        "timestamp": current_time.isoformat(),
        "status": "ok",
    }


def parse_percentage_value(value: str | float | int | None, field_name: str) -> float:
    return _parse_percentage(value, field_name)


def parse_finish_by_value(value: str | float | int | None, now: datetime) -> datetime:
    return _parse_finish_by(value, now)


def parse_input_boolean_value(value: str | float | int | None, field_name: str) -> bool:
    return _parse_input_boolean_state(value, field_name)


def next_quarter_boundary(current_time: datetime) -> datetime:
    aligned = current_time.replace(second=0, microsecond=0)
    next_quarter = ((aligned.minute // 15) + 1) * 15
    if next_quarter >= 60:
        return (aligned.replace(minute=0) + timedelta(hours=1)).replace(second=0)
    return aligned.replace(minute=next_quarter)


def next_midnight_boundary(current_time: datetime) -> datetime:
    return (current_time + timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


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


def _ensure_aware_now(now: datetime | None) -> datetime:
    current_time = now or datetime.now().astimezone()
    if current_time.tzinfo is None:
        return current_time.astimezone()
    return current_time


def _parse_float(value: str | float | int | None, field_name: str) -> float:
    if value is None:
        raise HomeAssistantApiError(f"Missing value for '{field_name}'.")
    normalized = str(value).strip().lower()
    if normalized in {"", "unknown", "unavailable", "none", "null"}:
        raise HomeAssistantApiError(f"Invalid value for '{field_name}': {value}")
    try:
        return float(normalized)
    except ValueError as exc:
        raise HomeAssistantApiError(
            f"Could not parse numeric value for '{field_name}': {value}"
        ) from exc


def _parse_positive_float(value: str | float | int | None, field_name: str) -> float:
    parsed = _parse_float(value, field_name)
    if parsed <= 0:
        raise HomeAssistantApiError(f"'{field_name}' must be greater than zero.")
    return parsed


def _parse_percentage(value: str | float | int | None, field_name: str) -> float:
    parsed = _parse_float(value, field_name)
    if parsed < 0 or parsed > 100:
        raise HomeAssistantApiError(f"'{field_name}' must be between 0 and 100.")
    return parsed


def _parse_input_boolean_state(value: str | float | int | None, field_name: str) -> bool:
    if value is None:
        raise HomeAssistantApiError(f"Missing value for '{field_name}'.")

    normalized = str(value).strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False

    raise HomeAssistantApiError(
        f"Invalid input_boolean state for '{field_name}': {value}"
    )


def _parse_finish_by(value: str | float | int | None, now: datetime) -> datetime:
    if value is None:
        raise HomeAssistantApiError("Missing value for 'finish_by'.")
    raw = str(value).strip()
    if raw.lower() in {"", "unknown", "unavailable", "none", "null"}:
        raise HomeAssistantApiError(f"Invalid value for 'finish_by': {value}")

    parsed_time: time | None = None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_time = datetime.strptime(raw, fmt).time()
            break
        except ValueError:
            continue

    if parsed_time is not None:
        deadline = now.replace(
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            second=0,
            microsecond=0,
        )
        if deadline <= now:
            deadline += timedelta(days=1)
        return deadline

    try:
        deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HomeAssistantApiError(f"Could not parse finish-by value: {value}") from exc

    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=now.tzinfo)
    return deadline.astimezone(now.tzinfo)


def _normalize_pricing(pricing: PricingPayload, now: datetime) -> list[PricePoint]:
    entries: list[tuple[dict[str, Any], str]] = [
        (entry, "raw_today") for entry in pricing.raw_today
    ]
    if pricing.raw_tomorrow is not None:
        entries.extend((entry, "raw_tomorrow") for entry in pricing.raw_tomorrow)
    elif pricing.forecast is not None:
        entries.extend((entry, "forecast") for entry in pricing.forecast)

    points_by_time: dict[datetime, float] = {}
    for entry, source in entries:
        if not isinstance(entry, dict):
            raise HomeAssistantApiError("Pricing entries must be objects.")
        starts_at_raw = entry.get("hour")
        price_raw = entry.get("price")
        if starts_at_raw is None or price_raw is None:
            raise HomeAssistantApiError("Pricing entries must contain 'hour' and 'price'.")
        try:
            starts_at = datetime.fromisoformat(str(starts_at_raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise HomeAssistantApiError(
                f"Invalid pricing timestamp: {starts_at_raw}"
            ) from exc
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=now.tzinfo)
        starts_at = starts_at.astimezone(now.tzinfo)
        try:
            price = float(price_raw)
        except (TypeError, ValueError) as exc:
            raise HomeAssistantApiError(f"Invalid pricing value: {price_raw}") from exc
        for point_time in _expand_price_points(starts_at, price, source):
            points_by_time[point_time.starts_at] = point_time.price

    if not points_by_time:
        raise HomeAssistantApiError("No pricing data was available for calculation.")

    return [
        PricePoint(starts_at=starts_at, price=points_by_time[starts_at])
        for starts_at in sorted(points_by_time)
    ]


def _find_cheapest_window(
    *,
    pricing: list[PricePoint],
    earliest_start: datetime,
    finish_by: datetime,
    slots_needed: int,
) -> tuple[datetime, datetime]:
    best_start: datetime | None = None
    best_end: datetime | None = None
    best_cost: float | None = None

    for index, point in enumerate(pricing):
        if point.starts_at < earliest_start:
            continue

        window = pricing[index : index + slots_needed]
        if len(window) < slots_needed:
            break
        if not _is_contiguous(window):
            continue

        end_time = window[-1].starts_at + PRICE_INTERVAL
        if end_time > finish_by:
            continue

        cost = sum(price_point.price for price_point in window)
        if best_cost is None or cost < best_cost or (
            math.isclose(cost, best_cost) and point.starts_at < best_start
        ):
            best_cost = cost
            best_start = point.starts_at
            best_end = end_time

    if best_start is None or best_end is None:
        raise HomeAssistantApiError(
            "No valid charging window was available before the finish-by deadline."
        )
    return best_start, best_end


def _is_contiguous(points: list[PricePoint]) -> bool:
    return all(
        later.starts_at - earlier.starts_at == PRICE_INTERVAL
        for earlier, later in zip(points, points[1:])
    )


def _expand_price_points(
    starts_at: datetime,
    price: float,
    source: str,
) -> list[PricePoint]:
    if source != "forecast":
        return [PricePoint(starts_at=starts_at, price=price)]

    # Forecast data can arrive hourly while the calculator operates on 15-minute slots.
    return [
        PricePoint(starts_at=starts_at + (PRICE_INTERVAL * offset), price=price)
        for offset in range(4)
    ]
