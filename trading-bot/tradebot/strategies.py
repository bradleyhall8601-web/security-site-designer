"""Trading strategies.

Every strategy is long-only (spot: buy, then sell what you bought) and causal:
the signal for candle i only uses candles 0..i, and orders fill at the open of
candle i+1. Each entry carries a stop-loss price so the risk manager can size it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from . import indicators as ind
from .data import Candle

BUY, SELL, HOLD = "buy", "sell", "hold"


@dataclass(frozen=True)
class Signal:
    action: str  # buy | sell | hold
    reason: str
    price: float  # close of the candle the signal was computed on
    stop: float | None = None  # stop-loss for a new entry
    target: float | None = None  # optional take-profit


class Strategy:
    name = "base"
    title = "Base"
    description = ""
    warmup = 50  # candles needed before the first signal

    def signals(self, candles: Sequence[Candle]) -> list[Signal]:
        raise NotImplementedError

    def evaluate(self, candles: Sequence[Candle]) -> Signal:
        if len(candles) < self.warmup + 2:
            price = candles[-1].close if candles else 0.0
            return Signal(HOLD, f"Need {self.warmup + 2} candles, have {len(candles)}", price)
        return self.signals(candles)[-1]


class TrendFollow(Strategy):
    name = "trend"
    title = "Trend following (EMA cross + 200 EMA filter)"
    description = (
        "Buys when the 20 EMA crosses above the 50 EMA while price is above the 200 EMA; "
        "sells when the 20 EMA falls back below the 50 EMA. Stop 2.5 ATR below entry."
    )
    warmup = 200

    def __init__(self, fast: int = 20, slow: int = 50, filter_period: int = 200, atr_mult: float = 2.5):
        self.fast, self.slow, self.filter_period, self.atr_mult = fast, slow, filter_period, atr_mult
        self.warmup = max(slow, filter_period)

    def signals(self, candles: Sequence[Candle]) -> list[Signal]:
        closes = [c.close for c in candles]
        fast, slow = ind.ema(closes, self.fast), ind.ema(closes, self.slow)
        trend, vol = ind.ema(closes, self.filter_period), ind.atr(candles, 14)
        out = []
        for i, price in enumerate(closes):
            if i == 0 or None in (fast[i], slow[i], trend[i], vol[i], fast[i - 1], slow[i - 1]):
                out.append(Signal(HOLD, "warming up", price))
                continue
            crossed_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
            if crossed_up and price > trend[i]:
                out.append(Signal(BUY, f"EMA{self.fast} crossed above EMA{self.slow}, price above EMA{self.filter_period}",
                                  price, stop=price - self.atr_mult * vol[i]))
            elif fast[i] < slow[i]:
                out.append(Signal(SELL, f"EMA{self.fast} below EMA{self.slow}: trend over", price))
            else:
                out.append(Signal(HOLD, "no new cross", price))
        return out


class MeanReversion(Strategy):
    name = "meanrev"
    title = "Mean reversion (RSI dip in an uptrend)"
    description = (
        "Buys when RSI(14) drops below 30 while price is above the 200 SMA; sells when RSI "
        "recovers above 55. Stop 3 ATR below entry."
    )
    warmup = 200

    def __init__(self, period: int = 14, buy_below: float = 30, sell_above: float = 55,
                 trend_period: int = 200, atr_mult: float = 3.0):
        self.period, self.buy_below, self.sell_above = period, buy_below, sell_above
        self.trend_period, self.atr_mult = trend_period, atr_mult
        self.warmup = trend_period

    def signals(self, candles: Sequence[Candle]) -> list[Signal]:
        closes = [c.close for c in candles]
        r, trend, vol = ind.rsi(closes, self.period), ind.sma(closes, self.trend_period), ind.atr(candles, 14)
        out = []
        for i, price in enumerate(closes):
            if None in (r[i], trend[i], vol[i]):
                out.append(Signal(HOLD, "warming up", price))
            elif r[i] < self.buy_below and price > trend[i]:
                out.append(Signal(BUY, f"RSI {r[i]:.0f} < {self.buy_below:.0f} in an uptrend", price,
                                  stop=price - self.atr_mult * vol[i]))
            elif r[i] > self.sell_above:
                out.append(Signal(SELL, f"RSI recovered to {r[i]:.0f}", price))
            else:
                out.append(Signal(HOLD, f"RSI {r[i]:.0f}", price))
        return out


class Breakout(Strategy):
    name = "breakout"
    title = "Breakout (20-bar Donchian channel)"
    description = (
        "Buys when price closes above the highest high of the previous 20 candles; sells when "
        "it closes below the lowest low of the previous 10. Stop 2 ATR below entry."
    )
    warmup = 30

    def __init__(self, entry: int = 20, exit_: int = 10, atr_mult: float = 2.0):
        self.entry, self.exit, self.atr_mult = entry, exit_, atr_mult
        self.warmup = max(entry, exit_, 15) + 1

    def signals(self, candles: Sequence[Candle]) -> list[Signal]:
        closes = [c.close for c in candles]
        hi = ind.highest([c.high for c in candles], self.entry)
        lo = ind.lowest([c.low for c in candles], self.exit)
        vol = ind.atr(candles, 14)
        out = []
        for i, price in enumerate(closes):
            if i == 0 or None in (hi[i - 1], lo[i - 1], vol[i]):
                out.append(Signal(HOLD, "warming up", price))
            elif price > hi[i - 1]:
                out.append(Signal(BUY, f"closed above the {self.entry}-bar high {hi[i - 1]:.2f}", price,
                                  stop=price - self.atr_mult * vol[i]))
            elif price < lo[i - 1]:
                out.append(Signal(SELL, f"closed below the {self.exit}-bar low {lo[i - 1]:.2f}", price))
            else:
                out.append(Signal(HOLD, "inside the channel", price))
        return out


STRATEGIES: dict[str, type[Strategy]] = {s.name: s for s in (TrendFollow, MeanReversion, Breakout)}


def get_strategy(name: str) -> Strategy:
    key = name.lower().strip()
    if key not in STRATEGIES:
        raise ValueError(f"Unknown strategy {name!r}; choose one of {', '.join(STRATEGIES)}")
    return STRATEGIES[key]()
