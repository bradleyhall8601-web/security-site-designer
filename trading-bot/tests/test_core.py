import math

import pytest

from conftest import make_candles
from tradebot import indicators as ind
from tradebot.backtest import run_backtest
from tradebot.config import LIVE_CONFIRM_PHRASE, Settings
from tradebot.data import Candle, SyntheticFeed, load_csv
from tradebot.learn import binary_option_ev, breakeven_win_rate, simulate_martingale
from tradebot.risk import RiskGuard, position_size
from tradebot.strategies import BUY, HOLD, SELL, STRATEGIES, Signal, Strategy, get_strategy


# ---------- indicators ----------
def test_sma_and_ema():
    assert ind.sma([1, 2, 3, 4, 5], 3) == [None, None, 2, 3, 4]
    e = ind.ema([1, 2, 3, 4, 5], 3)
    assert e[:2] == [None, None] and e[2] == 2 and e[3] == pytest.approx(3) and e[4] == pytest.approx(4)


def test_rsi_extremes():
    assert ind.rsi(list(range(1, 30)), 14)[-1] == 100.0
    assert ind.rsi(list(range(30, 1, -1)), 14)[-1] == 0.0
    flat_up_down = [10, 11] * 20
    assert 40 < ind.rsi(flat_up_down, 14)[-1] < 60


def test_atr_constant_range():
    candles = [Candle(i, 100, 101, 99, 100, 1) for i in range(30)]
    assert ind.atr(candles, 14)[-1] == pytest.approx(2.0)


def test_indicators_are_causal():
    closes = [100 + math.sin(i / 5) * 10 for i in range(300)]
    full = ind.ema(closes, 20)
    part = ind.ema(closes[:200], 20)
    assert full[:200] == part  # adding future data never changes past values


# ---------- risk ----------
def test_position_size_risks_the_right_amount():
    qty = position_size(10_000, 10_000, 100, 95, risk_per_trade=0.01, max_position_fraction=1)
    assert qty == pytest.approx(20)  # 20 units × $5 stop distance = $100 = 1% of equity


def test_position_size_caps_and_rejects():
    assert position_size(10_000, 10_000, 100, 99.9, risk_per_trade=0.01, max_position_fraction=0.25) == pytest.approx(25)
    assert position_size(10_000, 500, 100, 90, risk_per_trade=0.05, max_position_fraction=1, fee_rate=0) == pytest.approx(5)
    assert position_size(10_000, 10_000, 100, 100, risk_per_trade=0.01, max_position_fraction=1) == 0
    assert position_size(10_000, 10_000, 100, 101, risk_per_trade=0.01, max_position_fraction=1) == 0


def test_size_never_grows_after_a_loss():
    before = position_size(10_000, 10_000, 100, 95, risk_per_trade=0.01, max_position_fraction=1)
    after = position_size(9_000, 9_000, 100, 95, risk_per_trade=0.01, max_position_fraction=1)
    assert after < before


def test_risk_guard_drawdown_and_daily_limit():
    day = 86_400_000
    g = RiskGuard(daily_loss_limit=0.03, max_drawdown=0.10)
    assert g.can_open(10_000, 0)[0]
    ok, why = g.can_open(9_600, 1000)
    assert not ok and "daily" in why
    assert g.can_open(9_600, day + 1)[0]  # new UTC day resets the daily stop
    ok, why = g.can_open(8_900, day + 2)
    assert not ok and "drawdown" in why
    assert not g.can_open(9_900, 5 * day)[0]  # kill switch stays on until reset
    g.reset(8_900)
    assert g.can_open(8_900, 5 * day)[0]


# ---------- strategies ----------
def test_every_strategy_runs_on_synthetic_data():
    candles = SyntheticFeed(seed=3).series("BTC/USD")[:1500]
    for name in STRATEGIES:
        s = get_strategy(name)
        sigs = s.signals(candles)
        assert len(sigs) == len(candles)
        assert all(x.action in (BUY, SELL, HOLD) for x in sigs)
        assert all(x.stop < x.price for x in sigs if x.action == BUY)
        assert s.evaluate(candles) == sigs[-1]


def test_strategy_signals_are_causal():
    candles = SyntheticFeed(seed=5).series("ETH/USD")[:1200]
    for name in STRATEGIES:
        s = get_strategy(name)
        assert s.signals(candles)[:900] == s.signals(candles[:900])


def test_unknown_strategy():
    with pytest.raises(ValueError):
        get_strategy("martingale")


# ---------- backtest ----------
class Scripted(Strategy):
    """Buys on bar `buy_at`, sells on bar `sell_at`, stop `stop_pct` below."""
    name = "scripted"
    warmup = 0

    def __init__(self, buy_at, sell_at=None, stop_pct=0.05):
        self.buy_at, self.sell_at, self.stop_pct = buy_at, sell_at, stop_pct

    def signals(self, candles):
        out = []
        for i, c in enumerate(candles):
            if i == self.buy_at:
                out.append(Signal(BUY, "test", c.close, stop=c.close * (1 - self.stop_pct)))
            elif i == self.sell_at:
                out.append(Signal(SELL, "test exit", c.close))
            else:
                out.append(Signal(HOLD, "", c.close))
        return out


def test_backtest_fills_at_next_open_with_costs():
    closes = [100.0] * 15 + [110.0] * 15
    candles = make_candles(closes)
    r = run_backtest(candles, Scripted(buy_at=14, sell_at=20), fee_rate=0.001, slippage=0.001,
                     risk_per_trade=0.01, max_position_fraction=0.5)
    t = r.trades[0]
    assert t.entry_ts == candles[15].ts  # signal on bar 14 → fill at bar 15 open (=100, not 110)
    assert t.entry_price == pytest.approx(100 * 1.001)
    assert t.exit_price == pytest.approx(110 * 0.999)
    gross = (t.exit_price - t.entry_price) * t.qty
    assert t.pnl == pytest.approx(gross - t.fees)
    assert r.final_equity == pytest.approx(10_000 + t.pnl)
    assert r.fees_paid == pytest.approx(t.fees)


def test_backtest_stop_loss_and_gap():
    closes = [100.0] * 15 + [99.0, 98.0, 80.0, 80.0] + [80.0] * 10
    candles = make_candles(closes, spread=0)
    r = run_backtest(candles, Scripted(buy_at=14, stop_pct=0.05), fee_rate=0, slippage=0,
                     risk_per_trade=0.01, max_position_fraction=1)
    t = r.trades[0]
    assert t.exit_reason == "stop-loss"
    # bar 17 opens at 98 (above the 95 stop) and falls to 80: the stop fills at 95
    assert t.exit_price == pytest.approx(95.0)
    assert t.exit_ts == candles[17].ts
    assert t.pnl == pytest.approx(-5 * t.qty)


def test_backtest_gap_below_stop_fills_at_open():
    candles = make_candles([100.0] * 15, spread=0)
    candles.append(Candle(candles[-1].ts + 3_600_000, 90.0, 90.0, 88.0, 89.0, 1))  # opens below the 95 stop
    candles += [Candle(candles[-1].ts + 3_600_000 * (k + 1), 89, 89, 89, 89, 1) for k in range(10)]
    r = run_backtest(candles, Scripted(buy_at=13), fee_rate=0, slippage=0, max_position_fraction=1)
    t = r.trades[0]
    assert t.exit_reason == "stop-loss" and t.exit_price == pytest.approx(90.0)


def test_backtest_metrics_and_dict():
    candles = SyntheticFeed(seed=11).series("BTC/USD")[:3000]
    r = run_backtest(candles, get_strategy("breakout"), symbol="BTC/USD")
    s = r.to_dict()
    assert s["trades"] == len(r.closed) > 0
    assert 0 <= s["max_drawdown"] < 1
    assert len(s["equity_curve"]) <= 402
    assert s["final_equity"] == pytest.approx(r.equity_curve[-1][1], abs=0.01)
    assert isinstance(s["verdict"], str) and s["verdict"]


def test_backtest_needs_enough_data():
    with pytest.raises(ValueError):
        run_backtest(make_candles([1.0] * 50), get_strategy("trend"))


# ---------- data ----------
def test_synthetic_feed_is_deterministic_and_advances():
    a, b = SyntheticFeed(seed=1), SyntheticFeed(seed=1)
    assert a.series("BTC/USD")[-1] == b.series("BTC/USD")[-1]
    n = len(a.series("BTC/USD"))
    c = a.advance("BTC/USD")
    assert len(a.series("BTC/USD")) == n + 1 and c.open == a.series("BTC/USD")[-2].close


def test_load_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("timestamp,open,high,low,close,volume\n"
                 "2024-01-01T01:00:00Z,2,3,1,2.5,10\n1704067200,1,2,0.5,1.5,5\n")
    c = load_csv(p)
    assert [x.close for x in c] == [1.5, 2.5] and c[0].ts == 1704067200000


# ---------- config ----------
def test_live_mode_requires_keys_and_confirmation():
    s = Settings(mode="live")
    problems = " ".join(s.validate())
    assert "API_KEY" in problems and "LIVE_CONFIRM" in problems
    s = Settings(mode="live", api_key="k", api_secret="s", live_confirm=LIVE_CONFIRM_PHRASE)
    assert s.validate() == []


def test_public_dashboard_requires_token():
    assert Settings(web_host="0.0.0.0").validate()
    assert Settings(web_host="0.0.0.0", web_token="x").validate() == []


# ---------- learn ----------
def test_binary_option_math():
    assert binary_option_ev(0.92) == pytest.approx(-0.04)
    assert breakeven_win_rate(0.92) == pytest.approx(0.5208, abs=1e-4)


def test_martingale_ruins_most_accounts():
    r = simulate_martingale(sessions=500, trades=500)
    assert r.bust_rate > 0.5
    assert r.median_final < r.start
