"""Web dashboard and JSON API (FastAPI)."""

from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from .app import TradeBotApp
from .learn import HOW_IT_WORKS, SCAM_RED_FLAGS, martingale_lesson, simulate_martingale
from .strategies import STRATEGIES

STATIC = Path(__file__).parent / "static"


def create_web(app: TradeBotApp) -> FastAPI:
    api = FastAPI(title="TradeBot", docs_url=None, redoc_url=None)
    token = app.settings.web_token

    def check_token(request: Request) -> None:
        if not token:
            return
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip() \
            or request.query_params.get("token", "")
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(401, "Missing or wrong token")

    def check_write(request: Request) -> None:
        check_token(request)
        # a custom header forces a CORS preflight, so other websites cannot trigger trades
        if request.headers.get("x-tradebot") != "1":
            raise HTTPException(403, "Missing X-Tradebot header")

    @api.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @api.get("/api/status", dependencies=[Depends(check_token)])
    async def status():
        return await app.trader.status()

    @api.get("/api/equity", dependencies=[Depends(check_token)])
    async def equity(limit: int = Query(2000, ge=1, le=20000)):
        return app.store.equity_history(limit)

    @api.get("/api/fills", dependencies=[Depends(check_token)])
    async def fills(limit: int = Query(50, ge=1, le=1000)):
        return app.store.fills(limit)

    @api.get("/api/events", dependencies=[Depends(check_token)])
    async def events(limit: int = Query(50, ge=1, le=1000)):
        return app.store.events(limit)

    @api.get("/api/strategies")
    async def strategies():
        return [{"name": s.name, "title": s.title, "description": s.description} for s in STRATEGIES.values()]

    @api.get("/api/backtest", dependencies=[Depends(check_token)])
    async def backtest(symbol: str | None = None, strategy: str | None = None,
                       bars: int = Query(2000, ge=100, le=20000)):
        try:
            return await app.backtest(symbol, strategy, bars)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @api.get("/api/signal", dependencies=[Depends(check_token)])
    async def signal(symbol: str | None = None, strategy: str | None = None):
        try:
            sym, sig = await app.signal(symbol, strategy)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"symbol": sym, "action": sig.action, "reason": sig.reason, "price": sig.price, "stop": sig.stop}

    @api.get("/api/learn")
    async def learn():
        r = simulate_martingale()
        return {"how_it_works": HOW_IT_WORKS, "red_flags": SCAM_RED_FLAGS, "martingale": martingale_lesson(),
                "martingale_bust_rate": r.bust_rate}

    @api.post("/api/pause", dependencies=[Depends(check_write)])
    async def pause():
        app.trader.set_paused(True)
        return {"paused": True}

    @api.post("/api/resume", dependencies=[Depends(check_write)])
    async def resume():
        app.trader.set_paused(False)
        return {"paused": False}

    @api.post("/api/close", dependencies=[Depends(check_write)])
    async def close(symbol: str):
        ok = await app.trader.close_position(app.normalize_symbol(symbol))
        if not ok:
            raise HTTPException(404, "No open position")
        return {"closed": symbol}

    @api.post("/api/closeall", dependencies=[Depends(check_write)])
    async def closeall():
        return {"closed": await app.trader.close_all()}

    @api.post("/api/step", dependencies=[Depends(check_write)])
    async def step():
        await app.trader.step()
        return await app.trader.status()

    @api.exception_handler(Exception)
    async def errors(request: Request, exc: Exception):
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)

    return api
