"""Engine, brokers, exchange feed, web API and Telegram wiring, with fake exchanges (no network)."""

import time

import pytest
from fastapi.testclient import TestClient

from tradebot.app import TradeBotApp
from tradebot.broker import LiveBroker, PaperBroker
from tradebot.data import ExchangeFeed, SyntheticFeed
from tradebot.engine import Trader
from tradebot.storage import Store
from tradebot.strategies import BUY, HOLD, SELL, Signal, Strategy
from tradebot.web import create_web


class Manual(Strategy):
    """Returns whatever signal the test sets."""
    name = "manual"
    warmup = 0

    def __init__(self):
        self.next = Signal(HOLD, "", 0)

    def signals(self, candles):
        return [Signal(HOLD, "", c.close) for c in candles[:-1]] + [
            Signal(self.next.action, self.next.reason, candles[-1].close,
                   stop=None if self.next.stop is None else candles[-1].close * self.next.stop)]


def make_trader(settings, strategy=None):
    store = Store(settings.db_path)
    feed = SyntheticFeed(seed=2)
    broker = PaperBroker(store, settings.starting_cash, settings.fee_rate, settings.slippage)
    return Trader(settings, feed, broker, store, strategy), store, feed


async def test_paper_trader_buy_then_sell_keeps_books_consistent(settings):
    strat = Manual()
    trader, store, feed = make_trader(settings, strat)
    events = []

    async def capture(text):
        events.append(text)
    trader.on_event(capture)

    strat.next = Signal(BUY, "unit test entry", 0, stop=0.95)
    await trader.step()
    pos = store.positions()["BTC/USD"]
    assert pos.qty > 0 and pos.stop < pos.entry
    # loss if stopped = stop distance + round-trip fees ≈ 1% of equity
    risk = (pos.entry - pos.stop) * pos.qty + pos.entry * pos.qty * settings.fee_rate * 2
    assert risk == pytest.approx(settings.starting_cash * settings.risk_per_trade, rel=0.05)
    assert any("BUY" in e for e in events)

    strat.next = Signal(SELL, "unit test exit", 0)
    await trader.step()
    assert store.positions() == {}
    fills = store.fills()
    assert [f["side"] for f in fills] == ["sell", "buy"]
    cash = await trader.broker.cash()
    assert cash == pytest.approx(settings.starting_cash + fills[0]["pnl"], rel=1e-9)
    assert store.trade_stats()["closed_trades"] == 1
    assert store.equity_history()[-1]["equity"] == pytest.approx(cash)


async def test_stop_loss_exits_on_price(settings):
    strat = Manual()
    trader, store, feed = make_trader(settings, strat)
    strat.next = Signal(BUY, "entry", 0, stop=0.95)
    await trader.step()
    pos = store.positions()["BTC/USD"]
    store.save_position(type(pos)(**{**pos.__dict__, "stop": pos.entry * 10}))  # force the stop above price
    strat.next = Signal(HOLD, "", 0)
    await trader.step()
    assert store.positions() == {}
    assert "stop-loss" in store.fills()[0]["reason"]


async def test_pause_blocks_new_entries_and_survives_restart(settings):
    strat = Manual()
    trader, store, _ = make_trader(settings, strat)
    trader.set_paused(True)
    strat.next = Signal(BUY, "entry", 0, stop=0.95)
    await trader.step()
    assert store.positions() == {}
    again = Trader(settings, SyntheticFeed(seed=2), trader.broker, store, strat)
    assert again.paused


async def test_kill_switch_blocks_entries(settings):
    strat = Manual()
    trader, store, _ = make_trader(settings, strat)
    trader.guard.peak = settings.starting_cash * 2  # pretend we are 50% below peak
    strat.next = Signal(BUY, "entry", 0, stop=0.95)
    msgs = []

    async def capture(text):
        msgs.append(text)
    trader.on_event(capture)
    await trader.step()
    assert store.positions() == {}
    assert any("kill switch" in m for m in msgs)
    await trader.reset_kill_switch()
    await trader.step()
    assert "BTC/USD" in store.positions()


async def test_close_all(settings):
    strat = Manual()
    trader, store, _ = make_trader(settings, strat)
    strat.next = Signal(BUY, "entry", 0, stop=0.95)
    await trader.step()
    assert await trader.close_all() == 1
    assert store.positions() == {}


async def test_errors_do_not_stop_other_symbols(settings):
    settings.symbols = ["BTC/USD", "BAD/USD"]
    trader, store, feed = make_trader(settings)

    original = feed.candles

    async def candles(symbol, timeframe, limit):
        if symbol == "BAD/USD":
            raise RuntimeError("exchange down")
        return await original(symbol, timeframe, limit)
    feed.candles = candles
    await trader.step()
    assert "BTC/USD" in trader.prices
    assert "exchange down" in trader.last_error["BAD/USD"]


# ---------- exchange feed with a fake ccxt exchange ----------
class FakeExchange:
    def __init__(self, n=2500, step_ms=3_600_000):
        now = int(time.time() * 1000) // step_ms * step_ms
        self.rows = [[now - (n - i) * step_ms, 100 + i, 101 + i, 99 + i, 100.5 + i, 5] for i in range(n)]
        self.calls = 0
        self.orders = []
        self.markets = {"BTC/USD": {"quote": "USD", "limits": {"amount": {"min": 0.0001}}}}

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls += 1
        rows = [r for r in self.rows if since is None or r[0] >= since]
        return rows[:min(limit or 720, 720)]  # caps each page like real exchanges

    async def fetch_ticker(self, symbol):
        return {"last": self.rows[-1][4]}

    async def load_markets(self):
        return self.markets

    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"

    async def fetch_balance(self):
        return {"free": {"USD": 5000.0}}

    async def create_order(self, symbol, type_, side, amount):
        self.orders.append((symbol, type_, side, amount))
        return {"id": f"o{len(self.orders)}", "filled": None, "average": None}

    async def fetch_order(self, order_id, symbol):
        i = int(order_id[1:]) - 1
        return {"id": order_id, "filled": self.orders[i][3], "average": 2000.0,
                "fee": {"cost": 1.5, "currency": "USD"}}

    async def close(self):
        pass


async def test_exchange_feed_paginates():
    ex = FakeExchange()
    feed = ExchangeFeed("kraken", exchange=ex)
    candles = await feed.candles("BTC/USD", "1h", 2000)
    assert len(candles) == 2000 and ex.calls >= 3
    assert all(b.ts - a.ts == 3_600_000 for a, b in zip(candles, candles[1:]))
    assert await feed.price("BTC/USD") == ex.rows[-1][4]


async def test_live_broker_places_market_orders():
    ex = FakeExchange()
    broker = LiveBroker("kraken", "k", "s", exchange=ex)
    assert await broker.cash("BTC/USD") == 5000.0
    fill = await broker.buy("BTC/USD", 0.123456, 1990.0)
    assert ex.orders[-1] == ("BTC/USD", "market", "buy", 0.1235)
    assert fill.price == 2000.0 and fill.fee == 1.5 and fill.qty == 0.1235
    with pytest.raises(RuntimeError, match="minimum"):
        await broker.sell("BTC/USD", 0.00001, 2000)


async def test_trader_runs_live_broker_end_to_end(settings):
    """Live mode wiring with a fake exchange: buy, journal, sell."""
    ex = FakeExchange()
    store = Store(settings.db_path)
    strat = Manual()
    settings.data_source = "exchange"
    trader = Trader(settings, ExchangeFeed("kraken", exchange=ex), LiveBroker("kraken", "k", "s", exchange=ex),
                    store, strat)
    strat.next = Signal(BUY, "entry", 0, stop=0.95)
    await trader.step()
    assert ex.orders and ex.orders[0][2] == "buy"
    assert store.fills()[0]["mode"] == "live"
    strat.next = Signal(SELL, "exit", 0)
    trader.last_ts.clear()  # act as if the next candle has closed
    await trader.step()
    assert ex.orders[-1][2] == "sell" and store.positions() == {}
    assert store.fills()[0]["reason"] == "exit"


# ---------- web ----------
def test_web_api(settings):
    app = TradeBotApp(settings)
    client = TestClient(create_web(app))
    assert "TradeBot" in client.get("/").text
    st = client.get("/api/status").json()
    assert st["mode"] == "paper" and st["equity"] == pytest.approx(settings.starting_cash)
    bt = client.get("/api/backtest?strategy=breakout&bars=1500").json()
    assert bt["strategy"] == "breakout" and bt["candles"] == 1500
    assert client.get("/api/signal?symbol=eth").json()["symbol"] == "ETH/USD"
    assert client.post("/api/pause").status_code == 403  # no X-Tradebot header (CSRF guard)
    assert client.post("/api/pause", headers={"X-Tradebot": "1"}).json() == {"paused": True}
    assert client.post("/api/step", headers={"X-Tradebot": "1"}).json()["steps"] == 1
    assert len(client.get("/api/equity").json()) == 1
    assert "martingale" in client.get("/api/learn").json()["martingale"].lower()
    assert client.get("/api/backtest?strategy=nope").status_code == 400


def test_web_token(settings):
    settings.web_token = "secret"
    client = TestClient(create_web(TradeBotApp(settings)))
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert client.get("/api/status?token=secret").status_code == 200


# ---------- telegram ----------
class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, user_id, chat_id=None):
        self.effective_user = type("U", (), {"id": user_id})()
        self.effective_chat = type("C", (), {"id": chat_id or user_id})()
        self.effective_message = FakeMessage()


class FakeContext:
    def __init__(self, *args):
        self.args = list(args)


async def test_telegram_owner_lock_and_commands(settings):
    from tradebot.telegram_bot import TelegramBot

    settings.telegram_token = "123456:TEST"
    app = TradeBotApp(settings)
    bot = TelegramBot(app)
    start, status, backtest = bot._guard(bot.start), bot._guard(bot.status), bot._guard(bot.backtest)

    owner = FakeUpdate(42)
    await start(owner, FakeContext())
    assert app.store.get("telegram_owner") == 42
    assert "PAPER" in owner.effective_message.replies[0]

    stranger = FakeUpdate(99)
    await status(stranger, FakeContext())
    assert "private" in stranger.effective_message.replies[0]

    await status(owner, FakeContext())
    assert "Equity" in owner.effective_message.replies[-1]
    await backtest(owner, FakeContext("BTC", "breakout", "1500"))
    assert "Verdict" in owner.effective_message.replies[-1]
    await bot._guard(bot.signal)(owner, FakeContext("eth"))
    assert owner.effective_message.replies[-1].startswith("ETH/USD")
    await bot._guard(bot.martingale)(owner, FakeContext())
    assert "martingale" in owner.effective_message.replies[-1].lower()
