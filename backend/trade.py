import math
from datetime import date
from typing import Any, Optional

from backend import database as db
from backend.config import FEE_RATE, TAX_RATE


def available_cash() -> float:
    return float(db.get_setting("virtual_cash", 1_000_000))


def set_cash(amount: float) -> None:
    db.set_setting("virtual_cash", amount)


def calc_buy_qty(price: float, settings: Optional[dict] = None) -> int:
    s = settings or db.get_all_settings()
    cash = available_cash()
    pct = min(float(s.get("order_size_value", 20)), 20) / 100.0
    mode = s.get("order_size_mode", "percent")
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
    return max(qty, 0)


def execute_trade(symbol: str, side: str, qty: int, price: float) -> dict[str, Any]:
    symbol = symbol.upper()
    if qty <= 0 or qty % 1000 != 0:
        raise ValueError("股數須為正整數且以張為單位（1000 股）")
    cash = available_cash()
    fee = round(price * qty * FEE_RATE, 2)
    tax = 0.0
    pnl = None

    if side == "buy":
        cost = price * qty + fee
        if cost > cash:
            raise ValueError("虛擬資金不足")
        pos = db.get_position(symbol)
        if pos:
            total_qty = pos["qty"] + qty
            avg = (pos["avg_cost"] * pos["qty"] + price * qty) / total_qty
            db.upsert_position(symbol, total_qty, avg)
        else:
            db.upsert_position(symbol, qty, price)
        set_cash(cash - cost)
    else:
        pos = db.get_position(symbol)
        if not pos or pos["qty"] < qty:
            raise ValueError("持倉不足")
        tax = round(price * qty * TAX_RATE, 2)
        proceeds = price * qty - fee - tax
        pnl = round(proceeds - pos["avg_cost"] * qty, 2)
        new_qty = pos["qty"] - qty
        db.upsert_position(symbol, new_qty, pos["avg_cost"])
        set_cash(cash + proceeds)

    tid = db.insert_trade(symbol, side, qty, price, fee, tax, pnl)
    equity = portfolio_summary({})
    db.record_equity_snapshot(equity["total_equity"])
    return {"trade_id": tid, "side": side, "qty": qty, "price": price, "fee": fee, "tax": tax, "pnl": pnl}


def portfolio_summary(quotes: dict[str, float]) -> dict[str, Any]:
    cash = available_cash()
    positions = db.list_positions()
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
                "symbol": p["symbol"],
                "qty": p["qty"],
                "avg_cost": p["avg_cost"],
                "price": price,
                "market_value": mv,
                "unrealized_pnl": round(u, 2),
                "unrealized_pct": round(u / cost * 100, 2) if cost else 0,
            }
        )
    total = cash + holdings_value
    return {
        "cash": round(cash, 2),
        "holdings_value": round(holdings_value, 2),
        "total_equity": round(total, 2),
        "unrealized_pnl": round(unrealized, 2),
        "positions": details,
    }


def check_risk_and_maybe_halt(quotes: dict[str, float]) -> list[dict]:
    """Stop-loss per position; daily loss halt. Returns auto-sell actions."""
    s = db.get_all_settings()
    actions = []
    if s.get("trading_halted"):
        return actions

    summary = portfolio_summary(quotes)
    today = date.today().isoformat()
    day_start = s.get("day_start_equity")
    if day_start is None or s.get("_day_start_date") != today:
        db.patch_settings({"day_start_equity": summary["total_equity"], "_day_start_date": today})
        day_start = summary["total_equity"]

    limit_pct = float(s.get("daily_loss_limit_pct", 5))
    if day_start and summary["total_equity"] < day_start * (1 - limit_pct / 100):
        db.patch_settings(
            {"trading_halted": True, "halt_reason": "單日虧損超過上限，已停止自動買進"}
        )
        return actions

    stop_pct = float(s.get("stop_loss_pct", 8))
    for p in summary["positions"]:
        if p["unrealized_pct"] <= -stop_pct:
            price = quotes.get(p["symbol"], p["price"])
            try:
                execute_trade(p["symbol"], "sell", p["qty"], price)
                actions.append(
                    {"symbol": p["symbol"], "reason": f"停損 {stop_pct}%", "side": "sell"}
                )
            except ValueError:
                pass
    return actions


def performance_stats(period: str = "all") -> dict[str, Any]:
    trades = [t for t in db.list_trades() if t["side"] == "sell" and t["pnl"] is not None]
    if period == "week":
        trades = trades[:20]
    elif period == "month":
        trades = trades[:60]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0,
        "max_win": max((t["pnl"] for t in wins), default=0),
        "max_loss": min((t["pnl"] for t in losses), default=0),
        "avg_pnl": round(sum(t["pnl"] for t in trades) / len(trades), 2) if trades else 0,
        "equity_curve": db.list_equity_snapshots(),
        "trades": trades[:50],
    }
