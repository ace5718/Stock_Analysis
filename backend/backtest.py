from datetime import datetime
from typing import Any, Optional

import pandas as pd

from backend import database as db
from backend.ai.base import get_engine, rule_based_analysis
from backend.backtest_rules import map_triggers_to_direction
from backend.condition import evaluate_triggers
from backend.config import FEE_RATE, TAX_RATE
from backend.fugle import fetch_klines_range
from backend.indicators import compute_indicators
from backend.models import AnalysisResult


def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    use_ai: Optional[bool] = None,
) -> dict[str, Any]:
    settings = db.get_all_settings()
    use_ai = use_ai if use_ai is not None else bool(settings.get("backtest_use_ai", False))
    max_ai = int(settings.get("backtest_ai_max_calls", 30))
    ai_calls = 0
    sample_mode = settings.get("backtest_ai_sample", "monthly_first_trigger")
    last_ai_month: Optional[str] = None

    df = fetch_klines_range(symbol, start_date, end_date)
    if df.empty or len(df) < 25:
        return {"error": "資料不足", "symbol": symbol}

    df = compute_indicators(df)
    cash = float(settings.get("virtual_cash", 1_000_000))
    initial_cash = cash
    qty = 0
    avg_cost = 0.0
    trades_log: list[dict] = []
    equity_curve: list[dict] = []

    for i in range(20, len(df)):
        window = df.iloc[: i + 1]
        row = window.iloc[-1]
        prev = window.iloc[-2]
        ind = {
            "close": float(row["close"]),
            "ma5": _fv(row.get("ma5")),
            "ma20": _fv(row.get("ma20")),
            "rsi": _fv(row.get("rsi")),
            "macd_hist": _fv(row.get("macd_hist")),
            "macd_hist_prev": _fv(prev.get("macd_hist")),
            "volume_ratio": _fv(row.get("volume_ratio")),
            "ma5_prev": _fv(prev.get("ma5")),
            "ma20_prev": _fv(prev.get("ma20")),
            "rsi_prev": _fv(prev.get("rsi")),
        }
        fired = evaluate_triggers(ind, settings)
        if not fired:
            price = float(row["close"])
            equity_curve.append(
                {"date": str(row["time"]), "equity": cash + qty * price}
            )
            continue

        types = [t["type"] for t in fired]
        direction: str
        month_key = str(row["time"])[:7]

        if use_ai and ai_calls < max_ai:
            if sample_mode == "monthly_first_trigger":
                if last_ai_month != month_key:
                    engine = get_engine()
                    try:
                        result = engine.analyze(symbol, ind, fired)
                        direction = result.direction
                        ai_calls += 1
                        last_ai_month = month_key
                    except Exception:
                        direction = map_triggers_to_direction(types)
                else:
                    direction = map_triggers_to_direction(types)
            else:
                engine = get_engine()
                try:
                    result = engine.analyze(symbol, ind, fired)
                    direction = result.direction
                    ai_calls += 1
                except Exception:
                    direction = map_triggers_to_direction(types)
        else:
            direction = map_triggers_to_direction(types)

        price = float(row["close"])
        if direction == "buy" and qty == 0 and cash >= price * 1000:
            buy_qty = int(cash * 0.2 / (price * (1 + FEE_RATE)))
            buy_qty = (buy_qty // 1000) * 1000
            if buy_qty >= 1000:
                fee = price * buy_qty * FEE_RATE
                cash -= price * buy_qty + fee
                qty = buy_qty
                avg_cost = price
                trades_log.append(
                    {"date": str(row["time"]), "side": "buy", "price": price, "qty": buy_qty}
                )
        elif direction == "sell" and qty > 0:
            fee = price * qty * FEE_RATE
            tax = price * qty * TAX_RATE
            pnl = price * qty - fee - tax - avg_cost * qty
            cash += price * qty - fee - tax
            trades_log.append(
                {
                    "date": str(row["time"]),
                    "side": "sell",
                    "price": price,
                    "qty": qty,
                    "pnl": round(pnl, 2),
                }
            )
            qty = 0
            avg_cost = 0.0

        equity_curve.append({"date": str(row["time"]), "equity": cash + qty * price})

    final_price = float(df.iloc[-1]["close"])
    final_equity = cash + qty * final_price
    buy_hold_start = float(df.iloc[20]["close"])
    buy_hold_end = final_price
    buy_hold_return = (buy_hold_end - buy_hold_start) / buy_hold_start * 100
    strategy_return = (final_equity - initial_cash) / initial_cash * 100

    sells = [t for t in trades_log if t["side"] == "sell"]
    wins = [t for t in sells if t.get("pnl", 0) > 0]
    max_dd = _max_drawdown([e["equity"] for e in equity_curve])
    days = max(len(df) - 20, 1)
    annualized = ((final_equity / initial_cash) ** (365 / days) - 1) * 100 if days else 0

    return {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "use_ai": use_ai,
        "ai_calls_used": ai_calls,
        "strategy_return_pct": round(strategy_return, 2),
        "buy_hold_return_pct": round(buy_hold_return, 2),
        "win_rate": round(len(wins) / len(sells) * 100, 2) if sells else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "annualized_return_pct": round(annualized, 2),
        "trades_count": len(trades_log),
        "equity_curve": equity_curve[-100:],
        "trades": trades_log[-30:],
    }


def _fv(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return float(v)


def _max_drawdown(equities: list[float]) -> float:
    if not equities:
        return 0.0
    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)
    return max_dd
