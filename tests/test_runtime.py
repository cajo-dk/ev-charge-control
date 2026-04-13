from datetime import datetime

import pytest

from evcc.ha_api import HomeAssistantApiError
from evcc.runtime import (
    NO_SCHEDULE_TIME,
    LiveInputs,
    PricingPayload,
    calculate_result,
    next_midnight_boundary,
    next_quarter_boundary,
)


def test_next_quarter_boundary_moves_to_next_slot() -> None:
    current_time = datetime.fromisoformat("2026-03-14T00:16:00+01:00")
    assert next_quarter_boundary(current_time) == datetime.fromisoformat(
        "2026-03-14T00:30:00+01:00"
    )


def test_next_midnight_boundary_moves_to_next_day_midnight() -> None:
    current_time = datetime.fromisoformat("2026-03-14T22:16:00+01:00")
    assert next_midnight_boundary(current_time) == datetime.fromisoformat(
        "2026-03-15T00:00:00+01:00"
    )


def test_calculate_result_selects_cheapest_valid_window() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="40",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="06:30",
        nighttime_charging_only=False,
        pricing_information=PricingPayload(
            raw_today=[
                {"hour": "2026-03-14T00:15:00+01:00", "price": 3.0},
                {"hour": "2026-03-14T00:30:00+01:00", "price": 3.0},
                {"hour": "2026-03-14T00:45:00+01:00", "price": 3.0},
                {"hour": "2026-03-14T01:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-14T01:15:00+01:00", "price": 1.0},
                {"hour": "2026-03-14T01:30:00+01:00", "price": 1.0},
                {"hour": "2026-03-14T01:45:00+01:00", "price": 1.0},
                {"hour": "2026-03-14T02:00:00+01:00", "price": 1.0},
            ],
            raw_tomorrow=None,
            forecast=None,
        ),
    )

    payload = calculate_result(
        live_inputs,
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert payload["status"] == "ok"
    assert payload["start"] == "01:00"
    assert payload["end"] == "02:15"


def test_calculate_result_returns_placeholder_window_when_charge_not_needed() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="80",
        target_soc="70",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="06:30",
        nighttime_charging_only=False,
        pricing_information=PricingPayload(
            raw_today=[{"hour": "2026-03-14T00:15:00+01:00", "price": 3.0}],
            raw_tomorrow=None,
            forecast=None,
        ),
    )

    payload = calculate_result(
        live_inputs,
        now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
    )

    assert payload["status"] == "ok"
    assert payload["start"] == NO_SCHEDULE_TIME
    assert payload["end"] == NO_SCHEDULE_TIME


def test_calculate_result_uses_next_day_when_finish_by_has_passed() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="29",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="00:30",
        nighttime_charging_only=False,
        pricing_information=PricingPayload(
            raw_today=[
                {"hour": "2026-03-14T23:45:00+01:00", "price": 2.0},
            ],
            raw_tomorrow=[
                {"hour": "2026-03-15T00:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T00:15:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T00:30:00+01:00", "price": 1.0},
            ],
            forecast=None,
        ),
    )

    payload = calculate_result(
        live_inputs,
        now=datetime.fromisoformat("2026-03-14T23:50:00+01:00"),
    )

    assert payload["status"] == "ok"
    assert payload["start"] == "00:00"


def test_calculate_result_raises_when_no_valid_window_exists() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="100",
        ev_battery_capacity="100",
        charger_speed="3.7",
        charge_loss="0",
        finish_by="01:00",
        nighttime_charging_only=False,
        pricing_information=PricingPayload(
            raw_today=[
                {"hour": "2026-03-14T00:15:00+01:00", "price": 1.0},
                {"hour": "2026-03-14T00:30:00+01:00", "price": 1.0},
            ],
            raw_tomorrow=None,
            forecast=None,
        ),
    )

    with pytest.raises(HomeAssistantApiError, match="No valid charging window"):
        calculate_result(
            live_inputs,
            now=datetime.fromisoformat("2026-03-14T00:01:00+01:00"),
        )


def test_calculate_result_restricts_start_to_next_midnight_when_enabled() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="40",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="03:00",
        nighttime_charging_only=True,
        pricing_information=PricingPayload(
            raw_today=[
                {"hour": "2026-03-14T23:15:00+01:00", "price": 0.1},
                {"hour": "2026-03-14T23:30:00+01:00", "price": 0.1},
                {"hour": "2026-03-14T23:45:00+01:00", "price": 0.1},
            ],
            raw_tomorrow=[
                {"hour": "2026-03-15T00:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T00:15:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T00:30:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T00:45:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T01:00:00+01:00", "price": 1.0},
            ],
            forecast=None,
        ),
    )

    payload = calculate_result(
        live_inputs,
        now=datetime.fromisoformat("2026-03-14T22:10:00+01:00"),
    )

    assert payload["status"] == "ok"
    assert payload["start"] == "00:00"
    assert payload["end"] == "01:15"


def test_calculate_result_raises_when_nighttime_only_window_is_not_available() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="40",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="00:30",
        nighttime_charging_only=True,
        pricing_information=PricingPayload(
            raw_today=[
                {"hour": "2026-03-14T23:15:00+01:00", "price": 0.1},
                {"hour": "2026-03-14T23:30:00+01:00", "price": 0.1},
                {"hour": "2026-03-14T23:45:00+01:00", "price": 0.1},
            ],
            raw_tomorrow=[
                {"hour": "2026-03-15T00:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T00:15:00+01:00", "price": 1.0},
                {"hour": "2026-03-15T00:30:00+01:00", "price": 1.0},
            ],
            forecast=None,
        ),
    )

    with pytest.raises(HomeAssistantApiError, match="No valid charging window"):
        calculate_result(
            live_inputs,
            now=datetime.fromisoformat("2026-03-14T22:10:00+01:00"),
        )


def test_calculate_result_uses_hourly_forecast_for_nighttime_windows() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="47",
        target_soc="100",
        ev_battery_capacity="72",
        charger_speed="10.24",
        charge_loss="10",
        finish_by="08:30",
        nighttime_charging_only=True,
        pricing_information=PricingPayload(
            raw_today=[
                {"hour": "2026-03-14T23:00:00+01:00", "price": 1.856},
                {"hour": "2026-03-14T23:15:00+01:00", "price": 1.756},
                {"hour": "2026-03-14T23:30:00+01:00", "price": 1.742},
                {"hour": "2026-03-14T23:45:00+01:00", "price": 1.640},
            ],
            raw_tomorrow=None,
            forecast=[
                {"hour": "2026-03-15T00:00:00+01:00", "price": 1.517},
                {"hour": "2026-03-15T01:00:00+01:00", "price": 1.498},
                {"hour": "2026-03-15T02:00:00+01:00", "price": 1.333},
                {"hour": "2026-03-15T03:00:00+01:00", "price": 1.359},
                {"hour": "2026-03-15T04:00:00+01:00", "price": 1.376},
                {"hour": "2026-03-15T05:00:00+01:00", "price": 1.353},
                {"hour": "2026-03-15T06:00:00+01:00", "price": 1.526},
                {"hour": "2026-03-15T07:00:00+01:00", "price": 1.583},
                {"hour": "2026-03-15T08:00:00+01:00", "price": 1.581},
            ],
        ),
    )

    payload = calculate_result(
        live_inputs,
        now=datetime.fromisoformat("2026-03-14T11:39:00+01:00"),
    )

    assert payload["status"] == "ok"
    assert payload["start"] == "01:45"
    assert payload["end"] == "06:00"


def test_calculate_result_uses_actual_and_forecast_pricing_across_extended_horizon() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="100",
        ev_battery_capacity="75",
        charger_speed="11",
        charge_loss="0",
        finish_by="2026-03-16T08:00:00+01:00",
        nighttime_charging_only=False,
        pricing_information=PricingPayload(
            raw_today=[
                {"hour": "2026-03-14T08:15:00+01:00", "price": 5.0},
                {"hour": "2026-03-14T08:30:00+01:00", "price": 5.0},
                {"hour": "2026-03-14T08:45:00+01:00", "price": 5.0},
                {"hour": "2026-03-14T09:00:00+01:00", "price": 5.0},
            ],
            raw_tomorrow=[
                {"hour": "2026-03-15T20:00:00+01:00", "price": 4.0},
                {"hour": "2026-03-15T20:15:00+01:00", "price": 4.0},
                {"hour": "2026-03-15T20:30:00+01:00", "price": 4.0},
                {"hour": "2026-03-15T20:45:00+01:00", "price": 4.0},
            ],
            forecast=[
                {"hour": "2026-03-16T00:00:00+01:00", "price": 3.0},
                {"hour": "2026-03-16T01:00:00+01:00", "price": 2.0},
                {"hour": "2026-03-16T02:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-16T03:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-16T04:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-16T05:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-16T06:00:00+01:00", "price": 1.0},
                {"hour": "2026-03-16T07:00:00+01:00", "price": 1.0},
            ],
        ),
    )

    payload = calculate_result(
        live_inputs,
        now=datetime.fromisoformat("2026-03-14T08:01:00+01:00"),
    )

    assert payload["status"] == "ok"
    assert payload["start"] == "02:00"
