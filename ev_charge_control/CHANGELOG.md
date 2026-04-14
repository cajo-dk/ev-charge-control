# Changelog

## 2.1.6
- Treated healthy calculation statuses case-insensitively so `OK` no longer triggers false system-failure severity `100`.
- Corrected status derivation so resting or planned states continue to publish their intended operator-facing status level.

## 2.1.5
- Restored still-missing EVCC startup controls from Home Assistant’s own EVCC entity states when MQTT retained replay and local runtime-state restore are incomplete.
- Added a final startup fallback for EVCC-owned control values such as `target_soc`, `battery_capacity`, `charger_speed`, and `finish_by`.

## 2.1.4
- Persisted EVCC-owned control values locally so required startup inputs such as `current_soc`, `target_soc`, and `finish_by` survive restarts even when MQTT retained replay is incomplete.
- Restored persisted control values from `/data/runtime_state.json` before MQTT synchronization while keeping later MQTT updates authoritative.

## 2.1.3
- Delayed the first runtime calculation until MQTT connection and retained control-state replay can restore required startup inputs such as `current_soc`, `target_soc`, and `finish_by`.
- Added bounded startup restore waiting so EVCC still proceeds normally when retained MQTT control values are genuinely unavailable.

## 2.1.2
- Restored retained MQTT control values from control state topics so EVCC no longer loses inputs such as `target_soc` after restart or reconnect.
- Prevented blank control-state republishes from overwriting retained MQTT control values during startup.

## 2.1.1
- Changed the active charging status text to show the expected finish clock time instead of a countdown.
- Prevented the internal no-schedule placeholder from surfacing as status level `100` during normal resting states.

## 2.1.0
- Switched pricing and charger integration from external MQTT mirroring to selected Home Assistant entity IDs for Energi Data Service pricing, charger control, and charger state.
- Changed `current_soc`, `target_soc`, and `charge_loss` MQTT number controls to typed input mode instead of slider mode.
- Combined actual and forecast pricing data for extended calculation horizons up to 72 hours and added test coverage for the new integration path.

## 2.0.0
- Replaced the Home Assistant entity-ID runtime model with MQTT-owned controls, sensors, and a Start button on the EVCC device.
- Kept only MQTT broker and log-level settings in add-on configuration while preserving the aggregate MQTT compatibility sensor.
- Added minute-by-minute `status_message` and `status_level` publishing, charger-command separation from observed charger state, and MQTT-backed runtime tests.

## 1.7.4
- Clarified that releases may only be created from `main`.
- Required release-bound `fr-xxx` and `fix-xxx` branches to be merged into `main` before release and removed afterward.

## 1.7.3
- Logged charge-progress MQTT messages at `INFO` every 15 minutes while charging remains active.
- Kept regular runtime MQTT publishing unchanged while avoiding per-minute progress log spam.

## 1.7.2
- Captured `soc_at_charge_start` when the charging cable transitions from unplugged to plugged.
- Preserved the captured start SoC while charging remains on instead of overwriting it on later ticks.

## 1.7.1
- Replaced blank calculated start and end placeholders with `--:--` when no schedule is available.
- Aligned helper synchronization and runtime schedule checks with the new no-schedule placeholder.

## 1.7.0
- Added optional `input_text` helper outputs for the calculated charging start and end times.
- Synchronized the helpers from the finalized runtime payload without rewriting unchanged values.
- Wrote empty strings to the helpers when no calculated schedule values are available.

## 1.6.0
- Added an optional `input_number` helper output for the SoC captured when charging starts.
- Synchronized the helper through the Home Assistant API without rewriting unchanged values.
- Reset the helper to `0` when no charge-start SoC is currently available.

## 1.5.1
- Prevented repeated charger shutoff commands after target SoC is reached by making the auto-reset action one-shot across minute ticks.
- Reduced scheduler noise by moving the "next calculation scheduled" heartbeat log from `INFO` to `DEBUG`.

## 1.5.0
- Implemented the charging execution state machine from the spreadsheet-derived specification.
- Added a required cable-connected input and derived cable/window/runtime control state on each minute tick.
- Applied explicit state-machine actions for authorization, charger control, status, and calculation locking with full test coverage.

## 1.4.0
- Replaced the JSON `input_text` output with MQTT-published Home Assistant entity output.
- Published EVCC `status` as MQTT state and all other EVCC fields as MQTT attributes.
- Added MQTT broker configuration, discovery publishing, and output-path test coverage.

## 1.3.0
- Expanded the EVCC result payload with finish-by, authorization, charger-state, and SoC status fields.
- Captured the EV SoC at charge start and kept the output aligned with live charging state during execution.
- Standardized payload writes across calculation, execution, and error paths.

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
