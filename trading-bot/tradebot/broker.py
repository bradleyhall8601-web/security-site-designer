"""Brokers: PaperBroker simulates fills on real prices; LiveBroker sends real orders via ccxt."""

from __future__ import annotations

from dataclasses import dataclass

from .storage import Store


@dataclass
class Fill:
    qty: float
    price: float  # average fill price
    fee: float  # in quote currency
    order_id: str | None = None


class Broker:
    mode = "base"

    async def cash(self, symbol: str | None = None) -> float:
        raise NotImplementedError

    async def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        raise NotImplementedError

    async def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class PaperBroker(Broker):
    """Simulated account. Cash lives in the SQLite store so it survives restarts."""

    mode = "paper"

    def __init__(self, store: Store, starting_cash: float, fee_rate: float, slippage: float):
        self.store, self.fee_rate, self.slippage = store, fee_rate, slippage
        if store.get("paper_cash") is None:
            store.set("paper_cash", starting_cash)
            store.set("paper_starting_cash", starting_cash)

    async def cash(self, symbol: str | None = None) -> float:
        return float(self.store.get("paper_cash", 0.0))

    async def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        price = price_hint * (1 + self.slippage)
        cost = price * qty
        fee = cost * self.fee_rate
        cash = await self.cash()
        if cost + fee > cash + 1e-9:
            raise RuntimeError(f"Not enough paper cash: need {cost + fee:,.2f}, have {cash:,.2f}")
        self.store.set("paper_cash", cash - cost - fee)
        return Fill(qty, price, fee)

    async def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        price = price_hint * (1 - self.slippage)
        proceeds = price * qty
        fee = proceeds * self.fee_rate
        self.store.set("paper_cash", await self.cash() + proceeds - fee)
        return Fill(qty, price, fee)

    def reset(self, starting_cash: float) -> None:
        self.store.set("paper_cash", starting_cash)
        self.store.set("paper_starting_cash", starting_cash)


class LiveBroker(Broker):
    """Real market orders through ccxt. Use SANDBOX=true (exchange testnet) first.

    The bot only trades the positions it opened itself and tracks them in SQLite;
    it does not touch other holdings on the account.
    """

    mode = "live"

    def __init__(self, exchange_id: str, api_key: str, api_secret: str, password: str = "",
                 sandbox: bool = True, exchange=None):
        if exchange is None:
            import ccxt.async_support as ccxt

            params = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
            if password:
                params["password"] = password
            exchange = getattr(ccxt, exchange_id)(params)
            if sandbox:
                exchange.set_sandbox_mode(True)  # raises if this exchange has no testnet
        self.exchange = exchange
        self._markets_loaded = False

    async def _markets(self):
        if not self._markets_loaded:
            await self.exchange.load_markets()
            self._markets_loaded = True
        return self.exchange.markets

    async def quote_currency(self, symbol: str) -> str:
        markets = await self._markets()
        return markets[symbol]["quote"]

    async def cash(self, symbol: str | None = None) -> float:
        balance = await self.exchange.fetch_balance()
        quote = await self.quote_currency(symbol) if symbol else "USD"
        free = balance.get("free", {}) or {}
        return float(free.get(quote) or 0.0)

    async def _amount(self, symbol: str, qty: float) -> float:
        await self._markets()
        amount = float(self.exchange.amount_to_precision(symbol, qty))
        limits = self.exchange.markets[symbol].get("limits", {}).get("amount", {}) or {}
        if limits.get("min") and amount < limits["min"]:
            raise RuntimeError(f"{symbol}: size {amount} is below the exchange minimum {limits['min']}")
        return amount

    async def _fill(self, order: dict, symbol: str, fallback_price: float) -> Fill:
        if order.get("id") and (order.get("average") is None or order.get("filled") is None):
            try:
                order = await self.exchange.fetch_order(order["id"], symbol)
            except Exception:  # some exchanges cannot fetch closed orders; keep what we have
                pass
        filled = float(order.get("filled") or order.get("amount") or 0.0)
        price = float(order.get("average") or order.get("price") or fallback_price)
        fee = 0.0
        quote = await self.quote_currency(symbol)
        for f in order.get("fees") or ([order["fee"]] if order.get("fee") else []):
            if f and f.get("cost"):
                cost = float(f["cost"])
                fee += cost if f.get("currency") == quote else cost * price
        return Fill(filled, price, fee, order.get("id"))

    async def buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        order = await self.exchange.create_order(symbol, "market", "buy", await self._amount(symbol, qty))
        return await self._fill(order, symbol, price_hint)

    async def sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        order = await self.exchange.create_order(symbol, "market", "sell", await self._amount(symbol, qty))
        return await self._fill(order, symbol, price_hint)

    async def close(self) -> None:
        await self.exchange.close()
