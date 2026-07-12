"""Circuit breaker for preventing runaway/stuck model loops."""
import time
from dataclasses import dataclass, field
from enum import Enum


class BreakerState(str, Enum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


@dataclass
class LaneBreaker:
    """Per-lane circuit breaker: opens on repeated errors or tool loops."""

    state: BreakerState = BreakerState.CLOSED
    error_timestamps: list[float] = field(default_factory=list)
    opened_at: float = 0
    last_tool_call: tuple[str, float] | None = None
    repeat_count: int = 0

    ERROR_WINDOW_S: float = 300
    ERROR_THRESHOLD: int = 3
    TOOL_REPEAT_THRESHOLD: int = 5
    TOOL_REPEAT_WINDOW_S: float = 60
    HALF_OPEN_AFTER_S: float = 300

    def record_error(self):
        """Record an error; open breaker if threshold reached within window."""
        now = time.time()
        self.error_timestamps.append(now)
        # Remove errors outside the window
        self.error_timestamps = [
            t for t in self.error_timestamps if now - t < self.ERROR_WINDOW_S
        ]
        if len(self.error_timestamps) >= self.ERROR_THRESHOLD:
            self._open()

    def record_tool_call(self, tool_name: str):
        """Record a tool call; open breaker if same tool repeats N times within window."""
        now = time.time()
        if (
            self.last_tool_call
            and self.last_tool_call[0] == tool_name
            and now - self.last_tool_call[1] < self.TOOL_REPEAT_WINDOW_S
        ):
            self.repeat_count += 1
            if self.repeat_count >= self.TOOL_REPEAT_THRESHOLD:
                self._open()
        else:
            self.repeat_count = 0
        self.last_tool_call = (tool_name, now)

    def _open(self):
        """Open the circuit and record when."""
        self.state = BreakerState.OPEN
        self.opened_at = time.time()

    def check(self) -> BreakerState:
        """Check state; transition OPEN->HALF_OPEN if cool-down elapsed."""
        if self.state == BreakerState.OPEN:
            if time.time() - self.opened_at >= self.HALF_OPEN_AFTER_S:
                self.state = BreakerState.HALF_OPEN
        return self.state

    def record_success(self):
        """Record a success; close circuit if HALF_OPEN."""
        if self.state == BreakerState.HALF_OPEN:
            self.state = BreakerState.CLOSED
            self.error_timestamps.clear()
            self.repeat_count = 0


# Global dict of breakers per lane
BREAKERS: dict[str, LaneBreaker] = {}


def get_breaker(lane: str) -> LaneBreaker:
    """Get or create breaker for lane."""
    if lane not in BREAKERS:
        BREAKERS[lane] = LaneBreaker()
    return BREAKERS[lane]
