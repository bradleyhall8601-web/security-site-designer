"""Wires settings, storage, data feed, broker and trader into one object that the CLI,
Telegram bot and web dashboard all share."""

from __future__ import annotations

from .backtest import run_backtest
from .broker import Broker, LiveBroker, PaperBroker
from .config import Settings
from .data import DataFeed, make_feed
from .engine import Trader
from .storage import Store
from .strategies import Signal, get_strategy


class TradeBotApp:
    def __init__(self, settings: Settings, feed: DataFeed | None = None, broker: Broker | None = None,
                 store: Store | None = None):
        problems = settings.validate()
        if problems:
            raise SystemExit("Configuration problems:\n- " + "\n- ".join(problems))
        self.settings = settings
        self.store = store or Store(settings.db_path)
        self.feed = feed or make_feed(settings.data_source, settings.exchange, settings.timeframe)
        if broker is None:
            if settings.mode == "live":
                broker = LiveBroker(settings.exchange, settings.api_key, settings.api_secret,
                                    settings.api_password, sandbox=settings.sandbox)
            else:
                broker = PaperBroker(self.store, settings.starting_cash, settings.fee_rate, settings.slippage)
        self.broker = broker
        self.trader = Trader(settings, self.feed, self.broker, self.store)

    def normalize_symbol(self, symbol: str | None) -> str:
        if not symbol:
            return self.settings.symbols[0]
        s = symbol.upper().replace("-", "/").replace("_", "/")
        if "/" not in s:
            quote = self.settings.symbols[0].split("/")[1] if "/" in self.settings.symbols[0] else "USD"
            s = f"{s}/{quote}"
        return s

    async def backtest(self, symbol: str | None = None, strategy: str | None = None, bars: int = 2000) -> dict:
        symbol = self.normalize_symbol(symbol)
        strat = get_strategy(strategy or self.settings.strategy)
        bars = max(strat.warmup + 50, min(int(bars), 20_000))
        candles = await self.feed.candles(symbol, self.settings.timeframe, bars)
        s = self.settings
        result = run_backtest(candles, strat, symbol=symbol, timeframe=s.timeframe, starting_cash=s.starting_cash,
                              fee_rate=s.fee_rate, slippage=s.slippage, risk_per_trade=s.risk_per_trade,
                              max_position_fraction=s.max_position_fraction, daily_loss_limit=s.daily_loss_limit,
                              max_drawdown=s.max_drawdown)
        data = result.to_dict()
        data["candles"] = len(candles)
        data["data_source"] = s.data_source
        return data

    async def signal(self, symbol: str | None = None, strategy: str | None = None) -> tuple[str, Signal]:
        symbol = self.normalize_symbol(symbol)
        strat = get_strategy(strategy or self.settings.strategy)
        candles = await self.feed.candles(symbol, self.settings.timeframe, strat.warmup + 150)
        if self.settings.data_source == "exchange":
            from .data import timeframe_seconds
            from .storage import now_ms

            step = timeframe_seconds(self.settings.timeframe) * 1000
            candles = [c for c in candles if c.ts + step <= now_ms()]
        return symbol, strat.evaluate(candles)

    async def close(self) -> None:
        await self.feed.close()
        if self.broker is not None:
            await self.broker.close()
        self.store.close()
