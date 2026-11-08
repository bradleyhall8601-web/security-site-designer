"""Risk management: fixed-fractional position sizing plus daily-loss and drawdown stops.

The size of a trade depends only on current equity and the distance to the stop.
It never grows after a loss (no martingale, no "smart scaling", no averaging down).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def position_size(equity: float, cash: float, entry: float, stop: float, *, risk_per_trade: float,
                  max_position_fraction: float, fee_rate: float = 0.0) -> float:
    """Units to buy so that hitting the stop loses about `risk_per_trade` of equity.

    Capped so the position is at most `max_position_fraction` of equity and fits in cash.
    Returns 0 when the trade is not valid (stop at/above entry, no money).
    """
    if entry <= 0 or stop is None or stop >= entry or equity <= 0 or cash <= 0:
        return 0.0
    risk_per_unit = (entry - stop) + entry * fee_rate * 2  # stop distance plus round-trip fees
    qty = equity * risk_per_trade / risk_per_unit
    qty = min(qty, equity * max_position_fraction / entry)
    qty = min(qty, cash / (entry * (1 + fee_rate)))
    return max(qty, 0.0)


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class RiskGuard:
    daily_loss_limit: float
    max_drawdown: float
    peak: float = 0.0
    day: str = ""
    day_start: float = 0.0
    halted_reason: str = ""
    history: list[str] = field(default_factory=list)

    def update(self, equity: float, ts_ms: int) -> None:
        self.peak = max(self.peak, equity)
        day = _day(ts_ms)
        if day != self.day:
            self.day, self.day_start = day, equity
            if self.halted_reason.startswith("daily"):
                self.halted_reason = ""  # daily stop resets at midnight UTC

    def can_open(self, equity: float, ts_ms: int) -> tuple[bool, str]:
        self.update(equity, ts_ms)
        if self.halted_reason.startswith("drawdown"):
            return False, self.halted_reason
        if self.peak > 0 and equity <= self.peak * (1 - self.max_drawdown):
            self.halted_reason = (f"drawdown kill switch: equity {equity:,.2f} is "
                                  f"{(1 - equity / self.peak):.1%} below peak {self.peak:,.2f}")
            self.history.append(self.halted_reason)
            return False, self.halted_reason
        if self.day_start > 0 and equity <= self.day_start * (1 - self.daily_loss_limit):
            self.halted_reason = f"daily loss limit hit ({(1 - equity / self.day_start):.1%} today)"
            return False, self.halted_reason
        return True, ""

    def reset(self, equity: float) -> None:
        """Manually clear the kill switch (e.g. from Telegram /resume after review)."""
        self.halted_reason = ""
        self.peak = equity
        self.day_start = equity

    def to_dict(self) -> dict:
        return {"peak": self.peak, "day": self.day, "day_start": self.day_start, "halted_reason": self.halted_reason}

    def load(self, data: dict) -> None:
        self.peak = float(data.get("peak", 0))
        self.day = data.get("day", "")
        self.day_start = float(data.get("day_start", 0))
        self.halted_reason = data.get("halted_reason", "")
