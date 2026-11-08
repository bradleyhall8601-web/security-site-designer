# TradeBot

An all-in-one trading bot that tells you the truth. One command runs everything:

- **Trader**: checks the markets on a timer, acts on strategy signals, and manages stop-losses.
- **Paper trading** (the default): real exchange prices, simulated fills with fees and slippage, and a full journal.
- **Live trading** (opt-in): real market orders on any of the 100+ exchanges [ccxt](https://github.com/ccxt/ccxt) supports, with a testnet first.
- **Telegram bot**: alerts for every trade, plus status, signals, backtests, pause and close-all from your phone.
- **Web dashboard**: equity chart, positions, signals, trades, a backtester and an activity log.
- **Backtester**: fees, slippage, gap-aware stops, no look-ahead, and every result compared with buy-and-hold.
- **Lessons**: why martingale ("Smart Scaling") loses, with a simulation, and how to spot fake "AI trading bots".

> No strategy here is promised to make money, and on many markets they will not. The bot is built so you can find
> that out cheaply, with backtests and paper trading, before risking anything. Only trade money you can afford to lose.

## Quick start

```bash
cd trading-bot
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env                               # edit the markets, strategy and risk settings

tradebot check                                     # can it reach the exchange?
tradebot backtest --strategy all --bars 3000       # how have the strategies done on your market?
tradebot run                                       # trader + Telegram + dashboard at http://127.0.0.1:8000
```

No internet, or just exploring? Add `--synthetic` to any command to use offline practice data.
Synthetic data is a random walk, so its results say nothing about real markets.

## Commands

| Command | What it does |
|---|---|
| `tradebot run` | Starts the trader, Telegram bot (if `TELEGRAM_TOKEN` is set) and dashboard in one process. `--no-telegram`, `--no-web`, `--poll 30`, `--port 9000` |
| `tradebot backtest` | `--symbol ETH/USD --strategy trend\|meanrev\|breakout\|all --bars 5000`, `--csv file.csv`, `--json` |
| `tradebot signal` | The current signal for each market, with the reason and the stop |
| `tradebot check` | Validates settings and checks prices and account access |
| `tradebot martingale` | Simulates "Smart Scaling" and shows why it loses |

## Telegram

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token into `TELEGRAM_TOKEN` in `.env`.
2. Run `tradebot run`, then send `/start` to your bot. The first person to do this becomes its only user.
   To allow specific people instead, set `TELEGRAM_ALLOWED_USERS` to their numeric IDs.
3. Commands: `/status /positions /trades /signal BTC /backtest BTC trend 3000 /strategies /pause /resume /close BTC/USD /closeall /resetrisk /howitworks /martingale /redflags`

## How it decides

| Strategy | Buys when | Sells when | Stop |
|---|---|---|---|
| `trend` | 20 EMA crosses above 50 EMA and price is above the 200 EMA | 20 EMA below 50 EMA | 2.5 × ATR |
| `meanrev` | RSI(14) < 30 and price is above the 200 SMA | RSI > 55 | 3 × ATR |
| `breakout` | close above the previous 20-candle high | close below the previous 10-candle low | 2 × ATR |

- It only buys, then sells what it bought. There is no shorting and no leverage.
- Signals use closed candles only. The bot does not act on a candle that is still forming.
- **Position size** = equity × `RISK_PER_TRADE` ÷ (stop distance + round-trip fees), capped by `MAX_POSITION_FRACTION`
  and your available cash. At the default 1%, a trade that hits its stop loses about 1% of equity.
  Size never goes up after a loss.
- **Safety stops**: once the day's loss reaches `DAILY_LOSS_LIMIT`, no new trades until midnight UTC. Once equity is
  `MAX_DRAWDOWN` below its peak, a kill switch blocks new trades until you send `/resetrisk`. Open positions
  keep their stops and exits either way.
- Stops are checked against the live price every `POLL_SECONDS`. They are not resting orders on the exchange, so a
  fast move between checks can fill below the stop.

## Going live (carefully)

1. Backtest on your market and timeframe. If a strategy does not beat buy-and-hold after fees, do not run it live.
2. Paper trade it for weeks.
3. Create an exchange API key with **trade permission only and withdrawals turned off**. Restrict it to your IP if
   the exchange allows that.
4. Use the exchange testnet first. Set these in `.env`:
   ```
   MODE=live
   SANDBOX=true
   API_KEY=…
   API_SECRET=…
   LIVE_CONFIRM=I accept the risk of losing money
   ```
5. Switch to `SANDBOX=false` only when you mean it. Set `FEE_RATE` to your real taker fee.

The bot trades only the positions it opened and tracks them in its SQLite journal. It does not touch the rest of
your account.

## Docker

```bash
docker build -t tradebot trading-bot
docker run -d --env-file trading-bot/.env -e WEB_TOKEN=change-me -p 8000:8000 -v tradebot-data:/data tradebot
```

When the dashboard listens on a public address, `WEB_TOKEN` is required. Open `http://host:8000/?token=…`.
Buttons that change anything also need an `X-Tradebot` header, so other websites cannot trigger trades.

## Tests

```bash
pip install -e ".[dev]" && python -m pytest
```

The tests cover indicators, causality (no look-ahead), position sizing, the kill switches, backtest accounting
(fees, slippage, stops, gaps), the paper and live brokers against a fake exchange, exchange pagination, the web
API and auth, and Telegram access control.

## Layout

```
tradebot/
  config.py      settings from .env
  data.py        exchange feed (ccxt), synthetic feed, CSV loader
  indicators.py  SMA, EMA, RSI, ATR, Bollinger, channels
  strategies.py  trend, meanrev, breakout
  risk.py        position sizing, daily loss limit, drawdown kill switch
  backtest.py    backtester and metrics
  broker.py      PaperBroker and LiveBroker
  engine.py      the trading loop
  storage.py     SQLite journal
  telegram_bot.py, web.py, static/index.html, learn.py, cli.py
```
