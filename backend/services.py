import asyncio
import json
from typing import Any, Optional

from backend import crypto
from backend import database as db
from backend import fugle
from backend import notify
from backend import trade
from backend.ai.base import get_engine
from backend.condition import evaluate_triggers, has_directional_trigger
from backend.indicators import compute_indicators, indicator_fingerprint, latest_indicator_row
from backend.markets import MARKET_CRYPTO, MARKET_TW, normalize_market, normalize_symbol
from backend.models import AnalysisResult

_ws_clients: dict[str, set] = {"tw": set(), "crypto": set()}
_symbol_state: dict[str, dict] = {}
_stream_tasks: dict[str, asyncio.Task | None] = {"tw": None, "crypto": None}


def _state_key(market: str, symbol: str) -> str:
    return f"{normalize_market(market)}:{normalize_symbol(symbol, market)}"


def _quotes_for_market(market: str) -> dict[str, dict]:
    market = normalize_market(market)
    if market == MARKET_CRYPTO:
        return crypto.get_all_quotes()
    return fugle.get_all_quotes()


def _fetch_klines(symbol: str, days: int, market: str):
    market = normalize_market(market)
    sym = normalize_symbol(symbol, market)
    if market == MARKET_CRYPTO:
        return crypto.fetch_klines(sym, days)
    return fugle.fetch_klines(sym, days)


async def broadcast(message: dict, market: Optional[str] = None) -> None:
    msg_market = message.get("data", {}).get("market") or message.get("market")
    targets: list[str]
    if market:
        targets = [normalize_market(market)]
    elif msg_market in (MARKET_TW, MARKET_CRYPTO):
        targets = [msg_market]
    else:
        targets = [MARKET_TW, MARKET_CRYPTO]

    text = json.dumps(message, ensure_ascii=False)
    for m in targets:
        dead = []
        for ws in list(_ws_clients.get(m, set())):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_clients[m].discard(ws)


async def refresh_watchlist_stream(market: Optional[str] = None) -> None:
    markets = [normalize_market(market)] if market else [MARKET_TW, MARKET_CRYPTO]
    for m in markets:
        await _refresh_market_stream(m)


async def _refresh_market_stream(market: str) -> None:
    market = normalize_market(market)
    symbols = [w["symbol"] for w in db.list_watchlist(market)]
    task = _stream_tasks.get(market)
    if task:
        task.cancel()

    async def on_quote(q: dict) -> None:
        sym = q["symbol"]
        key = _state_key(market, sym)
        _symbol_state.setdefault(key, {})["quote"] = q
        await broadcast({"type": "quote", "data": q}, market)
        await _maybe_analyze(sym, market=market)

    if market == MARKET_CRYPTO:
        _stream_tasks[market] = asyncio.create_task(
            crypto.start_quote_stream(symbols, on_quote)
        )
    else:
        _stream_tasks[market] = asyncio.create_task(
            fugle.start_quote_stream(symbols, on_quote)
        )


async def _maybe_analyze(
    symbol: str, force: bool = False, market: str = MARKET_TW
) -> None:
    market = normalize_market(market)
    sym = normalize_symbol(symbol, market)
    key = _state_key(market, sym)
    state = _symbol_state.get(key, {})
    df = _fetch_klines(sym, 60, market)
    if df.empty:
        return
    df = compute_indicators(df)
    ind = latest_indicator_row(df)
    state["indicators"] = ind
    fired = evaluate_triggers(ind)
    state["triggers"] = fired
    await broadcast(
        {
            "type": "indicators",
            "market": market,
            "symbol": sym,
            "data": ind,
            "triggers": fired,
        },
        market,
    )

    if not force and not fired:
        return
    if not force and not has_directional_trigger(fired) and not any(
        t["type"] == "volume_spike" for t in fired
    ):
        if not fired:
            return

    fp = indicator_fingerprint(ind)
    cached = db.get_analysis_cache(sym, market)
    if not force and cached and cached["fingerprint"] == fp:
        await broadcast(
            {
                "type": "analysis",
                "market": market,
                "symbol": sym,
                "data": cached["result"],
                "cached": True,
                "analyzed_at": cached["analyzed_at"],
            },
            market,
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
    db.set_analysis_cache(sym, fp, payload, market)
    await broadcast(
        {
            "type": "analysis",
            "market": market,
            "symbol": sym,
            "data": payload,
            "cached": False,
            "analyzed_at": db.get_analysis_cache(sym, market)["analyzed_at"],
        },
        market,
    )

    settings = db.get_all_settings()
    if settings.get("notify_enabled"):
        notify.send_signal_email(sym, payload, ind)

    quotes = _build_quotes_map(market)
    quotes[sym] = ind.get("close") or quotes.get(sym, 0)
    trade.check_risk_and_maybe_halt(quotes, market)

    await _handle_auto_trade(sym, payload, ind, quotes, market)


def _build_quotes_map(market: str) -> dict[str, float]:
    market = normalize_market(market)
    out: dict[str, float] = {}
    prefix = f"{market}:"
    for key, val in _symbol_state.items():
        if not key.startswith(prefix):
            continue
        q = val.get("quote", {})
        if q.get("price"):
            out[q["symbol"]] = q["price"]
    for sym, q in _quotes_for_market(market).items():
        if q.get("price"):
            out[sym] = q["price"]
    return out


async def _handle_auto_trade(
    symbol: str,
    analysis: dict,
    ind: dict,
    quotes: dict[str, float],
    market: str = MARKET_TW,
) -> None:
    market = normalize_market(market)
    settings = db.get_all_settings()
    halt_key = f"trading_halted_{market}"
    if settings.get(halt_key) or (market == MARKET_TW and settings.get("trading_halted")):
        return
    direction = analysis.get("direction")
    price = quotes.get(symbol) or ind.get("close") or 0
    if not price:
        return

    mode = settings.get("order_mode", "notify_confirm")
    if direction == "hold":
        return

    side = "buy" if direction == "buy" else "sell"
    qty = trade.calc_buy_qty(price, settings, market) if side == "buy" else 0
    if side == "sell":
        pos = db.get_position(symbol, market)
        qty = pos["qty"] if pos else 0

    min_qty = 0.000001 if market == MARKET_CRYPTO else 1000
    if qty < min_qty:
        return

    if mode == "notify_confirm":
        db.add_pending_order(symbol, side, qty, price, analysis.get("reason", ""), market)
        await broadcast(
            {
                "type": "pending_order",
                "market": market,
                "symbol": symbol,
                "side": side,
                "qty": qty,
            },
            market,
        )
        return

    try:
        trade.execute_trade(symbol, side, qty, price, market)
        unit = "" if market == MARKET_CRYPTO else " 股"
        await broadcast(
            {
                "type": "trade",
                "market": market,
                "symbol": symbol,
                "side": side,
                "qty": qty,
            },
            market,
        )
        notify.send_signal_email(
            symbol,
            {
                **analysis,
                "reason": f"已自動{side} {qty}{unit}。{analysis.get('reason', '')}",
            },
            ind,
            signal_type="auto_trade",
        )
    except ValueError as e:
        await broadcast({"type": "error", "message": str(e)}, market)


def register_ws(ws, market: str = MARKET_TW) -> None:
    market = normalize_market(market)
    _ws_clients.setdefault(market, set()).add(ws)


def unregister_ws(ws, market: str = MARKET_TW) -> None:
    market = normalize_market(market)
    _ws_clients.get(market, set()).discard(ws)
