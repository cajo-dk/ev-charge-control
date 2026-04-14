from __future__ import annotations

from dataclasses import dataclass


WINDOW_NOT_REACHED = "Not Reached"
WINDOW_IN_WINDOW = "In Window"
WINDOW_PAST_WINDOW = "Past Window"
CABLE_PLUGGED = "Plugged"
CABLE_UNPLUGGED = "Unplugged"


@dataclass(slots=True)
class StateMachineContext:
    cable: str
    authorized: bool
    charging: bool
    soc_reached: bool
    continuous_power: bool
    charge_window: str | None


@dataclass(slots=True)
class StateMachineDecision:
    set_authorized: bool | None = None
    set_charging: bool | None = None
    status: str | None = None
    lock_calculation: bool | None = None
    rule: str | None = None


def evaluate_state_machine(context: StateMachineContext) -> StateMachineDecision:
    if not context.authorized:
        return StateMachineDecision(rule="scheduler_disengaged")

    if context.cable == CABLE_UNPLUGGED:
        return StateMachineDecision(rule="unplugged_scheduler_wait")

    if context.soc_reached and not context.continuous_power:
        return StateMachineDecision(
            set_authorized=True,
            set_charging=False,
            status="OK",
            lock_calculation=False,
            rule="auto_reset_soc_reached",
        )

    if context.soc_reached and context.continuous_power:
        return StateMachineDecision(
            set_authorized=True,
            status="OK",
            lock_calculation=False,
            rule="hold_power_after_target",
        )

    if (
        context.cable == CABLE_PLUGGED
        and context.authorized
        and not context.charging
        and context.charge_window == WINDOW_NOT_REACHED
    ):
        return StateMachineDecision(
            status="OK",
            lock_calculation=False,
            rule="waiting_before_window",
        )

    if (
        context.cable == CABLE_PLUGGED
        and context.authorized
        and not context.charging
        and context.charge_window == WINDOW_IN_WINDOW
    ):
        return StateMachineDecision(
            set_charging=True,
            status="OK",
            lock_calculation=True,
            rule="start_charging_in_window",
        )

    if (
        context.cable == CABLE_PLUGGED
        and context.authorized
        and context.charging
        and context.charge_window == WINDOW_PAST_WINDOW
    ):
        return StateMachineDecision(
            status="WARN",
            lock_calculation=False,
            rule="charging_continues_past_window",
        )

    if (
        context.cable == CABLE_PLUGGED
        and context.authorized
        and not context.charging
        and context.charge_window == WINDOW_PAST_WINDOW
    ):
        return StateMachineDecision(
            set_charging=True,
            status="ALERT",
            lock_calculation=True,
            rule="missed_window_start_anyway",
        )

    if (
        context.cable == CABLE_PLUGGED
        and not context.authorized
        and not context.charging
        and context.charge_window == WINDOW_IN_WINDOW
    ):
        return StateMachineDecision(
            status="WARN",
            lock_calculation=False,
            rule="in_window_not_authorized",
        )

    return StateMachineDecision(rule="no_op")
