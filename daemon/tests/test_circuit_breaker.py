import time
from daemon.circuit_breaker import LaneBreaker, BreakerState


def test_breaker_opens_on_3_errors():
    b = LaneBreaker()
    for _ in range(3):
        b.record_error()
    assert b.check() == BreakerState.OPEN


def test_breaker_opens_on_5_tool_repeats():
    b = LaneBreaker()
    for _ in range(6):
        b.record_tool_call("some_tool")
    assert b.check() == BreakerState.OPEN


def test_breaker_transitions_to_half_open_after_timeout():
    b = LaneBreaker()
    # Open the breaker
    for _ in range(3):
        b.record_error()
    assert b.check() == BreakerState.OPEN

    # Manually advance time by mocking opened_at
    b.opened_at = time.time() - 301  # 301 seconds ago
    assert b.check() == BreakerState.HALF_OPEN


def test_breaker_closes_on_success_from_half_open():
    b = LaneBreaker()
    # Open the breaker
    for _ in range(3):
        b.record_error()
    assert b.check() == BreakerState.OPEN

    # Advance to half-open
    b.opened_at = time.time() - 301
    assert b.check() == BreakerState.HALF_OPEN

    # Record success
    b.record_success()
    assert b.check() == BreakerState.CLOSED


def test_error_window_expires():
    b = LaneBreaker()
    # Record 2 errors
    b.record_error()
    b.record_error()
    assert b.check() == BreakerState.CLOSED

    # Manually advance time so first errors are outside window
    b.error_timestamps = [t - 301 for t in b.error_timestamps]

    # Record one more error - should stay closed since old errors expire
    b.record_error()
    assert b.check() == BreakerState.CLOSED


def test_tool_repeat_window_expires():
    b = LaneBreaker()
    # Record 5 repeats of same tool
    for _ in range(5):
        b.record_tool_call("tool_x")
    assert b.check() == BreakerState.CLOSED  # 5 is threshold, but not yet open

    # Manually advance time so next tool call is outside window
    b.last_tool_call = ("tool_x", time.time() - 61)

    # Record same tool again - should reset repeat count since outside window
    b.record_tool_call("tool_x")
    assert b.repeat_count == 0
    assert b.check() == BreakerState.CLOSED
