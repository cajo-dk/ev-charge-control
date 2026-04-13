# EV Charge Control

EV Charge Control (`EVCC`) is a Home Assistant add-on that calculates the best time to charge an electric vehicle based on electricity prices, charging constraints, and a user-defined completion time.

Release `2.x.x` moves EVCC to an MQTT-owned runtime model. The add-on keeps only broker connectivity and logging in add-on options. All charge inputs, controls, and status outputs are exposed through MQTT discovery entities on the EVCC device.

## Core Behavior

EVCC calculates an optimal charging start time so that:

- the EV reaches the desired target State of Charge;
- charging completes by the configured finish time; and
- the selected charging window favors the best available electricity prices within those constraints.

The add-on publishes:

- a compatibility MQTT sensor with `status` as state and the remaining EVCC payload as attributes;
- MQTT discovery controls for runtime inputs such as SoC, target SoC, charger speed, finish-by, cable state, and pricing payloads;
- MQTT discovery sensors for calculated times, state-machine status, and human-readable operator status; and
- an MQTT discovery `Start` button for re-authorizing and triggering a charge session when appropriate.

## Add-on Configuration

Only these add-on options remain:

- `mqtt_host`
- `mqtt_port`
- `mqtt_username`
- `mqtt_password`
- `mqtt_discovery_prefix`
- `mqtt_topic_prefix`
- `log_level`

## Home Assistant Integration Model

Home Assistant automations or integrations are responsible for feeding real-world values into EVCC's writable MQTT controls and for reacting to EVCC's charger command output.

Typical responsibilities outside EVCC:

- write `current_soc`, `target_soc`, `battery_capacity`, `charger_speed`, `charge_loss`, `finish_by`, and `pricing_information`;
- mirror the physical cable and charger state into `cable_connected` and `charger_state`;
- react to EVCC's `charger_command` switch state and forward it to the real charger integration.

`charger_state` is intentionally exposed as a read-only MQTT sensor in Home Assistant while still being consumed by EVCC from its MQTT state topic.

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

This repository contains the Release `2.x.x` MQTT-owned runtime implementation. Product and workflow governance remain defined by `CONTEXT.md` and `VERSIONING.md`.
