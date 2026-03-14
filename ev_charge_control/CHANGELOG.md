# Changelog

## 1.2.1
- Fixed nighttime charging failures when tomorrow pricing was sourced from hourly forecast data.
- Expanded forecast pricing into 15-minute slots before the charging window search.

## 1.2.0
- Added charger execution control with a charger switch and schedule authorization helper.
- Added per-minute schedule execution checks while keeping quarter-hour calculation updates.
- Locked schedule recalculation while charging is active until target SoC or finish-by is reached.

## 1.1.0
- Added the Nighttime Charging Only helper to control whether charging may start only after the next midnight.
- Extended the calculator to enforce the overnight-only restriction without falling back to unrestricted scheduling.
- Added validation and test coverage for the new helper-driven scheduling behavior.

## 1.0.7
- Repaired the release history so the changelog now matches the version shown in Home Assistant.
- Ensured the changelog is aligned with the new tagged release version.

## 1.0.6
- Clarified that the changelog must be updated before the release commit is created.
- Corrected the changelog workflow so Home Assistant version notes stay aligned with the tagged release.

## 1.0.5
- Moved the changelog into `ev_charge_control/CHANGELOG.md`.
- Updated the release rules so future version changes maintain the changelog in the add-on folder.

## 1.0.4
- Restricted pricing payload logging to `DEBUG` level only.
- Kept `INFO` logs focused on compact operational input summaries.

## 1.0.3
- Implemented the first working charging window calculator.
- Added scheduled recalculation at startup and at `01`, `16`, `31`, and `46` each hour.
- Wrote calculated charging results and runtime errors back to the configured Home Assistant helper.

## 1.0.2
- Clarified the release workflow so fix documents must be created before pushing and tagging a fix release.

## 1.0.1
- Restructured the repository into a standard Home Assistant add-on repository layout.
- Added root repository metadata and moved the deployable add-on into `ev_charge_control/`.

## 1.0.0
- Initial release.
- Added the EVCC Home Assistant add-on scaffold and packaging files.
- Added Home Assistant API integration for reading configured entities and writing result payloads.
