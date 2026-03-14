# EV Charge Control

EV Charge Control (`EVCC`) is a Home Assistant app intended to calculate the best time to charge an electric vehicle based on electricity prices, charging constraints, and a user-defined completion time.

The goal of the project is to move this logic out of complex Home Assistant Jinja templates and into a maintainable application with proper configuration, validation, and logging.

## Release 1 Scope

Release `1.x.x` establishes the first production-ready baseline of EVCC. The initial release is expected to provide:

- a valid Home Assistant app or add-on structure;
- a Python 3.x backend;
- configuration support through the Home Assistant app configuration page;
- charging calculation logic implemented in application code;
- logging for troubleshooting configuration and runtime behavior; and
- documentation workflows for releases, features, and fixes.

## Core Behavior

EVCC is intended to calculate an optimal charging start time so that:

- the EV reaches the desired target State of Charge;
- charging is completed by the configured finish time; and
- the selected charging window favors the best available electricity prices within those constraints.

The application reads configuration and input data from Home Assistant entities and publishes its latest result over MQTT as a Home Assistant-discoverable entity. The published entity exposes `status` as state and the remaining EVCC output as attributes.

## Repository Layout

- `CONTEXT.md`: authoritative product and release context for this repository.
- `VERSIONING.md`: rules for `release.feature.fix` versioning and documentation workflow.
- `repository.yaml`: Home Assistant add-on repository metadata.
- `ev_charge_control/`: deployable Home Assistant add-on folder.
- `ev_charge_control/config.yaml`: add-on metadata and configuration schema.
- `ev_charge_control/build.yaml`: architecture-specific Home Assistant base image configuration.
- `ev_charge_control/Dockerfile`: add-on container build definition.
- `ev_charge_control/src/evcc/`: Python application package for the EVCC service.
- `doc/fr-xxx.md`: template for feature request planning.
- `doc/fix-xxx.md`: template for documenting deployed fixes.
- `doc/features/`: approved and tracked feature request documents.
- `doc/fixes/`: deployed fix records.
- `doc/releases/`: release-specific documentation.

## Delivery Workflow

Feature work and fix work are documented separately.

- Features begin with an approved FR based on `doc/fr-xxx.md`.
- Feature branches should use the FR ID, for example `fr-001`.
- Fixes are documented on deployment using `doc/fix-xxx.md`.
- Fix branches should use the fix ID, for example `fix-001`.
- Versioning follows the format `release.feature.fix`.

## Development Notes

- `CONTEXT.md` is the source of truth if documentation conflicts exist.
- Backend work must use Python 3.x.
- A virtual environment should be used for development.
- Frontend work, if introduced, should use TypeScript unless explicitly approved otherwise.
- Secrets and configuration values should not be committed.

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
python -m evcc
```

## Home Assistant Add-on Packaging

The repository now includes the baseline files required to package EVCC as a Home Assistant add-on:

- `repository.yaml` defines the add-on repository for Home Assistant.
- `ev_charge_control/config.yaml` defines add-on metadata and user-configurable options.
- `ev_charge_control/build.yaml` selects the Home Assistant Python base images per architecture.
- `ev_charge_control/Dockerfile` builds the add-on container and starts the EVCC service.
- `ev_charge_control/run.sh` starts the Python module inside the add-on container.
- The add-on uses the internal Home Assistant API proxy and requires `homeassistant_api: true`.
- The add-on publishes output through MQTT and therefore requires MQTT broker connectivity.

The current implementation reads configured Home Assistant entities, calculates charging windows, controls charging execution, and publishes EVCC output through MQTT for Home Assistant consumption.

## Status

This repository currently contains the project documentation and workflow templates for Release 1. Implementation work should follow the rules described in `CONTEXT.md` and `VERSIONING.md`.
