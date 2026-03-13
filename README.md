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

The application is expected to read configuration and input data from Home Assistant entities and write its latest calculation result to a configured `input_text` helper as JSON.

## Repository Layout

- `CONTEXT.md`: authoritative product and release context for this repository.
- `VERSIONING.md`: rules for `release.feature.fix` versioning and documentation workflow.
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

## Status

This repository currently contains the project documentation and workflow templates for Release 1. Implementation work should follow the rules described in `CONTEXT.md` and `VERSIONING.md`.
