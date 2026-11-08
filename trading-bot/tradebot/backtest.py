"""Event-driven backtester with fees, slippage, stops and honest metrics.

Rules, so results are not flattered:
- a signal computed on candle i fills at the OPEN of candle i+1 (no look-ahead);
- every fill pays slippage and the fee rate;
- a stop that gaps fills at the open, not at the stop price;
- results are compared with simply buying and holding the same market.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Sequence

from .data import Candle, timeframe_seconds
from .risk import RiskGuard, position_size
from .strategies import BUY, SELL, Strategy


@dataclass
class Trade:
    symbol: str
    entry_ts: int
    entry_price: float
    qty: float
    stop: float
    exit_ts: int | None = None
    exit_price: float | None = None
    fees: float = 0.0
    pnl: float = 0.0
    exit_reason: str = ""
    entry_reason: str = ""

    @property
    def return_pct(self) -> float:
        cost = self.entry_price * self.qty
        return self.pnl / cost if cost else 0.0


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    timeframe: str
    start_ts: int
    end_ts: int
    starting_cash: float
    final_equity: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    buy_hold_return: float = 0.0
    fees_paid: float = 0.0
    halts: list[str] = field(default_factory=list)

    # ---- metrics ----
    @property
    def total_return(self) -> float:
        return self.final_equity / self.starting_cash - 1

    @property
    def years(self) -> float:
        return max((self.end_ts - self.start_ts) / 1000 / 86400 / 365.25, 1e-9)

    @property
    def cagr(self) -> float:
        if self.final_equity <= 0:
            return -1.0
        return (self.final_equity / self.starting_cash) ** (1 / self.years) - 1

    @property
    def max_drawdown(self) -> float:
        peak, worst = 0.0, 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            if peak:
                worst = max(worst, 1 - eq / peak)
        return worst

    @property
    def sharpe(self) -> float:
        eq = [e for _, e in self.equity_curve]
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        if var <= 0:
            return 0.0
        bars_per_year = 365.25 * 86400 / timeframe_seconds(self.timeframe)
        return mean / math.sqrt(var) * math.sqrt(bars_per_year)

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_ts is not None]

    @property
    def win_rate(self) -> float:
        closed = self.closed
        return sum(1 for t in closed if t.pnl > 0) / len(closed) if closed else 0.0

    @property
    def profit_factor(self) -> float:
        wins = sum(t.pnl for t in self.closed if t.pnl > 0)
        losses = -sum(t.pnl for t in self.closed if t.pnl < 0)
        if losses == 0:
            return float("inf") if wins > 0 else 0.0
        return wins / losses

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.closed if t.pnl > 0]
        return sum(wins) / len(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.closed if t.pnl < 0]
        return sum(losses) / len(losses) if losses else 0.0

    def verdict(self) -> str:
        n = len(self.closed)
        notes = []
        if n < 30:
            notes.append(f"only {n} trades: too few to trust, test a longer period")
        if self.total_return < self.buy_hold_return:
            notes.append("did worse than simply buying and holding")
        if self.total_return < 0:
            notes.append("lost money after fees")
        if self.max_drawdown > 0.25:
            notes.append(f"deep drawdown ({self.max_drawdown:.0%})")
        if not notes:
            notes.append("beat buy-and-hold on this data; past results do not predict future ones")
        return "; ".join(notes)

    def summary(self) -> dict:
        pf = self.profit_factor
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "timeframe": self.timeframe,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "starting_cash": round(self.starting_cash, 2),
            "final_equity": round(self.final_equity, 2),
            "total_return": round(self.total_return, 4),
            "buy_hold_return": round(self.buy_hold_return, 4),
            "cagr": round(self.cagr, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe": round(self.sharpe, 2),
            "trades": len(self.closed),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": None if math.isinf(pf) else round(pf, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "fees_paid": round(self.fees_paid, 2),
            "halts": self.halts,
            "verdict": self.verdict(),
        }

    def to_dict(self) -> dict:
        data = self.summary()
        data["trade_list"] = [asdict(t) for t in self.trades]
        step = max(1, math.ceil(len(self.equity_curve) / 400))  # keep payloads small for charts
        data["equity_curve"] = self.equity_curve[::step] + ([self.equity_curve[-1]] if self.equity_curve else [])
        return data


def run_backtest(candles: Sequence[Candle], strategy: Strategy, *, symbol: str = "", timeframe: str = "1h",
                 starting_cash: float = 10_000.0, fee_rate: float = 0.0026, slippage: float = 0.0005,
                 risk_per_trade: float = 0.01, max_position_fraction: float = 0.25,
                 daily_loss_limit: float = 0.03, max_drawdown: float = 0.15) -> BacktestResult:
    if len(candles) < strategy.warmup + 10:
        raise ValueError(f"Need at least {strategy.warmup + 10} candles for {strategy.name}, got {len(candles)}")

    signals = strategy.signals(candles)
    guard = RiskGuard(daily_loss_limit, max_drawdown)
    cash = starting_cash
    position: Trade | None = None
    result = BacktestResult(symbol, strategy.name, timeframe, candles[0].ts, candles[-1].ts, starting_cash, starting_cash)

    def close_position(ts: int, raw_price: float, reason: str) -> None:
        nonlocal cash, position
        assert position is not None
        price = raw_price * (1 - slippage)
        proceeds = price * position.qty
        fee = proceeds * fee_rate
        cash += proceeds - fee
        position.exit_ts, position.exit_price, position.exit_reason = ts, price, reason
        position.fees += fee
        position.pnl = proceeds - fee - position.entry_price * position.qty - (position.fees - fee)
        result.fees_paid += fee
        position = None

    for j in range(1, len(candles)):
        bar, sig = candles[j], signals[j - 1]
        equity_at_open = cash + (position.qty * bar.open if position else 0.0)

        # 1) act on the previous candle's signal at this candle's open
        if position and sig.action == SELL:
            close_position(bar.ts, bar.open, sig.reason)
        elif position is None and sig.action == BUY and sig.stop is not None:
            ok, why = guard.can_open(equity_at_open, bar.ts)
            if not ok:
                if not result.halts or result.halts[-1] != why:
                    result.halts.append(why)
            elif bar.open > sig.stop:
                entry = bar.open * (1 + slippage)
                qty = position_size(equity_at_open, cash, entry, sig.stop, risk_per_trade=risk_per_trade,
                                    max_position_fraction=max_position_fraction, fee_rate=fee_rate)
                if qty > 0:
                    cost = entry * qty
                    fee = cost * fee_rate
                    cash -= cost + fee
                    result.fees_paid += fee
                    position = Trade(symbol, bar.ts, entry, qty, sig.stop, fees=fee, entry_reason=sig.reason)
                    result.trades.append(position)

        # 2) stop-loss inside this candle (a gap below the stop fills at the open)
        if position and bar.low <= position.stop:
            fill = bar.open if bar.open <= position.stop else position.stop
            close_position(bar.ts, fill, "stop-loss")

        equity = cash + (position.qty * bar.close if position else 0.0)
        guard.update(equity, bar.ts)
        result.equity_curve.append((bar.ts, equity))

    if position:  # mark the open trade to market at the end
        close_position(candles[-1].ts, candles[-1].close, "end of test")
        result.equity_curve[-1] = (candles[-1].ts, cash)

    result.final_equity = cash
    first_open = candles[1].open
    result.buy_hold_return = (candles[-1].close * (1 - slippage) * (1 - fee_rate)) / (first_open * (1 + slippage) * (1 + fee_rate)) - 1
    return result


def format_summary(s: dict) -> str:
    pf = "∞" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
    return (
        f"{s['strategy']} on {s['symbol'] or 'data'} ({s['timeframe']})\n"
        f"Return:        {s['total_return']:+.2%}   (buy & hold {s['buy_hold_return']:+.2%})\n"
        f"CAGR:          {s['cagr']:+.2%}\n"
        f"Max drawdown:  {s['max_drawdown']:.2%}\n"
        f"Sharpe:        {s['sharpe']:.2f}\n"
        f"Trades:        {s['trades']}   win rate {s['win_rate']:.1%}   profit factor {pf}\n"
        f"Avg win/loss:  {s['avg_win']:+,.2f} / {s['avg_loss']:+,.2f}\n"
        f"Fees paid:     {s['fees_paid']:,.2f}\n"
        f"Final equity:  {s['final_equity']:,.2f} from {s['starting_cash']:,.2f}\n"
        f"Verdict:       {s['verdict']}"
    )
