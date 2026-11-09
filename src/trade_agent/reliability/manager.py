from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_agent.core.models import ReliabilityState


class ReliabilityManager:
    """Bounded error and freshness state machine; no infinite retry loop."""

    def __init__(self, max_consecutive_errors: int = 3, stale_after_seconds: int = 5) -> None:
        self.max_consecutive_errors = max_consecutive_errors
        self.stale_after = timedelta(seconds=stale_after_seconds)
        self.consecutive_errors = 0
        self.last_success: datetime | None = None
        self.state = ReliabilityState.NORMAL
        self.last_error = ""

    def record_success(self, at: datetime | None = None) -> ReliabilityState:
        self.last_success = at or datetime.now(timezone.utc)
        self.consecutive_errors = 0
        self.state = ReliabilityState.RECOVERY if self.state is ReliabilityState.DEGRADED else ReliabilityState.NORMAL
        return self.state

    def record_error(self, message: str) -> ReliabilityState:
        self.consecutive_errors += 1
        self.last_error = message
        self.state = ReliabilityState.SAFE_STOP if self.consecutive_errors >= self.max_consecutive_errors else ReliabilityState.DEGRADED
        return self.state

    def assess_freshness(self, now: datetime | None = None) -> ReliabilityState:
        now = now or datetime.now(timezone.utc)
        if self.last_success is None or now - self.last_success > self.stale_after:
            if self.state is not ReliabilityState.SAFE_STOP:
                self.state = ReliabilityState.DEGRADED
        return self.state

    def safe_stop(self) -> None:
        self.state = ReliabilityState.SAFE_STOP

