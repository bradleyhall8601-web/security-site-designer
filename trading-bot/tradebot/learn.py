"""Plain-language lessons, plus a martingale simulator that shows why "Smart Scaling" fails."""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache


def binary_option_ev(payout: float, win_prob: float = 0.5) -> float:
    """Expected profit per 1 unit staked on a fixed-payout binary option."""
    return win_prob * payout - (1 - win_prob)


def breakeven_win_rate(payout: float) -> float:
    """Win rate needed just to break even at a given payout (0.92 -> 52.1%)."""
    return 1 / (1 + payout)


@dataclass
class MartingaleResult:
    sessions: int
    busted: int
    median_final: float
    average_final: float
    start: float
    worst_streak: int

    @property
    def bust_rate(self) -> float:
        return self.busted / self.sessions


@lru_cache(maxsize=16)
def simulate_martingale(*, start: float = 1000.0, base_stake: float = 10.0, payout: float = 0.92,
                        win_prob: float = 0.5, max_steps: int = 8, trades: int = 500,
                        sessions: int = 2000, seed: int = 1) -> MartingaleResult:
    """Simulate a 'Smart Scaling' series: after each loss, raise the stake so one win recovers
    everything plus the base profit. Repeat for `trades` bets per session."""
    rng = random.Random(seed)
    finals, busted, worst = [], 0, 0
    for _ in range(sessions):
        balance, stake, lost_in_series, streak = start, base_stake, 0.0, 0
        for _ in range(trades):
            if stake > balance:  # cannot fund the next step: the series is dead
                busted += 1
                break
            if rng.random() < win_prob:
                balance += stake * payout
                stake, lost_in_series, streak = base_stake, 0.0, 0
            else:
                balance -= stake
                lost_in_series += stake
                streak += 1
                worst = max(worst, streak)
                if streak >= max_steps:  # series limit reached: take the loss and restart
                    stake, lost_in_series, streak = base_stake, 0.0, 0
                else:
                    stake = (lost_in_series + base_stake * payout) / payout
        finals.append(balance)
    finals.sort()
    return MartingaleResult(sessions, busted, finals[len(finals) // 2], sum(finals) / len(finals), start, worst)


def martingale_lesson(payout: float = 0.92) -> str:
    r = simulate_martingale(payout=payout)
    ev = binary_option_ev(payout)
    return (
        "🎲 Why 'Smart Scaling' (martingale) loses\n\n"
        f"A {payout:.0%} payout binary option at a 50/50 guess returns {ev:+.1%} per bet on average. "
        f"You need a {breakeven_win_rate(payout):.1%} win rate just to break even.\n\n"
        "Martingale raises the stake after every loss so one win 'recovers' the series. It wins small "
        "amounts most of the time, then a losing streak needs a stake you cannot afford.\n\n"
        f"Simulation: {r.sessions:,} accounts of {r.start:,.0f}, base stake 10, up to 8 steps, 500 bets each:\n"
        f"• {r.bust_rate:.0%} could no longer fund the next step\n"
        f"• average ending balance {r.average_final:,.0f} (median {r.median_final:,.0f})\n"
        f"• longest losing streak seen: {r.worst_streak}\n\n"
        "Scaling up after losses does not change the odds; it only changes how big the final loss is. "
        "This bot sizes every trade from your equity and the stop distance, and never adds after a loss."
    )


SCAM_RED_FLAGS = """🚩 How to spot a fake 'AI trading bot'

1. The 'AI signal' is up/down on a short timer. That is a binary option, a bet, not a trade.
2. Pairs end in _OTC or trade on weekends: the broker makes up the price you bet against.
3. 'Smart Scaling', 'recovery series' or 'step-up': that is martingale (see /martingale).
4. The bot opens a broker account for you. The operator earns a share of what you lose.
5. The broker is not licensed where you live (check FCA, CFTC/NFA, ASIC, ESMA registers).
6. Reviews are screenshots of wins; there is no full, checkable trade history.
7. A demo that always looks great, then pressure to 'go real' and deposit.
8. Fine print says 'no guaranteed profit' while the page sells profit.

What honest tools do: show backtests with fees, drawdowns and losing trades; compare with simply
buying and holding; let you paper trade as long as you like; and never take custody of your money."""


HOW_IT_WORKS = """⚙️ How this bot works

• Data: real candles from the exchange you choose (ccxt), or an offline synthetic feed for practice.
• Strategies: trend (EMA cross with a 200 EMA filter), meanrev (RSI dip in an uptrend) and
  breakout (20-bar channel). Long only: it buys, then sells what it bought. No leverage.
• Every entry has a stop-loss. Size = (equity × risk per trade) ÷ stop distance, capped at
  the max position size. A 1% risk setting means a stopped trade loses about 1% of equity.
• Safety: daily loss limit and a max-drawdown kill switch stop new trades automatically.
• Paper mode (default) uses real prices with simulated fills, fees and slippage.
• Live mode sends real market orders and needs API keys plus an explicit confirmation phrase.
  Start on the exchange testnet (SANDBOX=true).
• Run /backtest first. If a strategy does not beat buy-and-hold after fees on your market, do not
  trade it with real money."""
