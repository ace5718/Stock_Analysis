from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import crypto
from backend import database as db
from backend import fugle
from backend import services
from backend import trade
from backend.backtest import run_backtest
from backend.markets import MARKET_CRYPTO, MARKET_TW, normalize_market, normalize_symbol
from backend.models import (
    BacktestRequest,
    ConfirmOrderRequest,
    SettingsPatch,
    TradeRequest,
    WatchlistCreate,
)

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def _parse_market(market: str = "tw") -> str:
    try:
        return normalize_market(market)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@asynccontextmanager
async def lifespan(app: FastAPI):
    fugle.clear_kline_cache()
    crypto.clear_kline_cache()
    db.init_db()
    _sync_legacy_cash()
    await services.refresh_watchlist_stream()
    yield


def _sync_legacy_cash() -> None:
    legacy = db.get_setting("virtual_cash")
    if legacy is not None and db.get_setting("virtual_cash_tw") is None:
        db.set_setting("virtual_cash_tw", legacy)


app = FastAPI(title="AI 模擬交易（台股／虛擬貨幣）", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return db.get_all_settings()


@app.patch("/api/settings")
def patch_settings(body: SettingsPatch) -> dict[str, Any]:
    return db.patch_settings(body.model_dump(exclude_none=True))


@app.get("/api/watchlist")
def get_watchlist(market: str = Query("tw")) -> list[dict]:
    return db.list_watchlist(_parse_market(market))


@app.post("/api/watchlist")
async def post_watchlist(body: WatchlistCreate) -> dict:
    m = _parse_market(body.market)
    try:
        item = db.add_watchlist(body.symbol, body.name, m)
        await services.refresh_watchlist_stream(m)
        return item
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/watchlist/{symbol}")
async def delete_watchlist(
    symbol: str, market: str = Query("tw")
) -> dict[str, bool]:
    m = _parse_market(market)
    db.remove_watchlist(symbol, m)
    await services.refresh_watchlist_stream(m)
    return {"ok": True}


@app.get("/api/quotes")
def get_quotes(market: str = Query("tw")) -> dict[str, dict]:
    m = _parse_market(market)
    if m == MARKET_CRYPTO:
        return crypto.get_all_quotes()
    return fugle.get_all_quotes()


@app.get("/api/klines/{symbol}")
def get_klines(
    symbol: str, days: int = 120, market: str = Query("tw")
) -> dict[str, Any]:
    m = _parse_market(market)
    sym = normalize_symbol(symbol, m)
    if m == MARKET_CRYPTO:
        df = crypto.fetch_klines(sym, days)
    else:
        df = fugle.fetch_klines(sym, days)
    if df.empty:
        return {"market": m, "symbol": sym, "candles": []}
    candles = []
    for row in df.to_dict(orient="records"):
        vol = row.get("volume") or 0
        candles.append(
            {
                "time": str(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(vol) if m == MARKET_CRYPTO else int(vol),
            }
        )
    return {"market": m, "symbol": sym, "candles": candles}


@app.post("/api/analyze/{symbol}")
async def analyze_symbol(symbol: str, market: str = Query("tw")) -> dict:
    m = _parse_market(market)
    sym = normalize_symbol(symbol, m)
    await services._maybe_analyze(sym, force=True, market=m)
    cached = db.get_analysis_cache(sym, m)
    return cached or {"error": "無分析結果"}


@app.get("/api/analysis/{symbol}")
def get_analysis(symbol: str, market: str = Query("tw")) -> dict:
    m = _parse_market(market)
    sym = normalize_symbol(symbol, m)
    cached = db.get_analysis_cache(sym, m)
    if not cached:
        return {"market": m, "symbol": sym, "result": None, "analyzed_at": None, "fingerprint": None}
    return cached


@app.get("/api/portfolio")
def get_portfolio(market: str = Query("tw")) -> dict:
    m = _parse_market(market)
    if m == MARKET_CRYPTO:
        quotes = {s: q["price"] for s, q in crypto.get_all_quotes().items()}
    else:
        quotes = {s: q["price"] for s, q in fugle.get_all_quotes().items()}
    return trade.portfolio_summary(quotes, m)


@app.get("/api/trades/max-qty")
def get_max_qty(symbol: str, market: str = Query("tw")) -> dict:
    m = _parse_market(market)
    sym = normalize_symbol(symbol, m)
    if m == MARKET_CRYPTO:
        quotes = crypto.get_all_quotes()
    else:
        quotes = fugle.get_all_quotes()
    price = float(quotes.get(sym, {}).get("price") or 0)
    if not price:
        raise HTTPException(400, "無報價")
    cash = trade.available_cash(m)
    max_q = trade.max_affordable_qty(price, m)
    return {
        "market": m,
        "symbol": sym,
        "price": price,
        "cash": cash,
        "max_qty": max_q,
    }


@app.post("/api/trades")
def post_trade(body: TradeRequest) -> dict:
    m = _parse_market(body.market)
    sym = normalize_symbol(body.symbol, m)
    if m == MARKET_CRYPTO:
        quotes = crypto.get_all_quotes()
    else:
        quotes = fugle.get_all_quotes()
    q = quotes.get(sym, {})
    price = q.get("price") or 0
    if not price:
        raise HTTPException(400, "無報價")
    try:
        return trade.execute_trade(sym, body.side, body.qty, price, m)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/trades")
def get_trades(market: str = Query("tw"), limit: int = 200) -> list[dict]:
    return db.list_trades(limit=limit, market=_parse_market(market))


@app.get("/api/pending-orders")
def get_pending(market: str = Query("tw")) -> list[dict]:
    return db.list_pending_orders(_parse_market(market))


@app.post("/api/pending-orders/{order_id}/confirm")
def confirm_pending(order_id: int, market: str = Query("tw")) -> dict:
    m = _parse_market(market)
    orders = db.list_pending_orders(m)
    order = next((o for o in orders if o["id"] == order_id), None)
    if not order:
        raise HTTPException(404, "訂單不存在")
    try:
        result = trade.execute_trade(
            order["symbol"],
            order["side"],
            order["qty"],
            order["price"],
            order.get("market", m),
        )
        db.delete_pending_order(order_id)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/pending-orders/{order_id}")
def reject_pending(order_id: int) -> dict[str, bool]:
    db.delete_pending_order(order_id)
    return {"ok": True}


@app.get("/api/performance")
def performance(period: str = "all", market: str = Query("tw")) -> dict:
    return trade.performance_stats(period, _parse_market(market))


@app.post("/api/backtest")
def backtest(body: BacktestRequest) -> dict:
    return run_backtest(body.symbol, body.start_date, body.end_date, body.use_ai)


@app.websocket("/ws/quotes")
async def ws_quotes(websocket: WebSocket, market: str = Query("tw")):
    m = _parse_market(market)
    await websocket.accept()
    services.register_ws(websocket, m)
    try:
        if m == MARKET_CRYPTO:
            quotes = crypto.get_all_quotes()
        else:
            quotes = fugle.get_all_quotes()
        for q in quotes.values():
            await websocket.send_json({"type": "quote", "data": q})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        services.unregister_ws(websocket, m)


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")

    @app.get("/performance")
    def performance_page():
        return FileResponse(FRONTEND / "performance.html")

    @app.get("/backtest")
    def backtest_page():
        return FileResponse(FRONTEND / "backtest.html")

    @app.get("/settings")
    def settings_page():
        return FileResponse(FRONTEND / "settings.html")
