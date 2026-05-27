from typing import Literal, Optional

Direction = Literal["buy", "sell", "hold"]

BUY_TYPES = {"rsi_oversold", "golden_cross", "macd_bull"}
SELL_TYPES = {"rsi_overbought", "death_cross", "macd_bear"}


def map_triggers_to_direction(trigger_types: list[str]) -> Direction:
    """Scheme A: per-trigger mapping; conflict or volume-only -> hold."""
    types = set(trigger_types)
    directional = types - {"volume_spike"}
    if not directional:
        return "hold"
    buys = directional & BUY_TYPES
    sells = directional & SELL_TYPES
    if buys and sells:
        return "hold"
    if buys:
        return "buy"
    if sells:
        return "sell"
    return "hold"


def triggers_from_types(trigger_types: list[str]) -> list[dict]:
    labels = {
        "rsi_oversold": "RSI 超賣",
        "rsi_overbought": "RSI 超買",
        "golden_cross": "黃金交叉",
        "death_cross": "死亡交叉",
        "macd_bull": "MACD 轉正",
        "macd_bear": "MACD 轉負",
        "volume_spike": "量比異常",
    }
    return [{"type": t, "label": labels.get(t, t)} for t in trigger_types]
