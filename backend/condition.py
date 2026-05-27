from typing import Any, Optional

from backend import database as db


def evaluate_triggers(ind: dict[str, Any], settings: Optional[dict] = None) -> list[dict]:
    """Return list of fired trigger events: {type, label}."""
    s = settings or db.get_all_settings()
    fired: list[dict] = []
    rsi = ind.get("rsi")
    rsi_prev = ind.get("rsi_prev")
    oversold = float(s.get("rsi_oversold", 30))
    overbought = float(s.get("rsi_overbought", 70))

    if s.get("trigger_rsi", True) and rsi is not None:
        if rsi_prev is not None and rsi_prev >= oversold > rsi:
            fired.append({"type": "rsi_oversold", "label": "RSI 超賣"})
        elif rsi < oversold:
            fired.append({"type": "rsi_oversold", "label": "RSI 超賣"})
        if rsi_prev is not None and rsi_prev <= overbought < rsi:
            fired.append({"type": "rsi_overbought", "label": "RSI 超買"})
        elif rsi > overbought:
            fired.append({"type": "rsi_overbought", "label": "RSI 超買"})

    ma5, ma20 = ind.get("ma5"), ind.get("ma20")
    ma5_prev, ma20_prev = ind.get("ma5_prev"), ind.get("ma20_prev")
    if s.get("trigger_ma_cross", True) and all(
        v is not None for v in (ma5, ma20, ma5_prev, ma20_prev)
    ):
        if ma5_prev <= ma20_prev and ma5 > ma20:
            fired.append({"type": "golden_cross", "label": "黃金交叉"})
        if ma5_prev >= ma20_prev and ma5 < ma20:
            fired.append({"type": "death_cross", "label": "死亡交叉"})

    hist = ind.get("macd_hist")
    hist_prev = ind.get("macd_hist_prev")
    if s.get("trigger_macd", True) and hist is not None and hist_prev is not None:
        if hist_prev < 0 <= hist:
            fired.append({"type": "macd_bull", "label": "MACD 轉正"})
        if hist_prev > 0 >= hist:
            fired.append({"type": "macd_bear", "label": "MACD 轉負"})

    vr = ind.get("volume_ratio")
    threshold = float(s.get("volume_ratio_threshold", 2.0))
    if s.get("trigger_volume", True) and vr is not None and vr >= threshold:
        fired.append({"type": "volume_spike", "label": "量比異常"})

    return fired


def has_directional_trigger(fired: list[dict]) -> bool:
    return any(t["type"] != "volume_spike" for t in fired)
