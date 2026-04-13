# EV Charge Control

EV Charge Control (`EVCC`) is a Home Assistant add-on that calculates the best time to charge an electric vehicle based on electricity prices, charging constraints, and a user-defined completion time.

Release `2.1.x` keeps EVCC's main runtime inputs on the MQTT device while integrating pricing and charger state/control directly with selected Home Assistant entities.

## Core Behavior

EVCC calculates an optimal charging start time so that:

- the EV reaches the desired target State of Charge;
- charging completes by the configured finish time; and
- the selected charging window favors the best available electricity prices within those constraints.

The add-on publishes:

- a compatibility MQTT sensor with `status` as state and the remaining EVCC payload as attributes;
- MQTT discovery controls for runtime inputs such as SoC, target SoC, charger speed, finish-by, and scheduling flags;
- MQTT discovery sensors for calculated times, state-machine status, and human-readable operator status; and
- an MQTT discovery `Start` button for re-authorizing and triggering a charge session when appropriate.

## Add-on Configuration

The add-on requires these options:

- `mqtt_host`
- `mqtt_port`
- `mqtt_username`
- `mqtt_password`
- `mqtt_discovery_prefix`
- `mqtt_topic_prefix`
- `log_level`
- `pricing_information_entity`
- `charger_control_switch_entity`
- `charger_state_sensor_entity`

## Home Assistant Integration Model

Home Assistant automations or integrations are still responsible for feeding EVCC's writable MQTT controls for the following values:

- `current_soc`
- `target_soc`
- `battery_capacity`
- `charger_speed`
- `charge_loss`
- `finish_by`
- `nighttime_charging_only`
- `schedule_authorized`

Pricing and charger integration are now selected directly in add-on configuration:

- `pricing_information_entity` should point at an Energi Data Service sensor whose attributes provide `raw_today`, `raw_tomorrow`, and optional `forecast` data.
- `charger_control_switch_entity` should point at the real charger switch EVCC is allowed to turn on and off.
- `charger_state_sensor_entity` should point at a Home Assistant sensor that reports one of:
  - `charging`
  - `disconnected`
  - `connected_finished_idle`
  - `connected_requesting_charge`

The aggregate EVCC MQTT payload still includes pricing data as an attribute for downstream consumers.

## Local Setup

Create and activate the virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

Run the service locally:

```powershell
$env:OPTIONS_PATH = ".\sample-options.json"
$env:PYTHONPATH = "ev_charge_control\src"
python -m evcc
```

Run tests:

```powershell
$env:PYTHONPATH = "ev_charge_control\src"
python -m pytest -q
```

## Repository Layout

- `CONTEXT.md`: authoritative product and release context for this repository.
- `VERSIONING.md`: rules for `release.feature.fix` versioning and documentation workflow.
- `repository.yaml`: Home Assistant add-on repository metadata.
- `ev_charge_control/`: deployable Home Assistant add-on folder.
- `ev_charge_control/config.yaml`: add-on metadata and configuration schema.
- `ev_charge_control/build.yaml`: architecture-specific Home Assistant base image configuration.
- `ev_charge_control/Dockerfile`: add-on container build definition.
- `ev_charge_control/src/evcc/`: Python application package for the EVCC service.
- `doc/features/`: approved and tracked feature request documents.
- `doc/fixes/`: deployed fix records.

## Status

This repository contains the Release `2.1.x` hybrid runtime implementation. Product and workflow governance remain defined by `CONTEXT.md` and `VERSIONING.md`.
