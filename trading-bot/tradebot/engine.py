"""The trading loop: fetch candles, compute signals, manage stops, place orders, journal."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from .broker import Broker
from .config import Settings
from .data import DataFeed, SyntheticFeed, timeframe_seconds
from .risk import RiskGuard, position_size
from .storage import Position, Store, now_ms
from .strategies import BUY, SELL, Signal, Strategy, get_strategy

log = logging.getLogger("tradebot.engine")
Notifier = Callable[[str], Awaitable[None]]


class Trader:
    def __init__(self, settings: Settings, feed: DataFeed, broker: Broker, store: Store,
                 strategy: Strategy | None = None):
        self.settings, self.feed, self.broker, self.store = settings, feed, broker, store
        self.strategy = strategy or get_strategy(settings.strategy)
        self.guard = RiskGuard(settings.daily_loss_limit, settings.max_drawdown)
        self.guard.load(store.get("risk_guard", {}))
        self.last_ts: dict[str, int] = store.get("last_candle_ts", {}) or {}
        self.paused: bool = bool(store.get("paused", False))
        self.last_signal: dict[str, Signal] = {}
        self.prices: dict[str, float] = {}
        self.last_error: dict[str, str] = {}
        self.last_halt = ""
        self.steps = 0
        self.started_ms = now_ms()
        self._handlers: list[Notifier] = []
        self._lock = asyncio.Lock()

    # ---------- notifications ----------
    def on_event(self, handler: Notifier) -> None:
        self._handlers.append(handler)

    async def notify(self, text: str) -> None:
        log.info(text)
        self.store.log(text)
        for handler in self._handlers:
            try:
                await handler(text)
            except Exception:  # a broken notifier must never stop trading
                log.exception("notifier failed")

    # ---------- account ----------
    async def account(self) -> dict:
        positions = self.store.positions()
        cash = await self.broker.cash(self.settings.symbols[0])
        value = sum(p.qty * self.prices.get(s, p.entry) for s, p in positions.items())
        return {"cash": cash, "positions_value": value, "equity": cash + value, "positions": positions}

    # ---------- orders ----------
    async def _enter(self, symbol: str, price: float, signal: Signal) -> None:
        acct = await self.account()
        ok, why = self.guard.can_open(acct["equity"], now_ms())
        if not ok:
            if why != self.last_halt:
                self.last_halt = why
                await self.notify(f"⛔ Not opening {symbol}: {why}")
            return
        if signal.stop is None or price <= signal.stop:
            return
        cash = await self.broker.cash(symbol)
        qty = position_size(acct["equity"], cash, price, signal.stop, risk_per_trade=self.settings.risk_per_trade,
                            max_position_fraction=self.settings.max_position_fraction, fee_rate=self.settings.fee_rate)
        if qty * price < 1:
            await self.notify(f"ℹ️ {symbol} buy signal skipped: not enough cash for a position")
            return
        fill = await self.broker.buy(symbol, qty, price)
        if fill.qty <= 0:
            await self.notify(f"⚠️ {symbol} buy order did not fill")
            return
        stop = signal.stop
        self.store.save_position(Position(symbol, fill.qty, fill.price, stop, now_ms(), self.strategy.name,
                                          signal.reason, fill.fee))
        self.store.add_fill(mode=self.broker.mode, symbol=symbol, side="buy", qty=fill.qty, price=fill.price,
                            fee=fill.fee, pnl=None, reason=signal.reason, order_id=fill.order_id)
        risk = (fill.price - stop) * fill.qty
        await self.notify(
            f"🟢 BUY {fill.qty:.6g} {symbol} @ {fill.price:,.2f} ({self.broker.mode})\n"
            f"Why: {signal.reason}\nStop: {stop:,.2f} · risk ≈ {risk:,.2f} ({risk / acct['equity']:.2%} of equity)")

    async def _exit(self, position: Position, price: float, reason: str) -> None:
        fill = await self.broker.sell(position.symbol, position.qty, price)
        pnl = fill.price * fill.qty - fill.fee - position.entry * position.qty - position.entry_fee
        self.store.delete_position(position.symbol)
        self.store.add_fill(mode=self.broker.mode, symbol=position.symbol, side="sell", qty=fill.qty,
                            price=fill.price, fee=fill.fee, pnl=pnl, reason=reason, order_id=fill.order_id)
        emoji = "✅" if pnl > 0 else "🔴"
        await self.notify(f"{emoji} SELL {fill.qty:.6g} {position.symbol} @ {fill.price:,.2f} ({self.broker.mode})\n"
                          f"Why: {reason}\nP&L: {pnl:+,.2f} after fees")

    async def close_position(self, symbol: str, reason: str = "closed manually") -> bool:
        async with self._lock:
            position = self.store.positions().get(symbol)
            if not position:
                return False
            price = self.prices.get(symbol) or await self.feed.price(symbol)
            await self._exit(position, price, reason)
            return True

    async def close_all(self, reason: str = "closed manually") -> int:
        count = 0
        for symbol in list(self.store.positions()):
            if await self.close_position(symbol, reason):
                count += 1
        return count

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.store.set("paused", paused)

    async def reset_kill_switch(self) -> None:
        acct = await self.account()
        self.guard.reset(acct["equity"])
        self.last_halt = ""
        self.store.set("risk_guard", self.guard.to_dict())

    # ---------- the loop ----------
    async def step(self) -> None:
        async with self._lock:
            await self._step()

    async def _step(self) -> None:
        now = now_ms()
        synthetic = isinstance(self.feed, SyntheticFeed)
        step_ms = timeframe_seconds(self.settings.timeframe) * 1000
        positions = self.store.positions()
        for symbol in self.settings.symbols:
            try:
                if synthetic:
                    self.feed.advance(symbol)  # offline demo: one new candle per loop
                candles = await self.feed.candles(symbol, self.settings.timeframe, self.strategy.warmup + 150)
                closed = candles if synthetic else [c for c in candles if c.ts + step_ms <= now]
                if not closed:
                    continue
                price = closed[-1].close if synthetic else await self.feed.price(symbol)
                self.prices[symbol] = price
                self.last_error.pop(symbol, None)

                position = positions.get(symbol)
                if position and price <= position.stop:
                    await self._exit(position, price, f"stop-loss hit ({position.stop:,.2f})")
                    position = None

                last = closed[-1]
                if self.last_ts.get(symbol) == last.ts:
                    continue  # nothing new to decide on until the next candle closes
                self.last_ts[symbol] = last.ts
                signal = self.strategy.evaluate(closed)
                self.last_signal[symbol] = signal

                if position and signal.action == SELL:
                    await self._exit(position, price, signal.reason)
                elif position is None and signal.action == BUY and not self.paused:
                    await self._enter(symbol, price, signal)
            except Exception as exc:  # keep going with other symbols; report each new error once
                message = f"{type(exc).__name__}: {exc}"
                log.warning("%s: %s", symbol, message)
                if self.last_error.get(symbol) != message:
                    self.last_error[symbol] = message
                    await self.notify(f"⚠️ {symbol}: {message}")

        self.store.set("last_candle_ts", self.last_ts)
        acct = await self.account()
        self.guard.update(acct["equity"], now)
        self.store.set("risk_guard", self.guard.to_dict())
        self.store.record_equity(acct["equity"], acct["cash"], now)
        self.steps += 1

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        await self.notify(f"🤖 Trader started · {self.broker.mode} · {self.strategy.name} · "
                          f"{', '.join(self.settings.symbols)} · {self.settings.timeframe}")
        while not stop.is_set():
            try:
                await self.step()
            except Exception:
                log.exception("step failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.settings.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def status(self) -> dict:
        acct = await self.account()
        start = self.store.get("paper_starting_cash", self.settings.starting_cash) if self.broker.mode == "paper" else None
        return {
            "mode": self.broker.mode,
            "exchange": self.settings.exchange,
            "data_source": self.settings.data_source,
            "strategy": self.strategy.name,
            "strategy_title": self.strategy.title,
            "timeframe": self.settings.timeframe,
            "symbols": self.settings.symbols,
            "paused": self.paused,
            "halted": self.guard.halted_reason,
            "cash": acct["cash"],
            "equity": acct["equity"],
            "starting_cash": start,
            "return": (acct["equity"] / start - 1) if start else None,
            "peak": self.guard.peak,
            "prices": self.prices,
            "positions": [
                {"symbol": p.symbol, "qty": p.qty, "entry": p.entry, "stop": p.stop, "opened_ts": p.opened_ts,
                 "price": self.prices.get(p.symbol), "reason": p.reason,
                 "unrealized": (self.prices.get(p.symbol, p.entry) - p.entry) * p.qty}
                for p in acct["positions"].values()
            ],
            "signals": {s: {"action": sig.action, "reason": sig.reason, "price": sig.price, "stop": sig.stop}
                        for s, sig in self.last_signal.items()},
            "errors": self.last_error,
            "stats": self.store.trade_stats(),
            "steps": self.steps,
            "risk": {"per_trade": self.settings.risk_per_trade, "max_position": self.settings.max_position_fraction,
                     "daily_loss_limit": self.settings.daily_loss_limit, "max_drawdown": self.settings.max_drawdown},
        }
