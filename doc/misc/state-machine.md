# EVCC State Machine Specification

## 1. Purpose

This document formalizes the state logic captured in `doc/misc/states.xlsx`.
It defines how EVCC should interpret runtime conditions and what control actions EVCC may take in response.

This is an operational state-machine specification for charging execution behavior.
It is not a UI-only status model.

## 2. Observed Inputs

EVCC evaluates the following observed runtime inputs on each control tick.

### 2.1. Cable

`Cable` indicates whether the EV is physically connected.

Allowed values:

- `Plugged`
- `Unplugged`

This input is observational only.
It does not mean that charging is active.

### 2.2. Authorized

`Authorized` is the current state of the schedule-authorization control as read before any state-machine action is applied.

Allowed values:

- `Yes`
- `No`

### 2.3. Charging

`Charging` in the current-state columns means the current observed charging setting as read before any state-machine action is applied.

Allowed values:

- `Yes`
- `No`

In the commanded-output columns, charging means a requested change to the charging control setting.

### 2.4. SoC

`SoC` is a derived state.

Allowed values:

- `Reached`
- `Not Reached`

Definition:

- `Reached` means `current_soc >= target_soc`
- `Not Reached` means `current_soc < target_soc`

### 2.5. Charge Window

`Charge Window` is a derived state based on the currently active EVCC schedule.

Allowed values:

- `Not Reached`
- `In Window`
- `Past Window`

Definition:

- `Not Reached`: current time is before the calculated `start`
- `In Window`: current time is from calculated `start` through estimated `end`
- `Past Window`: current time is after estimated `end`

The window is defined from calculated `start` to estimated `end`, not by `finish_by`.

## 3. Commanded Outputs

The state machine may produce the following outputs.

### 3.1. Set Authorized

Commanded change to the authorization setting.

Allowed actions:

- set to `Yes`
- set to `No`
- no change

### 3.2. Set Charging

Commanded change to the charging setting.

Allowed actions:

- set to `Yes`
- set to `No`
- no change

### 3.3. Status

Operational status emitted by the state machine.

Allowed values:

- `OK`
- `WARN`
- `ALERT`

### 3.4. Lock Calculation

Indicates whether EVCC should block schedule recalculation while the current state remains active.

Allowed values:

- `Yes`
- `No`

## 4. Derived-State Notes

- `Authorized` and `Charging` are always evaluated as current observed states before applying any transition action.
- The commanded output columns do not describe current state; they describe state changes EVCC should apply.
- Row 10 in the spreadsheet is an automatic reset rule.
- Any runtime combination not listed in the spreadsheet is a no-op transition and must not alter control settings.

## 5. Transition Rules

The following rules are a direct prose conversion of the non-header rows in `states.xlsx`.

### Rule 1. Waiting Before Window

Preconditions:

- `Cable = Plugged`
- `Authorized = Yes`
- `Charging = No`
- `SoC = Not Reached`
- `Charge Window = Not Reached`

Actions:

- do not change authorization
- do not change charging

Outputs:

- `Status = OK`
- `Lock Calculation = No`

### Rule 2. Start Charging In Window

Preconditions:

- `Cable = Plugged`
- `Authorized = Yes`
- `Charging = No`
- `SoC = Not Reached`
- `Charge Window = In Window`

Actions:

- set `Authorized = No`
- set `Charging = Yes`

Outputs:

- `Status = OK`
- `Lock Calculation = Yes`

### Rule 3. Charging Continues Past Window

Preconditions:

- `Cable = Plugged`
- `Authorized = Yes`
- `Charging = Yes`
- `SoC = Not Reached`
- `Charge Window = Past Window`

Actions:

- do not change authorization
- do not change charging

Outputs:

- `Status = WARN`
- `Lock Calculation = No`

### Rule 4. Missed Window, Start Anyway

Preconditions:

- `Cable = Plugged`
- `Authorized = Yes`
- `Charging = No`
- `SoC = Not Reached`
- `Charge Window = Past Window`

Actions:

- do not change authorization
- set `Charging = Yes`

Outputs:

- `Status = ALERT`
- `Lock Calculation = Yes`

### Rule 5. In Window But Not Authorized

Preconditions:

- `Cable = Plugged`
- `Authorized = No`
- `Charging = No`
- `SoC = Not Reached`
- `Charge Window = In Window`

Actions:

- do not change authorization
- do not change charging

Outputs:

- `Status = WARN`
- `Lock Calculation = No`

### Rule 6. Unplugged While Charging In Window

Preconditions:

- `Cable = Unplugged`
- `Authorized = Yes`
- `Charging = Yes`
- `SoC = Not Reached`
- `Charge Window = In Window`

Actions:

- do not change authorization
- set `Charging = No`

Outputs:

- `Status = WARN`
- `Lock Calculation = No`

### Rule 7. Unplugged While Charging Past Window

Preconditions:

- `Cable = Unplugged`
- `Authorized = Yes`
- `Charging = Yes`
- `SoC = Not Reached`
- `Charge Window = Past Window`

Actions:

- do not change authorization
- set `Charging = No`

Outputs:

- `Status = ALERT`
- `Lock Calculation = No`

### Rule 8. Auto Reset On Target Reached

Preconditions:

- `SoC = Reached`

All other observed inputs are treated as wildcards.

Actions:

- set `Authorized = Yes`
- set `Charging = No`

Outputs:

- `Status = OK`
- `Lock Calculation = No`

This rule is an automatic reset.

## 6. Default Rule

If no explicit transition rule matches:

- do not change authorization
- do not change charging
- do not change status
- do not change calculation lock

In other words, combinations not listed in the spreadsheet must not alter anything.

## 7. Evaluation Order

EVCC should evaluate the state machine in this order:

1. Evaluate the auto-reset rule first.
   If `SoC = Reached`, apply Rule 8 immediately.
2. If the auto-reset rule does not apply, evaluate the explicit listed combinations.
3. If no listed combination matches, apply the default no-op rule.

This precedence is required so the `SoC = Reached` reset behavior is unconditional.

## 8. Unresolved Implementation Dependencies

The spreadsheet defines `Cable` as an observed runtime input, but the current EVCC implementation does not yet define a cable-connected entity in its configuration or runtime model.

For implementation, EVCC will therefore need an additional runtime input that can determine whether the EV is physically connected:

- `Plugged`
- `Unplugged`

Until such an input is implemented, the state machine is only partially executable in code.

## 9. Validation Checklist

This specification is intended to satisfy the following checks:

- every non-header spreadsheet row is represented exactly once
- observed state is separated from commanded state
- row 10 is documented as an unconditional auto-reset
- `Charge Window` is defined from calculated `start` to estimated `end`
- unspecified combinations are explicitly no-op transitions
