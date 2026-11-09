from datetime import datetime, timedelta, timezone

from trade_agent.reliability import ReliabilityManager
from trade_agent.storage import Database


def test_reliability_uses_bounded_error_state() -> None:
    manager = ReliabilityManager(max_consecutive_errors=2, stale_after_seconds=2)
    assert manager.record_error("first").value == "DEGRADED"
    assert manager.record_error("second").value == "SAFE_STOP"
    manager.record_success(datetime.now(timezone.utc))
    assert manager.state.value == "NORMAL"
    assert manager.assess_freshness(datetime.now(timezone.utc) + timedelta(seconds=3)).value == "DEGRADED"


def test_database_migrates_and_persists_setting(tmp_path) -> None:
    database = Database(tmp_path / "trade_agent.sqlite3")
    database.set_setting("capture_interval_ms", 420)
    assert database.get_setting("capture_interval_ms") == 420
    assert database.connection.execute("SELECT version FROM schema_version").fetchone()["version"] == 1
    database.close()

