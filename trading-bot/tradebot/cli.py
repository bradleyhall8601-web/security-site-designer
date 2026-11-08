"""Command line: `tradebot run` starts everything (trader + Telegram + dashboard) in one process."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys

from .backtest import format_summary, run_backtest
from .config import Settings
from .data import load_csv
from .learn import martingale_lesson
from .strategies import STRATEGIES, get_strategy


def build_settings(args: argparse.Namespace) -> Settings:
    s = Settings.from_env()
    if getattr(args, "synthetic", False):
        s.data_source = "synthetic"
    for attr in ("exchange", "timeframe", "strategy", "db"):
        value = getattr(args, attr, None)
        if value:
            setattr(s, "db_path" if attr == "db" else attr, value.lower() if attr == "exchange" else value)
    if getattr(args, "symbols", None):
        s.symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    if getattr(args, "poll", None):
        s.poll_seconds = args.poll
    if getattr(args, "port", None):
        s.web_port = args.port
    return s


async def cmd_backtest(args) -> int:
    s = build_settings(args)
    strategies = list(STRATEGIES) if args.strategy == "all" else [args.strategy or s.strategy]
    if args.csv:
        candles = load_csv(args.csv)
        results = []
        for name in strategies:
            r = run_backtest(candles, get_strategy(name), symbol=args.csv, timeframe=s.timeframe,
                             starting_cash=s.starting_cash, fee_rate=s.fee_rate, slippage=s.slippage,
                             risk_per_trade=s.risk_per_trade, max_position_fraction=s.max_position_fraction,
                             daily_loss_limit=s.daily_loss_limit, max_drawdown=s.max_drawdown)
            results.append(r.summary())
    else:
        from .app import TradeBotApp

        if args.strategy == "all":
            s.strategy = "trend"
        app = TradeBotApp(s)
        try:
            results = [await app.backtest(args.symbol, name, args.bars) for name in strategies]
        finally:
            await app.close()
    for r in results:
        if args.json:
            r = {k: v for k, v in r.items() if k not in ("trade_list", "equity_curve")}
            print(json.dumps(r, indent=2))
        else:
            print(format_summary(r))
            if "candles" in r:
                print(f"Candles:       {r['candles']} ({r['data_source']} data)")
            print()
    return 0


async def cmd_signal(args) -> int:
    from .app import TradeBotApp

    app = TradeBotApp(build_settings(args))
    try:
        for symbol in ([args.symbol] if args.symbol else app.settings.symbols):
            sym, sig = await app.signal(symbol, args.strategy)
            stop = f" · stop {sig.stop:,.2f}" if sig.stop else ""
            print(f"{sym}: {sig.action.upper()} at {sig.price:,.2f}{stop} — {sig.reason}")
    finally:
        await app.close()
    return 0


async def cmd_run(args) -> int:
    from .app import TradeBotApp

    settings = build_settings(args)
    app = TradeBotApp(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(getattr(signal, sig_name), stop.set)

    tasks = [asyncio.create_task(app.trader.run_forever(stop), name="trader")]
    bot = server = None
    if not args.no_telegram and settings.telegram_token:
        from .telegram_bot import TelegramBot

        bot = TelegramBot(app)
        await bot.start_polling()
        print("Telegram bot: polling. Send /start to your bot.")
    elif not args.no_telegram:
        print("Telegram bot: off (set TELEGRAM_TOKEN to turn it on).")

    if not args.no_web:
        import uvicorn

        from .web import create_web

        config = uvicorn.Config(create_web(app), host=settings.web_host, port=settings.web_port,
                                log_level="warning", lifespan="off")
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # we handle Ctrl+C ourselves
        tasks.append(asyncio.create_task(server.serve(), name="web"))
        print(f"Dashboard: http://{settings.web_host}:{settings.web_port}/")

    mode = "LIVE — real orders" if settings.mode == "live" else "paper — simulated fills"
    print(f"Trading: {mode} · {settings.strategy} · {', '.join(settings.symbols)} · {settings.timeframe} · "
          f"{'synthetic data' if settings.data_source == 'synthetic' else settings.exchange + ' prices'}")
    print("Press Ctrl+C to stop.")
    try:
        await stop.wait()
    finally:
        if server:
            server.should_exit = True
        if bot:
            await bot.stop()
        await asyncio.wait(tasks, timeout=10)
        await app.close()
    return 0


async def cmd_check(args) -> int:
    from .app import TradeBotApp

    s = build_settings(args)
    problems = s.validate()
    if problems:
        print("Configuration problems:\n- " + "\n- ".join(problems))
        return 1
    app = TradeBotApp(s)
    ok = True
    try:
        for symbol in s.symbols:
            try:
                price = await app.feed.price(symbol)
                print(f"✓ {symbol} price {price:,.2f} from {s.data_source if s.data_source == 'synthetic' else s.exchange}")
            except Exception as exc:
                ok = False
                print(f"✗ {symbol}: {type(exc).__name__}: {exc}")
        try:
            cash = await app.broker.cash(s.symbols[0])
            print(f"✓ {app.broker.mode} account cash: {cash:,.2f}")
        except Exception as exc:
            ok = False
            print(f"✗ account: {type(exc).__name__}: {exc}")
        print("✓ Telegram token set" if s.telegram_token else "• Telegram off (no TELEGRAM_TOKEN)")
    finally:
        await app.close()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradebot", description="Honest all-in-one trading bot.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--synthetic", action="store_true", help="offline practice data instead of the exchange")
        p.add_argument("--exchange", help="ccxt exchange id, e.g. kraken, coinbase, binance, binanceus")
        p.add_argument("--symbols", help="comma-separated markets, e.g. BTC/USD,ETH/USD")
        p.add_argument("--timeframe", help="1m 5m 15m 30m 1h 4h 1d 1w")
        p.add_argument("--db", help="SQLite file for the journal")
        p.add_argument("-v", "--verbose", action="store_true")

    p = sub.add_parser("run", help="trader + Telegram bot + web dashboard in one process")
    common(p)
    p.add_argument("--strategy", choices=list(STRATEGIES))
    p.add_argument("--poll", type=int, help="seconds between checks")
    p.add_argument("--port", type=int, help="dashboard port")
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--no-web", action="store_true")

    p = sub.add_parser("backtest", help="test a strategy on history (fees and slippage included)")
    common(p)
    p.add_argument("--symbol")
    p.add_argument("--strategy", choices=list(STRATEGIES) + ["all"])
    p.add_argument("--bars", type=int, default=2000)
    p.add_argument("--csv", help="backtest a CSV file: timestamp,open,high,low,close,volume")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("signal", help="print the current signal for each market")
    common(p)
    p.add_argument("--symbol")
    p.add_argument("--strategy", choices=list(STRATEGIES))

    p = sub.add_parser("check", help="check settings, prices and account access")
    common(p)
    p.add_argument("--strategy", choices=list(STRATEGIES))

    sub.add_parser("martingale", help="show why martingale / 'Smart Scaling' loses")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "martingale":
        print(martingale_lesson())
        return 0
    handler = {"run": cmd_run, "backtest": cmd_backtest, "signal": cmd_signal, "check": cmd_check}[args.command]
    try:
        return asyncio.run(handler(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
