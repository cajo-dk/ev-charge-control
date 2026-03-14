# Changelog

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
