import asyncio
import json
from typing import Any, Optional

from backend import database as db
from backend import fugle
from backend import notify
from backend import trade
from backend.ai.base import get_engine
from backend.condition import evaluate_triggers, has_directional_trigger
from backend.indicators import compute_indicators, indicator_fingerprint, latest_indicator_row
from backend.models import AnalysisResult

_ws_clients: set = set()
_symbol_state: dict[str, dict] = {}
_analysis_tasks: dict[str, asyncio.Task] = {}


async def broadcast(message: dict) -> None:
    dead = []
    text = json.dumps(message, ensure_ascii=False)
    for ws in list(_ws_clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


async def refresh_watchlist_stream() -> None:
    symbols = [w["symbol"] for w in db.list_watchlist()]

    async def on_quote(q: dict) -> None:
        sym = q["symbol"]
        _symbol_state.setdefault(sym, {})["quote"] = q
        await broadcast({"type": "quote", "data": q})
        await _maybe_analyze(sym)

    await fugle.start_quote_stream(symbols, on_quote)


async def _maybe_analyze(symbol: str, force: bool = False) -> None:
    sym = symbol.upper()
    state = _symbol_state.get(sym, {})
    df = fugle.fetch_klines(sym, 60)
    if df.empty:
        return
    df = compute_indicators(df)
    ind = latest_indicator_row(df)
    state["indicators"] = ind
    fired = evaluate_triggers(ind)
    state["triggers"] = fired
    await broadcast({"type": "indicators", "symbol": sym, "data": ind, "triggers": fired})

    if not force and not fired:
        return
    if not force and not has_directional_trigger(fired) and not any(
        t["type"] == "volume_spike" for t in fired
    ):
        if not fired:
            return

    fp = indicator_fingerprint(ind)
    cached = db.get_analysis_cache(sym)
    if not force and cached and cached["fingerprint"] == fp:
        await broadcast(
            {
                "type": "analysis",
                "symbol": sym,
                "data": cached["result"],
                "cached": True,
                "analyzed_at": cached["analyzed_at"],
            }
        )
        return

    engine = get_engine()
    try:
        result: AnalysisResult = engine.analyze(sym, ind, fired)
    except Exception as e:
        result = AnalysisResult(
            direction="hold",
            confidence="low",
            reason=f"分析失敗：{e}",
        )
    payload = result.model_dump()
    db.set_analysis_cache(sym, fp, payload)
    await broadcast(
        {
            "type": "analysis",
            "symbol": sym,
            "data": payload,
            "cached": False,
            "analyzed_at": db.get_analysis_cache(sym)["analyzed_at"],
        }
    )

    settings = db.get_all_settings()
    if settings.get("notify_enabled"):
        notify.send_signal_email(sym, payload, ind)

    quotes = {s: q.get("price", 0) for s, q in ((k, v.get("quote", {})) for k, v in _symbol_state.items())}
    quotes[sym] = ind.get("close") or quotes.get(sym, 0)
    trade.check_risk_and_maybe_halt(quotes)

    await _handle_auto_trade(sym, payload, ind, quotes)


async def _handle_auto_trade(
    symbol: str, analysis: dict, ind: dict, quotes: dict[str, float]
) -> None:
    settings = db.get_all_settings()
    if settings.get("trading_halted"):
        return
    direction = analysis.get("direction")
    price = quotes.get(symbol) or ind.get("close") or 0
    if not price:
        return

    mode = settings.get("order_mode", "notify_confirm")
    if direction == "hold":
        return

    side = "buy" if direction == "buy" else "sell"
    qty = trade.calc_buy_qty(price, settings) if side == "buy" else 0
    if side == "sell":
        pos = db.get_position(symbol)
        qty = pos["qty"] if pos else 0

    if qty < 1000:
        return

    if mode == "notify_confirm":
        db.add_pending_order(symbol, side, qty, price, analysis.get("reason", ""))
        await broadcast({"type": "pending_order", "symbol": symbol, "side": side, "qty": qty})
        return

    try:
        trade.execute_trade(symbol, side, qty, price)
        await broadcast({"type": "trade", "symbol": symbol, "side": side, "qty": qty})
        notify.send_signal_email(
            symbol,
            {**analysis, "reason": f"已自動{side} {qty} 股。{analysis.get('reason', '')}"},
            ind,
            signal_type="auto_trade",
        )
    except ValueError as e:
        await broadcast({"type": "error", "message": str(e)})


def register_ws(ws) -> None:
    _ws_clients.add(ws)


def unregister_ws(ws) -> None:
    _ws_clients.discard(ws)
