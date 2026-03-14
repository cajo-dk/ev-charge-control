## 0. Instructions to AI Coding Assistants

This document is the authoritative context for this application. If you encounter discrepancies in documentation, coding standards, or workflow instructions, the information in `CONTEXT.md` overrides information from other sources.

- Ask for clarification if requirements conflict or are ambiguous.
- Prefer consistency and maintainability over novelty.
- Do not introduce new technologies or patterns without explicit approval.

### 0.1 Conventions

- Only ask permission to apply changes before deleting files, before executing a plan, or before committing irreversible changes to a database schema.
- Prefer small, reviewable changes that align with the documented versioning and branching workflow.
- If a requirement is not yet documented, update the relevant documentation as part of the work when appropriate.

### 0.2 References

Further documentation is available in the `doc` folder.

## 1. Product Context

### 1.1 Problem Statement

Calculating the optimal timeframe for charging an EV at the best electricity rate depends on several parameters, so creating a template sensor in Home Assistant (Hass) to perform this calculation using Jinja is cumbersome and difficult to maintain.

Instead, the algorithm should be placed in a Hass App. For Hass versions earlier than `2026.x`, this is referred to as an Add-on. Moving the logic into the app provides better configuration, logging, validation, and future extensibility.

### 1.2 Product Goal

This project is responsible for building the EV Charge Control App, hereafter referred to as `EVCC`.

EVCC must provide a maintainable and configurable way to determine when an EV should charge in order to satisfy user-defined constraints while favoring the most beneficial electricity pricing available to the user.

### 1.3 Intended Users

- Home Assistant users who want to automate EV charging based on price and charging targets.
- Maintainers of EVCC who need a codebase that is easier to evolve than complex Jinja templates.

## 2. Release 1 Definition

### 2.1 Release Objective

Release `1.x.x` establishes the first production-ready baseline of EVCC. This release defines the initial architecture, delivery model, documentation standards, and minimum functional expectations for the application.

### 2.2 What Release 1 Must Deliver

- A valid project structure for a Home Assistant app or add-on, as appropriate for the supported Hass version.
- A backend implementation in Python 3.x.
- Configuration support suitable for management from the Home Assistant app configuration page.
- Logging suitable for diagnosing configuration issues, calculation behavior, and runtime failures.
- A documented foundation for future feature work and fixes using the FR and fix workflows.

### 2.3 Release 1 Quality Bar

Release 1 must prioritize correctness, clarity, and maintainability over feature breadth. If tradeoffs are necessary, a smaller and more reliable first release is preferred over a broader but fragile implementation.

## 3. Scope

### 3.1 In Scope for Release 1

- Establishing the EVCC codebase and repository structure.
- Implementing the backend service in Python 3.x.
- Defining configuration inputs required by the charging algorithm.
- Implementing the charging decision logic in application code rather than Jinja templates.
- Providing logging and error reporting appropriate for setup and runtime troubleshooting.
- Establishing templates and documentation for releases, features, and fixes.
- Supporting local development practices suitable for ongoing maintenance.

### 3.2 Non-functional Requirements

- The project must be structured properly for a Hass App and have the necessary configuration to support configuration from the app configuration page.
- Whenever instructed to begin or commit releases, features, or fixes, you must always refer to the instructions in `VERSIONING.md`.
- The coding language for backend services must be Python 3.x. A virtual environment must be used for development.
- The coding language for frontend services, if any are introduced later, must be TypeScript unless explicitly approved otherwise.
- Configuration parameters and secrets must be kept in environment files where appropriate, and `.gitignore` must prevent them from being committed.
- The codebase must remain understandable to future maintainers without relying on undocumented conventions.

### 3.3 Out of Scope for Release 1

- Large-scale UI experimentation that changes the identity of the application.
- Introduction of new infrastructure or platforms not required to support the initial EVCC delivery.
- Broad multi-provider integrations unless they are necessary to support the initial charging workflow.
- Premature optimization that complicates the implementation without a demonstrated need.

## 4. Charging Calculation Requirements

### 4.1 Purpose

This section defines the core calculation behavior that EVCC must implement to fulfill the primary purpose of the application.

### 4.2 Calculation Goal

EVCC must calculate the optimal charging start time so that:

- charging completes by the user-defined finish time;
- the EV reaches the desired target State of Charge (SoC); and
- the selected charging window favors the best available electricity prices within those constraints.

### 4.3 Required Inputs

The app configuration page must make it possible to specify the devices, entities, sensors, and helpers from which EVCC reads the data required to calculate the charging start time and estimated end time.

The following inputs must be configurable:

| Parameter | Expected Data Type | Description |
| --------- | ------------------ | ----------- |
| EV Current SoC | Integer `0-100` | The sensor containing the EV's current SoC as a percentage. |
| Target SoC | Integer `0-100` | The sensor containing the desired target SoC as a percentage. |
| EV Battery Capacity | Float | The sensor containing the EV's total battery capacity in kWh. |
| Charger Speed | Float | The sensor containing the charging power of the wall box in kW. |
| Charge Loss | Integer `0-100` | The sensor containing the expected charging loss as a percentage. |
| Finish By | Time `hh:mm` | The sensor or helper containing the latest allowed completion time for charging. |
| Pricing Information | See Section 4.4 | The sensor containing actual and forecast electricity prices. |

### 4.4 Pricing Data Requirements

Pricing data is expected to be available in the pricing sensor's attributes:

| Attribute | Description |
| --------- | ----------- |
| `raw_today` | Pricing for today. |
| `raw_tomorrow` | Pricing for tomorrow, if available; otherwise `null`. |
| `forecast` | Estimated pricing for tomorrow when `raw_tomorrow` is `null`. |

Pricing data is available in 15-minute intervals and is expected to follow this structure:

```json
[
  {
    "hour": "2026-03-14T00:00:00+01:00",
    "price": 1.443
  },
  {
    "hour": "2026-03-14T23:45:00+01:00",
    "price": 1.455
  }
]
```

### 4.5 Required Output

The app configuration page must make it possible to specify the name of an `input_text` helper that stores the latest calculation result.

The output must include:

- the calculated start time;
- the estimated end time;
- the timestamp of the latest calculation; and
- a status value containing either `ok` or the latest error message, truncated to 255 characters.

The data should be stored as a JSON string in this form:

```json
{
  "start": "02:15",
  "end": "05:30",
  "timestamp": "2026-03-14T23:45:00+01:00",
  "status": "ok"
}
```

## 5. Product Expectations

### 5.1 Functional Expectations

At a minimum, EVCC should be designed so that the application can:

- Accept and validate the configuration needed to perform charging calculations.
- Evaluate charging windows based on the available input parameters.
- Produce outputs that Home Assistant can use for automation or user visibility.
- Fail in a diagnosable way when configuration is invalid or required inputs are missing.

### 5.2 Configuration Expectations

Configuration design for Release 1 should:

- Favor explicit and understandable settings over implicit behavior.
- Avoid excessive configuration complexity in the initial release.
- Include sensible validation and defaults where that improves usability without hiding important behavior.
- Be documented well enough that future FRs and fixes can evolve the configuration safely.

### 5.3 Logging and Observability Expectations

Logging for Release 1 should:

- Help diagnose invalid configuration, missing dependencies, and calculation outcomes.
- Be structured and clear enough to support troubleshooting by maintainers and advanced users.
- Avoid leaking secrets or sensitive configuration values.

## 6. Technical Direction

### 6.1 Architecture Principles

- Keep business logic separate from integration and configuration plumbing where practical.
- Prefer simple and testable modules over deeply coupled implementations.
- Avoid introducing architectural complexity before it is justified by a concrete requirement.
- Design the initial structure so future features can be added through FRs without reworking the entire application.

### 6.2 Technology Constraints

- Backend: Python 3.x.
- Frontend, if needed: TypeScript.
- New frameworks, storage technologies, or messaging patterns require explicit approval.

### 6.3 Home Assistant Alignment

- The repository and application structure must remain aligned with Home Assistant expectations for apps or add-ons.
- Configuration and runtime behavior should fit naturally into Home Assistant operations and maintenance practices.

## 7. Development Standards

### 7.1 Code Quality

- Prefer readable code over clever code.
- Keep functions and modules focused on clear responsibilities.
- Add comments only when they explain intent or non-obvious behavior.
- Favor consistency across the codebase over isolated local preferences.

### 7.2 Testing Expectations

- New functionality should be supported by automated tests where practical.
- Fixes should include validation that the reported issue is addressed.
- If automation is not practical for a given scenario, the reason and manual validation approach should be documented.

### 7.3 Documentation Expectations

- Documentation must evolve with the code when behavior, workflow, or configuration changes.
- Feature work must be documented through the FR process in `doc/features`.
- Fix deployments must be documented through the fix process in `doc/fixes`.
- When a change is released at a new fix version, the corresponding `doc/fixes/fix-xxx.md` file must be created or completed before the release commit is pushed or tagged so the fix record is contained in the tagged revision.
- `ev_charge_control/CHANGELOG.md` must be maintained whenever the application version changes. The top changelog entry must match the version in `ev_charge_control/config.yaml`.

## 8. Delivery Workflow

### 8.1 Versioning

The application version format is:

    release.feature.fix

Interpretation and workflow rules are defined in `VERSIONING.md`.

Every version change must also update `ev_charge_control/CHANGELOG.md` so the changelog stays aligned with `ev_charge_control/config.yaml`.

### 8.2 Features

- New features must start with an approved FR documented from `doc/fr-xxx.md`.
- Feature work must be implemented on a branch named after the FR, for example `fr-001`.

### 8.3 Fixes

- Fix work must be documented using the `doc/fix-xxx.md` template when deployed.
- Fix work must be implemented on a branch named after the fix, for example `fix-001`.
- If the code is being committed at a new fix level, the matching `fix-xxx.md` document must be created before the commit is pushed and before the release tag is created.

### 8.4 Releases

- Release 1 is governed by this document.
- Future release documentation may be added separately, but it must remain consistent with this context unless this file is updated.

## 9. Decision Guidance

When multiple implementation options are available, prefer the option that best satisfies the following order of priorities:

1. Correctness.
2. Maintainability.
3. Operational clarity.
4. Simplicity.
5. Feature breadth.

## 10. Open Items

The following topics are recognized as likely to need refinement after Release 1 work begins:

- Exact Home Assistant packaging details for the supported target version range.
- The final set of configuration fields required by the charging algorithm.
- The exact output entities, services, or interfaces exposed to Home Assistant.
- Release documentation beyond the initial governance defined here.

## 11. Document Change Log

| Revision | Date (YYYY.MM.DD) | Notes                                                                                                        |
| -------- | ----------------- | ------------------------------------------------------------------------------------------------------------ |
| 1.1.2    | 2026.03.14        | Added the requirement to maintain `ev_charge_control/CHANGELOG.md` whenever the application version changes. |
| 1.1.1    | 2026.03.14        | Clarified that fix documents must be created before pushing and tagging a new fix-level release. |
| 1.1.0    | 2026.03.13        | Expanded CONTEXT.md to define product context, Release 1 scope, technical direction, and delivery standards. |
| 1.0.0    | 2026.03.13        | First version.                                                                                               |
