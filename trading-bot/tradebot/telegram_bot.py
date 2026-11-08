"""Telegram bot: control the trader, run backtests and signals, get trade alerts."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from .app import TradeBotApp
from .backtest import format_summary
from .learn import HOW_IT_WORKS, SCAM_RED_FLAGS, martingale_lesson
from .strategies import STRATEGIES

log = logging.getLogger("tradebot.telegram")

COMMANDS = [
    ("status", "Balance, positions and latest signals"),
    ("positions", "Open positions with stops"),
    ("trades", "Recent fills and P&L"),
    ("signal", "Current signal: /signal BTC trend"),
    ("backtest", "Backtest: /backtest BTC trend 2000"),
    ("strategies", "List the strategies"),
    ("pause", "Stop opening new trades"),
    ("resume", "Allow new trades again"),
    ("close", "Close one position: /close BTC/USD"),
    ("closeall", "Close every position now"),
    ("resetrisk", "Clear the drawdown kill switch"),
    ("howitworks", "How the bot trades"),
    ("martingale", "Why 'Smart Scaling' loses"),
    ("redflags", "How to spot a fake AI trading bot"),
    ("help", "All commands"),
]


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pre(text: str) -> str:
    return f"<pre>{html.escape(text)}</pre>"


class TelegramBot:
    def __init__(self, app: TradeBotApp):
        self.app = app
        token = app.settings.telegram_token
        if not token:
            raise SystemExit("Set TELEGRAM_TOKEN (create a bot with @BotFather) to run the Telegram bot.")
        self.application = Application.builder().token(token).build()
        handlers = {
            "start": self.start, "help": self.help, "status": self.status, "positions": self.positions,
            "trades": self.trades, "signal": self.signal, "backtest": self.backtest,
            "strategies": self.strategies, "pause": self.pause, "resume": self.resume, "close": self.close,
            "closeall": self.closeall, "resetrisk": self.resetrisk, "howitworks": self.howitworks,
            "martingale": self.martingale, "redflags": self.redflags,
        }
        for name, fn in handlers.items():
            self.application.add_handler(CommandHandler(name, self._guard(fn)))
        app.trader.on_event(self.broadcast)

    # ---------- access control ----------
    def allowed_ids(self) -> list[int]:
        configured = self.app.settings.telegram_allowed_users
        if configured:
            return configured
        owner = self.app.store.get("telegram_owner")
        return [owner] if owner else []

    def _guard(self, fn):
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            if user is None or update.effective_message is None:
                return
            allowed = self.allowed_ids()
            if not allowed and fn.__name__ == "start":
                # first person to /start becomes the owner when no allow-list is configured
                self.app.store.set("telegram_owner", user.id)
                self.app.store.set("telegram_chats", [update.effective_chat.id])
                allowed = [user.id]
            if user.id not in allowed:
                await update.effective_message.reply_text(
                    "This bot is private. Ask the owner to add your Telegram ID "
                    f"({user.id}) to TELEGRAM_ALLOWED_USERS.")
                return
            chats = set(self.app.store.get("telegram_chats", []) or [])
            if update.effective_chat.id not in chats:
                chats.add(update.effective_chat.id)
                self.app.store.set("telegram_chats", sorted(chats))
            try:
                await fn(update, context)
            except Exception as exc:
                log.exception("command failed")
                await update.effective_message.reply_text(f"⚠️ {type(exc).__name__}: {exc}")
        return wrapped

    async def broadcast(self, text: str) -> None:
        for chat_id in self.app.store.get("telegram_chats", []) or []:
            try:
                await self.application.bot.send_message(chat_id, text[:4000])
            except Exception:
                log.exception("could not message chat %s", chat_id)

    async def reply(self, update: Update, text: str, pre: bool = False) -> None:
        if pre:
            await update.effective_message.reply_text(_pre(text[:3900]), parse_mode=ParseMode.HTML)
        else:
            await update.effective_message.reply_text(text[:4000])

    # ---------- commands ----------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        s = self.app.settings
        await self.reply(update,
            f"👋 TradeBot is running in {s.mode.upper()} mode on {s.exchange} "
            f"({'synthetic practice data' if s.data_source == 'synthetic' else 'real prices'}).\n"
            f"Strategy: {s.strategy} · markets: {', '.join(s.symbols)} · {s.timeframe} candles.\n\n"
            "No profit is promised. Backtest first (/backtest), paper trade, and only use money you can "
            "afford to lose.\n\nYou will get a message for every trade. /help lists all commands.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, "\n".join(f"/{c} — {d}" for c, d in COMMANDS))

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        st = await self.app.trader.status()
        lines = [f"Mode: {st['mode']} · {st['strategy']} · {st['timeframe']}",
                 f"Equity: {st['equity']:,.2f}  (cash {st['cash']:,.2f})"]
        if st["return"] is not None:
            lines.append(f"Since start: {st['return']:+.2%} from {st['starting_cash']:,.2f}")
        stats = st["stats"]
        lines.append(f"Closed trades: {stats['closed_trades']} · win rate {stats['win_rate']:.0%} · "
                     f"realized {stats['realized_pnl']:+,.2f}")
        lines.append("New trades: " + ("PAUSED" if st["paused"] else "allowed"))
        if st["halted"]:
            lines.append(f"Kill switch: {st['halted']}")
        for p in st["positions"]:
            lines.append(f"• {p['symbol']} {p['qty']:.6g} @ {p['entry']:,.2f} stop {p['stop']:,.2f} "
                         f"→ {p['unrealized']:+,.2f}")
        for sym, sig in st["signals"].items():
            lines.append(f"Signal {sym}: {sig['action'].upper()} — {sig['reason']}")
        for sym, err in st["errors"].items():
            lines.append(f"⚠️ {sym}: {err}")
        await self.reply(update, "\n".join(lines))

    async def positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        st = await self.app.trader.status()
        if not st["positions"]:
            await self.reply(update, "No open positions.")
            return
        await self.reply(update, "\n".join(
            f"{p['symbol']}: {p['qty']:.6g} @ {p['entry']:,.2f}, stop {p['stop']:,.2f}, "
            f"now {p['price'] or 0:,.2f}, P&L {p['unrealized']:+,.2f}\n  why: {p['reason']}"
            for p in st["positions"]))

    async def trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        fills = self.app.store.fills(15)
        if not fills:
            await self.reply(update, "No trades yet.")
            return
        await self.reply(update, "\n".join(
            f"{_fmt_ts(f['ts'])} {f['side'].upper()} {f['qty']:.6g} {f['symbol']} @ {f['price']:,.2f}"
            + (f" P&L {f['pnl']:+,.2f}" if f["pnl"] is not None else "") for f in fills), pre=True)

    async def signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        symbol, sig = await self.app.signal(args[0] if args else None, args[1] if len(args) > 1 else None)
        text = f"{symbol}: {sig.action.upper()} at {sig.price:,.2f}\nWhy: {sig.reason}"
        if sig.stop:
            text += f"\nStop-loss: {sig.stop:,.2f}"
        text += "\n\nA signal is a rule firing, not a prediction. See /backtest for how the rule has done."
        await self.reply(update, text)

    async def backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        bars = int(args[2]) if len(args) > 2 and args[2].isdigit() else 2000
        await self.reply(update, "⏳ Running backtest…")
        result = await self.app.backtest(args[0] if args else None, args[1] if len(args) > 1 else None, bars)
        text = format_summary(result) + f"\nCandles: {result['candles']} ({result['data_source']} data)"
        await self.reply(update, text, pre=True)

    async def strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, "\n\n".join(f"{s.name} — {s.title}\n{s.description}" for s in STRATEGIES.values()))

    async def pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.app.trader.set_paused(True)
        await self.reply(update, "⏸ Paused: no new trades. Open positions keep their stops and exits.")

    async def resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.app.trader.set_paused(False)
        await self.reply(update, "▶️ Resumed: new trades allowed.")

    async def close(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await self.reply(update, "Usage: /close BTC/USD")
            return
        symbol = self.app.normalize_symbol(context.args[0])
        if not await self.app.trader.close_position(symbol):
            await self.reply(update, f"No open position in {symbol}.")

    async def closeall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        n = await self.app.trader.close_all()
        await self.reply(update, f"Closed {n} position(s).")

    async def resetrisk(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.app.trader.reset_kill_switch()
        await self.reply(update, "Kill switch cleared; peak equity reset to current equity.")

    async def howitworks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, HOW_IT_WORKS)

    async def martingale(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, martingale_lesson())

    async def redflags(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, SCAM_RED_FLAGS)

    # ---------- lifecycle (runs inside an existing asyncio loop) ----------
    async def start_polling(self) -> None:
        await self.application.initialize()
        try:
            await self.application.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
        except Exception:
            log.warning("could not set the command menu")
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        if self.application.updater and self.application.updater.running:
            await self.application.updater.stop()
        if self.application.running:
            await self.application.stop()
        await self.application.shutdown()
