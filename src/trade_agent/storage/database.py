from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from trade_agent.core.models import CalculationResult, MarketSnapshot


class Database:
    LATEST_SCHEMA = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        with self.connection:
            self.connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self.connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                self.connection.execute("INSERT INTO schema_version(version) VALUES (0)")
                version = 0
            else:
                version = int(row["version"])
            if version < 1:
                self.connection.executescript("""
                    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS market_snapshots (
                        id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL, item_name TEXT NOT NULL,
                        request_price TEXT, listing_prices TEXT NOT NULL, complete INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS calculations (
                        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, average_price TEXT, net_sale_price TEXT,
                        per_item_result TEXT, total_result TEXT, eligible INTEGER NOT NULL, reason TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sticker_sessions (
                        id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, sticker_items INTEGER NOT NULL,
                        normal_items INTEGER NOT NULL, duration_seconds REAL
                    );
                    CREATE TABLE IF NOT EXISTS app_logs (
                        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
                    );
                """)
                self.connection.execute("UPDATE schema_version SET version = 1")

    def set_setting(self, key: str, value: Any) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def save_snapshot(self, snapshot: MarketSnapshot) -> None:
        request = snapshot.request_price.parsed_value if snapshot.request_price else None
        listings = [str(item.parsed_value) if item.parsed_value is not None else None for item in snapshot.listing_prices]
        with self.connection:
            self.connection.execute(
                "INSERT INTO market_snapshots(captured_at,item_name,request_price,listing_prices,complete) VALUES (?,?,?,?,?)",
                (snapshot.captured_at.isoformat(), snapshot.item_name, str(request) if request is not None else None,
                 json.dumps(listings), int(snapshot.is_complete)),
            )

    def save_calculation(self, result: CalculationResult) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO calculations(created_at,average_price,net_sale_price,per_item_result,total_result,eligible,reason) VALUES (?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), *[
                    str(value) if value is not None else None
                    for value in (result.average_price, result.net_sale_price, result.per_item_result, result.total_result)
                ], int(result.eligible), result.reason),
            )

    def save_sticker_session(self, started_at: datetime, ended_at: datetime, sticker_items: int, normal_items: int) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO sticker_sessions(started_at,ended_at,sticker_items,normal_items,duration_seconds) VALUES (?,?,?,?,?)",
                (started_at.isoformat(), ended_at.isoformat(), sticker_items, normal_items,
                 (ended_at - started_at).total_seconds()),
            )

    def recent_history(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(self.connection.execute(
            "SELECT created_at AS happened_at, 'Расчёт' AS kind, reason AS detail FROM calculations "
            "UNION ALL SELECT captured_at, 'Снимок рынка', item_name FROM market_snapshots "
            "ORDER BY happened_at DESC LIMIT ?", (limit,)
        ))

    def log(self, level: str, message: str) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO app_logs(created_at,level,message) VALUES (?,?,?)", (
                datetime.now(timezone.utc).isoformat(), level, message,
            ))

    def close(self) -> None:
        self.connection.close()
