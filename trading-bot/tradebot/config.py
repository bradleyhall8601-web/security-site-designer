"""Settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

LIVE_CONFIRM_PHRASE = "I accept the risk of losing money"


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines; existing environment wins."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    value = _env(name)
    return float(value) if value else default


def _int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


def _bool(name: str, default: bool) -> bool:
    value = _env(name).lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in _env(name, default).split(",") if item.strip()]


@dataclass
class Settings:
    # market
    exchange: str = "kraken"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USD", "ETH/USD"])
    timeframe: str = "1h"
    strategy: str = "trend"
    # data source: "exchange" (real prices) or "synthetic" (offline demo)
    data_source: str = "exchange"
    # trading mode: "paper" (simulated fills on real prices) or "live"
    mode: str = "paper"
    live_confirm: str = ""
    sandbox: bool = True
    api_key: str = ""
    api_secret: str = ""
    api_password: str = ""
    # money and costs
    starting_cash: float = 10_000.0
    fee_rate: float = 0.0026  # 0.26% taker, Kraken's top tier for small accounts
    slippage: float = 0.0005  # 0.05% per fill
    # risk
    risk_per_trade: float = 0.01  # lose at most 1% of equity if the stop is hit
    max_position_fraction: float = 0.25  # never put more than 25% of equity in one position
    daily_loss_limit: float = 0.03  # stop opening trades after -3% in a day
    max_drawdown: float = 0.15  # kill switch: stop opening trades after -15% from peak
    # loop
    poll_seconds: int = 60
    # telegram
    telegram_token: str = ""
    telegram_allowed_users: list[int] = field(default_factory=list)
    # web
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    web_token: str = ""
    # storage
    db_path: str = "tradebot.sqlite3"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(_env("TRADEBOT_ENV_FILE", ".env"))
        users = [int(u) for u in _list("TELEGRAM_ALLOWED_USERS", "") if u.lstrip("-").isdigit()]
        return cls(
            exchange=_env("EXCHANGE", "kraken").lower(),
            symbols=_list("SYMBOLS", "BTC/USD,ETH/USD"),
            timeframe=_env("TIMEFRAME", "1h"),
            strategy=_env("STRATEGY", "trend"),
            data_source=_env("DATA_SOURCE", "exchange").lower(),
            mode=_env("MODE", "paper").lower(),
            live_confirm=_env("LIVE_CONFIRM"),
            sandbox=_bool("SANDBOX", True),
            api_key=_env("API_KEY"),
            api_secret=_env("API_SECRET"),
            api_password=_env("API_PASSWORD"),
            starting_cash=_float("STARTING_CASH", 10_000.0),
            fee_rate=_float("FEE_RATE", 0.0026),
            slippage=_float("SLIPPAGE", 0.0005),
            risk_per_trade=_float("RISK_PER_TRADE", 0.01),
            max_position_fraction=_float("MAX_POSITION_FRACTION", 0.25),
            daily_loss_limit=_float("DAILY_LOSS_LIMIT", 0.03),
            max_drawdown=_float("MAX_DRAWDOWN", 0.15),
            poll_seconds=_int("POLL_SECONDS", 60),
            telegram_token=_env("TELEGRAM_TOKEN"),
            telegram_allowed_users=users,
            web_host=_env("WEB_HOST", "127.0.0.1"),
            web_port=_int("WEB_PORT", 8000),
            web_token=_env("WEB_TOKEN"),
            db_path=_env("DB_PATH", "tradebot.sqlite3"),
        )

    def validate(self) -> list[str]:
        """Return a list of problems; empty means the settings are usable."""
        problems = []
        if self.mode not in {"paper", "live"}:
            problems.append("MODE must be 'paper' or 'live'.")
        if self.data_source not in {"exchange", "synthetic"}:
            problems.append("DATA_SOURCE must be 'exchange' or 'synthetic'.")
        if self.mode == "live":
            if self.data_source != "exchange":
                problems.append("Live trading needs DATA_SOURCE=exchange.")
            if not (self.api_key and self.api_secret):
                problems.append("Live trading needs API_KEY and API_SECRET.")
            if self.live_confirm != LIVE_CONFIRM_PHRASE:
                problems.append(f"Live trading needs LIVE_CONFIRM=\"{LIVE_CONFIRM_PHRASE}\".")
        if not 0 < self.risk_per_trade <= 0.05:
            problems.append("RISK_PER_TRADE must be between 0 and 0.05 (5%).")
        if not 0 < self.max_position_fraction <= 1:
            problems.append("MAX_POSITION_FRACTION must be between 0 and 1.")
        if not self.symbols:
            problems.append("SYMBOLS must list at least one market, e.g. BTC/USD.")
        if self.web_host not in {"127.0.0.1", "localhost", "::1"} and not self.web_token:
            problems.append("Set WEB_TOKEN when the dashboard listens on a public address.")
        return problems
