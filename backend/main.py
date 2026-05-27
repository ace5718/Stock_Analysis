from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import database as db
from backend import fugle
from backend import services
from backend import trade
from backend.backtest import run_backtest
from backend.models import (
    BacktestRequest,
    ConfirmOrderRequest,
    SettingsPatch,
    TradeRequest,
    WatchlistCreate,
)

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    await services.refresh_watchlist_stream()
    yield


app = FastAPI(title="台股 AI 模擬交易", lifespan=lifespan)


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
def get_watchlist() -> list[dict]:
    return db.list_watchlist()


@app.post("/api/watchlist")
async def post_watchlist(body: WatchlistCreate) -> dict:
    try:
        item = db.add_watchlist(body.symbol, body.name)
        await services.refresh_watchlist_stream()
        return item
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/watchlist/{symbol}")
async def delete_watchlist(symbol: str) -> dict[str, bool]:
    db.remove_watchlist(symbol)
    await services.refresh_watchlist_stream()
    return {"ok": True}


@app.get("/api/quotes")
def get_quotes() -> dict[str, dict]:
    return fugle.get_all_quotes()


@app.get("/api/klines/{symbol}")
def get_klines(symbol: str, days: int = 120) -> dict[str, Any]:
    df = fugle.fetch_klines(symbol, days)
    if df.empty:
        return {"symbol": symbol, "candles": []}
    candles = df.to_dict(orient="records")
    for c in candles:
        c["time"] = str(c["time"])
    return {"symbol": symbol.upper(), "candles": candles}


@app.post("/api/analyze/{symbol}")
async def analyze_symbol(symbol: str) -> dict:
    await services._maybe_analyze(symbol.upper(), force=True)
    cached = db.get_analysis_cache(symbol.upper())
    return cached or {"error": "無分析結果"}


@app.get("/api/analysis/{symbol}")
def get_analysis(symbol: str) -> dict:
    cached = db.get_analysis_cache(symbol.upper())
    if not cached:
        raise HTTPException(404, "尚無分析")
    return cached


@app.get("/api/portfolio")
def get_portfolio() -> dict:
    quotes = {s: q["price"] for s, q in fugle.get_all_quotes().items()}
    return trade.portfolio_summary(quotes)


@app.post("/api/trades")
def post_trade(body: TradeRequest) -> dict:
    quotes = fugle.get_all_quotes()
    q = quotes.get(body.symbol.upper(), {})
    price = q.get("price") or 0
    if not price:
        raise HTTPException(400, "無報價")
    try:
        return trade.execute_trade(body.symbol, body.side, body.qty, price)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/trades")
def get_trades() -> list[dict]:
    return db.list_trades()


@app.get("/api/pending-orders")
def get_pending() -> list[dict]:
    return db.list_pending_orders()


@app.post("/api/pending-orders/{order_id}/confirm")
def confirm_pending(order_id: int) -> dict:
    orders = db.list_pending_orders()
    order = next((o for o in orders if o["id"] == order_id), None)
    if not order:
        raise HTTPException(404, "訂單不存在")
    try:
        result = trade.execute_trade(
            order["symbol"], order["side"], order["qty"], order["price"]
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
def performance(period: str = "all") -> dict:
    return trade.performance_stats(period)


@app.post("/api/backtest")
def backtest(body: BacktestRequest) -> dict:
    return run_backtest(body.symbol, body.start_date, body.end_date, body.use_ai)


@app.websocket("/ws/quotes")
async def ws_quotes(websocket: WebSocket):
    await websocket.accept()
    services.register_ws(websocket)
    try:
        for sym, q in fugle.get_all_quotes().items():
            await websocket.send_json({"type": "quote", "data": q})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        services.unregister_ws(websocket)


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
