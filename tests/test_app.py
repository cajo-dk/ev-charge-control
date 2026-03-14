from pathlib import Path

from evcc.app import (
    AppConfig,
    create_home_assistant_client,
    load_options,
    perform_api_cycle,
    validate_config,
)
from evcc.ha_api import HomeAssistantApiError


class DummyClient:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def get_entity_value(self, entity_id: str) -> str:
        return {
            "sensor.ev_current_soc": "20",
            "input_number.ev_target_soc": "80",
            "sensor.ev_battery_capacity": "77",
            "sensor.ev_charger_power": "11",
            "input_number.ev_charge_loss": "10",
            "input_datetime.ev_finish_by": "06:30",
        }[entity_id]

    def get_state(self, entity_id: str) -> dict:
        if entity_id != "sensor.electricity_prices":
            raise AssertionError(f"Unexpected entity: {entity_id}")
        return {
            "state": "ok",
            "attributes": {
                "raw_today": [{"hour": "2026-03-14T00:00:00+01:00", "price": 1.2}],
                "raw_tomorrow": None,
                "forecast": [{"hour": "2026-03-15T00:00:00+01:00", "price": 1.1}],
            },
        }

    def set_input_text(self, entity_id: str, value: str) -> None:
        self.writes.append((entity_id, value))


def test_app_config_normalizes_log_level() -> None:
    config = AppConfig.from_mapping({"log_level": "fatal"})
    assert config.log_level == "CRITICAL"


def test_load_options_returns_empty_mapping_for_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "options.json"
    assert load_options(missing_path) == {}


def test_validate_config_reports_missing_required_fields() -> None:
    missing_fields = validate_config(AppConfig())
    assert "ev_current_soc_entity" in missing_fields
    assert "result_helper_entity" in missing_fields


def test_create_home_assistant_client_returns_none_without_token(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert create_home_assistant_client() is None


def test_perform_api_cycle_writes_placeholder_result(caplog) -> None:
    client = DummyClient()
    config = AppConfig.from_mapping(
        {
            "ev_current_soc_entity": "sensor.ev_current_soc",
            "target_soc_entity": "input_number.ev_target_soc",
            "ev_battery_capacity_entity": "sensor.ev_battery_capacity",
            "charger_speed_entity": "sensor.ev_charger_power",
            "charge_loss_entity": "input_number.ev_charge_loss",
            "finish_by_entity": "input_datetime.ev_finish_by",
            "pricing_information_entity": "sensor.electricity_prices",
            "result_helper_entity": "input_text.evcc_result",
        }
    )

    perform_api_cycle(client=client, config=config, logger=__import__("logging").getLogger("test"))

    assert client.writes
    assert client.writes[0][0] == "input_text.evcc_result"
    assert "\"status\": \"ok\"" in client.writes[0][1]


def test_api_error_preserves_explicit_exception_type() -> None:
    assert isinstance(HomeAssistantApiError("boom"), RuntimeError)
