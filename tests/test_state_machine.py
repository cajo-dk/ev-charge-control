from evcc.state_machine import (
    CABLE_PLUGGED,
    CABLE_UNPLUGGED,
    WINDOW_IN_WINDOW,
    WINDOW_NOT_REACHED,
    WINDOW_PAST_WINDOW,
    StateMachineContext,
    evaluate_state_machine,
)


def test_auto_reset_takes_precedence() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_UNPLUGGED,
            authorized=False,
            charging=True,
            soc_reached=True,
            continuous_power=False,
            charge_window=WINDOW_PAST_WINDOW,
        )
    )
    assert decision.rule == "scheduler_disengaged"


def test_waiting_before_window_rule() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_PLUGGED,
            authorized=True,
            charging=False,
            soc_reached=False,
            continuous_power=False,
            charge_window=WINDOW_NOT_REACHED,
        )
    )
    assert decision.status == "OK"
    assert decision.lock_calculation is False
    assert decision.set_authorized is None
    assert decision.set_charging is None


def test_start_charging_in_window_rule() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_PLUGGED,
            authorized=True,
            charging=False,
            soc_reached=False,
            continuous_power=False,
            charge_window=WINDOW_IN_WINDOW,
        )
    )
    assert decision.set_authorized is None
    assert decision.set_charging is True
    assert decision.status == "OK"
    assert decision.lock_calculation is True


def test_charging_continues_past_window_rule() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_PLUGGED,
            authorized=True,
            charging=True,
            soc_reached=False,
            continuous_power=False,
            charge_window=WINDOW_PAST_WINDOW,
        )
    )
    assert decision.status == "WARN"
    assert decision.lock_calculation is False


def test_missed_window_start_anyway_rule() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_PLUGGED,
            authorized=True,
            charging=False,
            soc_reached=False,
            continuous_power=False,
            charge_window=WINDOW_PAST_WINDOW,
        )
    )
    assert decision.set_charging is True
    assert decision.status == "ALERT"
    assert decision.lock_calculation is True


def test_in_window_not_authorized_rule() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_PLUGGED,
            authorized=False,
            charging=False,
            soc_reached=False,
            continuous_power=False,
            charge_window=WINDOW_IN_WINDOW,
        )
    )
    assert decision.rule == "scheduler_disengaged"


def test_unplugged_scheduler_wait_rule() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_UNPLUGGED,
            authorized=True,
            charging=True,
            soc_reached=False,
            continuous_power=False,
            charge_window=WINDOW_IN_WINDOW,
        )
    )
    assert decision.rule == "unplugged_scheduler_wait"


def test_continuous_power_hold_rule() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_PLUGGED,
            authorized=True,
            charging=True,
            soc_reached=True,
            continuous_power=True,
            charge_window=WINDOW_IN_WINDOW,
        )
    )
    assert decision.set_charging is None
    assert decision.status == "OK"
    assert decision.lock_calculation is False


def test_unlisted_combination_is_no_op() -> None:
    decision = evaluate_state_machine(
        StateMachineContext(
            cable=CABLE_UNPLUGGED,
            authorized=False,
            charging=False,
            soc_reached=False,
            continuous_power=False,
            charge_window=WINDOW_NOT_REACHED,
        )
    )
    assert decision.rule == "scheduler_disengaged"
