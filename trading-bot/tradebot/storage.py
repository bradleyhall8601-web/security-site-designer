"""SQLite journal: positions, every fill, equity history, events and bot state."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positions (
  symbol TEXT PRIMARY KEY, qty REAL NOT NULL, entry REAL NOT NULL, stop REAL NOT NULL,
  opened_ts INTEGER NOT NULL, strategy TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
  entry_fee REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, mode TEXT NOT NULL, symbol TEXT NOT NULL,
  side TEXT NOT NULL, qty REAL NOT NULL, price REAL NOT NULL, fee REAL NOT NULL, pnl REAL,
  reason TEXT NOT NULL DEFAULT '', order_id TEXT
);
CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, equity REAL NOT NULL, cash REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, text TEXT NOT NULL);
"""


@dataclass
class Position:
    symbol: str
    qty: float
    entry: float
    stop: float
    opened_ts: int
    strategy: str
    reason: str = ""
    entry_fee: float = 0.0


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, path: str = "tradebot.sqlite3"):
        self.path = path
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, params)
            self.db.commit()
            return cur

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    # ---- state ----
    def get(self, key: str, default=None):
        rows = self._all("SELECT value FROM state WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set(self, key: str, value) -> None:
        self._exec("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value)))

    # ---- positions ----
    def positions(self) -> dict[str, Position]:
        return {r["symbol"]: Position(**r) for r in self._all("SELECT * FROM positions")}

    def save_position(self, p: Position) -> None:
        self._exec(
            "INSERT INTO positions(symbol,qty,entry,stop,opened_ts,strategy,reason,entry_fee) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty, entry=excluded.entry, stop=excluded.stop, "
            "opened_ts=excluded.opened_ts, strategy=excluded.strategy, reason=excluded.reason, entry_fee=excluded.entry_fee",
            (p.symbol, p.qty, p.entry, p.stop, p.opened_ts, p.strategy, p.reason, p.entry_fee))

    def delete_position(self, symbol: str) -> None:
        self._exec("DELETE FROM positions WHERE symbol=?", (symbol,))

    # ---- journal ----
    def add_fill(self, *, mode: str, symbol: str, side: str, qty: float, price: float, fee: float,
                 pnl: float | None, reason: str, order_id: str | None = None, ts: int | None = None) -> None:
        self._exec("INSERT INTO fills(ts,mode,symbol,side,qty,price,fee,pnl,reason,order_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (ts or now_ms(), mode, symbol, side, qty, price, fee, pnl, reason, order_id))

    def fills(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,))

    def realized_pnl(self) -> float:
        rows = self._all("SELECT COALESCE(SUM(pnl),0) AS p FROM fills WHERE pnl IS NOT NULL")
        return float(rows[0]["p"])

    def trade_stats(self) -> dict:
        rows = self._all("SELECT pnl FROM fills WHERE side='sell' AND pnl IS NOT NULL")
        wins = [r["pnl"] for r in rows if r["pnl"] > 0]
        return {"closed_trades": len(rows), "wins": len(wins),
                "win_rate": len(wins) / len(rows) if rows else 0.0,
                "realized_pnl": sum(r["pnl"] for r in rows)}

    def record_equity(self, equity: float, cash: float, ts: int | None = None) -> None:
        self._exec("INSERT OR REPLACE INTO equity(ts,equity,cash) VALUES(?,?,?)", (ts or now_ms(), equity, cash))

    def equity_history(self, limit: int = 2000) -> list[dict]:
        rows = self._all("SELECT ts, equity, cash FROM equity ORDER BY ts DESC LIMIT ?", (limit,))
        return rows[::-1]

    def log(self, text: str) -> None:
        self._exec("INSERT INTO events(ts,text) VALUES(?,?)", (now_ms(), text))

    def events(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT ts, text FROM events ORDER BY id DESC LIMIT ?", (limit,))
