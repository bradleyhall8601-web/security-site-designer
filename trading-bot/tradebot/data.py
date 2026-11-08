"""Market data: real candles from any ccxt exchange, or a seeded synthetic feed."""

from __future__ import annotations

import asyncio
import csv
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}


@dataclass(frozen=True)
class Candle:
    ts: int  # open time, milliseconds since epoch
    open: float
    high: float
    low: float
    close: float
    volume: float


def timeframe_seconds(timeframe: str) -> int:
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe {timeframe!r}; use one of {', '.join(TIMEFRAME_SECONDS)}")
    return TIMEFRAME_SECONDS[timeframe]


class DataFeed:
    """Interface every feed implements."""

    async def candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raise NotImplementedError

    async def price(self, symbol: str) -> float:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class ExchangeFeed(DataFeed):
    """Public market data through ccxt (no API key needed for prices)."""

    def __init__(self, exchange_id: str, exchange=None):
        if exchange is None:
            import ccxt.async_support as ccxt  # imported lazily so tests run without network

            if not hasattr(ccxt, exchange_id):
                raise ValueError(f"Unknown exchange {exchange_id!r} (see ccxt.exchanges)")
            exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        self.exchange = exchange

    async def candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        step_ms = timeframe_seconds(timeframe) * 1000
        since = int(time.time() * 1000) - step_ms * (limit + 1)
        rows: dict[int, Candle] = {}
        # page forward from `since`; many exchanges cap each response (300–1000 rows)
        for _ in range(50):
            batch = await self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=min(limit, 1000))
            if not batch:
                break
            for ts, o, h, low, c, v in batch:
                rows[int(ts)] = Candle(int(ts), float(o), float(h), float(low), float(c), float(v or 0))
            last = int(batch[-1][0])
            if last + step_ms > time.time() * 1000 or len(rows) >= limit or last < since:
                break
            since = last + step_ms
        if not rows:
            # some exchanges (e.g. Kraken) ignore old `since`; fall back to "latest N"
            batch = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=min(limit, 1000))
            for ts, o, h, low, c, v in batch:
                rows[int(ts)] = Candle(int(ts), float(o), float(h), float(low), float(c), float(v or 0))
        out = [rows[k] for k in sorted(rows)]
        return out[-limit:]

    async def price(self, symbol: str) -> float:
        ticker = await self.exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close") or ticker.get("bid")
        if not price:
            raise RuntimeError(f"No price for {symbol}")
        return float(price)

    async def close(self) -> None:
        await self.exchange.close()


class SyntheticFeed(DataFeed):
    """Seeded random-walk prices for offline demos and tests.

    It is clearly *not* the real market: regime-switching geometric Brownian
    motion, so strategies can be exercised without network access. Results on
    it say nothing about real performance.
    """

    START_PRICES = {"BTC": 60_000.0, "ETH": 3_000.0, "SOL": 150.0}

    def __init__(self, seed: int = 7, timeframe: str = "1h", history: int = 5000):
        self.seed = seed
        self.timeframe = timeframe
        self.history = history
        self._series: dict[str, list[Candle]] = {}
        self._live_step: dict[str, int] = {}

    def _generate(self, symbol: str, count: int) -> list[Candle]:
        rng = random.Random(f"{self.seed}:{symbol}")
        base = symbol.split("/")[0].upper()
        price = self.START_PRICES.get(base, 100.0)
        step = timeframe_seconds(self.timeframe)
        dt = step / 86400 / 365
        end = (int(time.time()) // step) * step
        ts = end - step * (count - 1)
        drift, vol = 0.3, 0.6
        out = []
        for _ in range(count):
            if rng.random() < 0.004:  # occasional regime change: bull, bear or chop
                drift = rng.choice([0.9, -0.7, 0.0, 0.3])
                vol = rng.choice([0.4, 0.6, 0.9])
            ret = (drift - vol * vol / 2) * dt + vol * math.sqrt(dt) * rng.gauss(0, 1)
            open_ = price
            close = price * math.exp(ret)
            wiggle = abs(rng.gauss(0, vol * math.sqrt(dt))) * price
            high = max(open_, close) + wiggle * 0.5
            low = min(open_, close) - wiggle * 0.5
            out.append(Candle(ts * 1000, open_, high, max(low, 1e-9), close, rng.uniform(10, 1000)))
            price = close
            ts += step
        return out

    def series(self, symbol: str) -> list[Candle]:
        if symbol not in self._series:
            self._series[symbol] = self._generate(symbol, self.history)
        return self._series[symbol]

    async def candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        if timeframe != self.timeframe:
            self.timeframe = timeframe
            self._series.clear()
        data = self.series(symbol)
        return data[-limit:]

    def advance(self, symbol: str) -> Candle:
        """Append one new candle (used by the paper loop in synthetic mode)."""
        data = self.series(symbol)
        rng = random.Random(f"{self.seed}:{symbol}:{len(data)}")
        last = data[-1]
        step_ms = timeframe_seconds(self.timeframe) * 1000
        ret = rng.gauss(0.0, 0.006)
        close = last.close * math.exp(ret)
        high = max(last.close, close) * (1 + abs(rng.gauss(0, 0.002)))
        low = min(last.close, close) * (1 - abs(rng.gauss(0, 0.002)))
        candle = Candle(last.ts + step_ms, last.close, high, low, close, rng.uniform(10, 1000))
        data.append(candle)
        return candle

    async def price(self, symbol: str) -> float:
        return self.series(symbol)[-1].close


def load_csv(path: str | Path) -> list[Candle]:
    """Read candles from a CSV with columns: timestamp,open,high,low,close,volume.

    timestamp may be epoch milliseconds, epoch seconds or ISO-8601.
    """
    from datetime import datetime

    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row or not row[0].strip():
                continue
            first = row[0].strip()
            try:
                num = float(first)
                ts = int(num if num > 1e11 else num * 1000)
            except ValueError:
                try:
                    ts = int(datetime.fromisoformat(first.replace("Z", "+00:00")).timestamp() * 1000)
                except ValueError:
                    continue  # header row
            o, h, low, c = (float(x) for x in row[1:5])
            v = float(row[5]) if len(row) > 5 and row[5] else 0.0
            out.append(Candle(ts, o, h, low, c, v))
    out.sort(key=lambda c: c.ts)
    return out


def make_feed(source: str, exchange_id: str, timeframe: str = "1h", seed: int = 7) -> DataFeed:
    if source == "synthetic":
        return SyntheticFeed(seed=seed, timeframe=timeframe)
    return ExchangeFeed(exchange_id)


async def gather_prices(feed: DataFeed, symbols: list[str]) -> dict[str, float]:
    prices = await asyncio.gather(*(feed.price(s) for s in symbols), return_exceptions=True)
    return {s: p for s, p in zip(symbols, prices) if isinstance(p, float)}
