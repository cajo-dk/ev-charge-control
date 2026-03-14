from datetime import datetime

import pytest

from evcc.ha_api import HomeAssistantApiError
from evcc.runtime import LiveInputs, PricingPayload, calculate_result, next_quarter_boundary


def test_next_quarter_boundary_moves_to_next_slot() -> None:
    current_time = datetime.fromisoformat("2026-03-14T00:16:00+01:00")
    assert next_quarter_boundary(current_time) == datetime.fromisoformat(
        "2026-03-14T00:30:00+01:00"
    )


def test_calculate_result_selects_cheapest_valid_window() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="40",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="06:30",
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


def test_calculate_result_returns_blank_window_when_charge_not_needed() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="80",
        target_soc="70",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="06:30",
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
    assert payload["start"] == ""
    assert payload["end"] == ""


def test_calculate_result_uses_next_day_when_finish_by_has_passed() -> None:
    live_inputs = LiveInputs(
        ev_current_soc="20",
        target_soc="29",
        ev_battery_capacity="60",
        charger_speed="11",
        charge_loss="0",
        finish_by="00:30",
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
