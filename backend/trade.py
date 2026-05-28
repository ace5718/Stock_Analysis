import math
from datetime import date
from typing import Any, Optional

from backend import database as db
from backend.config import FEE_RATE, TAX_RATE
from backend.markets import MARKET_CRYPTO, MARKET_TW, normalize_market, normalize_symbol

CRYPTO_FEE_RATE = 0.001


def _cash_key(market: str) -> str:
    market = normalize_market(market)
    if market == MARKET_CRYPTO:
        return "virtual_cash_crypto"
    return "virtual_cash_tw"


def available_cash(market: str = MARKET_TW) -> float:
    market = normalize_market(market)
    key = _cash_key(market)
    val = db.get_setting(key)
    if val is None and market == MARKET_TW:
        return float(db.get_setting("virtual_cash", 1_000_000))
    return float(val if val is not None else 1_000_000)


def set_cash(amount: float, market: str = MARKET_TW) -> None:
    db.set_setting(_cash_key(market), amount)


def max_affordable_qty(price: float, market: str = MARKET_TW) -> float:
    """依可用虛擬資金估算最多可買數量（含手續費）。"""
    market = normalize_market(market)
    if price <= 0:
        return 0.0
    cash = available_cash(market)
    fee_rate = CRYPTO_FEE_RATE if market == MARKET_CRYPTO else FEE_RATE
    raw = cash / (price * (1 + fee_rate))
    if market == MARKET_CRYPTO:
        return round(max(raw, 0), 6)
    lots = int(raw) // 1000 * 1000
    return float(max(lots, 0))


def calc_buy_qty(
    price: float, settings: Optional[dict] = None, market: str = MARKET_TW
) -> float:
    market = normalize_market(market)
    s = settings or db.get_all_settings()
    cash = available_cash(market)
    pct = min(float(s.get("order_size_value", 20)), 20) / 100.0
    mode = s.get("order_size_mode", "percent")

    if market == MARKET_CRYPTO:
        if mode == "fixed_lots":
            qty = float(s.get("order_size_value", 0.01))
        else:
            budget = cash * pct
            qty = budget / (price * (1 + CRYPTO_FEE_RATE))
        return round(max(qty, 0), 6)

    if mode == "fixed_lots":
        lots = int(s.get("order_size_value", 1))
        qty = lots * 1000
        max_spend = cash * 0.2
        cost = qty * price * (1 + FEE_RATE)
        if cost > max_spend:
            qty = int(max_spend / (price * (1 + FEE_RATE)))
            qty = (qty // 1000) * 1000
    else:
        budget = cash * pct
        qty = int(budget / (price * (1 + FEE_RATE)))
        qty = (qty // 1000) * 1000
    return float(max(qty, 0))


def execute_trade(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    market: str = MARKET_TW,
) -> dict[str, Any]:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    qty = float(qty)

    if market == MARKET_TW:
        qty = int(qty)
        if qty <= 0 or qty % 1000 != 0:
            raise ValueError("股數須為正整數且以張為單位（1000 股）")
        fee_rate = FEE_RATE
        tax_rate = TAX_RATE
    else:
        if qty <= 0:
            raise ValueError("數量須大於 0")
        qty = round(qty, 6)
        fee_rate = CRYPTO_FEE_RATE
        tax_rate = 0.0

    cash = available_cash(market)
    fee = round(price * qty * fee_rate, 4 if market == MARKET_CRYPTO else 2)
    tax = 0.0
    pnl = None

    if side == "buy":
        cost = price * qty + fee
        if cost > cash:
            max_q = max_affordable_qty(price, market)
            unit = "USDT" if market == MARKET_CRYPTO else "NT$"
            if market == MARKET_CRYPTO:
                raise ValueError(
                    f"虛擬資金不足（需約 {cost:,.2f} {unit}，可用 {cash:,.2f} {unit}，"
                    f"最多可買約 {max_q} 顆）"
                )
            raise ValueError(
                f"虛擬資金不足（需約 {cost:,.0f} {unit}，可用 {cash:,.0f} {unit}，"
                f"最多可買 {int(max_q)} 股）"
            )
        pos = db.get_position(symbol, market)
        if pos:
            total_qty = pos["qty"] + qty
            avg = (pos["avg_cost"] * pos["qty"] + price * qty) / total_qty
            db.upsert_position(symbol, total_qty, avg, market)
        else:
            db.upsert_position(symbol, qty, price, market)
        set_cash(cash - cost, market)
    else:
        pos = db.get_position(symbol, market)
        if not pos or pos["qty"] < qty - 1e-9:
            raise ValueError("持倉不足")
        tax = round(price * qty * tax_rate, 2)
        proceeds = price * qty - fee - tax
        pnl = round(proceeds - pos["avg_cost"] * qty, 4 if market == MARKET_CRYPTO else 2)
        new_qty = pos["qty"] - qty
        db.upsert_position(symbol, new_qty, pos["avg_cost"], market)
        set_cash(cash + proceeds, market)

    tid = db.insert_trade(symbol, side, qty, price, fee, tax, pnl, market)
    equity = portfolio_summary({}, market)
    db.record_equity_snapshot(equity["total_equity"])
    return {
        "trade_id": tid,
        "market": market,
        "side": side,
        "qty": qty,
        "price": price,
        "fee": fee,
        "tax": tax,
        "pnl": pnl,
    }


def portfolio_summary(
    quotes: dict[str, float], market: str = MARKET_TW
) -> dict[str, Any]:
    market = normalize_market(market)
    cash = available_cash(market)
    positions = db.list_positions(market)
    holdings_value = 0.0
    unrealized = 0.0
    details = []
    for p in positions:
        price = quotes.get(p["symbol"], p["avg_cost"])
        mv = price * p["qty"]
        cost = p["avg_cost"] * p["qty"]
        u = mv - cost
        holdings_value += mv
        unrealized += u
        details.append(
            {
                "market": market,
                "symbol": p["symbol"],
                "qty": p["qty"],
                "avg_cost": p["avg_cost"],
                "price": price,
                "market_value": mv,
                "unrealized_pnl": round(u, 4 if market == MARKET_CRYPTO else 2),
                "unrealized_pct": round(u / cost * 100, 2) if cost else 0,
            }
        )
    total = cash + holdings_value
    currency = "USDT" if market == MARKET_CRYPTO else "NT$"
    return {
        "market": market,
        "currency": currency,
        "cash": round(cash, 4 if market == MARKET_CRYPTO else 2),
        "holdings_value": round(holdings_value, 4 if market == MARKET_CRYPTO else 2),
        "total_equity": round(total, 4 if market == MARKET_CRYPTO else 2),
        "unrealized_pnl": round(unrealized, 4 if market == MARKET_CRYPTO else 2),
        "positions": details,
    }


def check_risk_and_maybe_halt(
    quotes: dict[str, float], market: str = MARKET_TW
) -> list[dict]:
    market = normalize_market(market)
    s = db.get_all_settings()
    actions = []
    halt_key = f"trading_halted_{market}"
    if s.get(halt_key) or (market == MARKET_TW and s.get("trading_halted")):
        return actions

    summary = portfolio_summary(quotes, market)
    today = date.today().isoformat()
    day_key = f"day_start_equity_{market}"
    day_date_key = f"_day_start_date_{market}"
    day_start = s.get(day_key)
    if day_start is None or s.get(day_date_key) != today:
        db.patch_settings({day_key: summary["total_equity"], day_date_key: today})
        day_start = summary["total_equity"]

    limit_pct = float(s.get("daily_loss_limit_pct", 5))
    if day_start and summary["total_equity"] < day_start * (1 - limit_pct / 100):
        db.patch_settings(
            {
                halt_key: True,
                f"halt_reason_{market}": "單日虧損超過上限，已停止自動買進",
            }
        )
        return actions

    stop_pct = float(s.get("stop_loss_pct", 8))
    for p in summary["positions"]:
        if p["unrealized_pct"] <= -stop_pct:
            price = quotes.get(p["symbol"], p["price"])
            try:
                execute_trade(p["symbol"], "sell", p["qty"], price, market)
                actions.append(
                    {
                        "market": market,
                        "symbol": p["symbol"],
                        "reason": f"停損 {stop_pct}%",
                        "side": "sell",
                    }
                )
            except ValueError:
                pass
    return actions


def performance_stats(period: str = "all", market: str = MARKET_TW) -> dict[str, Any]:
    market = normalize_market(market)
    trades = [
        t
        for t in db.list_trades(limit=500, market=market)
        if t["side"] == "sell" and t["pnl"] is not None
    ]
    if period == "week":
        trades = trades[:20]
    elif period == "month":
        trades = trades[:60]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    return {
        "market": market,
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0,
        "max_win": max((t["pnl"] for t in wins), default=0),
        "max_loss": min((t["pnl"] for t in losses), default=0),
        "avg_pnl": round(sum(t["pnl"] for t in trades) / len(trades), 2) if trades else 0,
        "equity_curve": db.list_equity_snapshots(),
        "trades": trades[:50],
    }
