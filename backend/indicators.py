from typing import Any, Optional

import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    ta = None


def compute_indicators(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Expect columns: open, high, low, close, volume."""
    df = ohlcv.copy()
    if df.empty or len(df) < 2:
        return df
    close = df["close"]
    df["ma5"] = close.rolling(5).mean()
    df["ma20"] = close.rolling(20).mean()
    if ta is not None:
        df["rsi"] = ta.rsi(close, length=14)
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        if macd is not None:
            df["macd_hist"] = macd.iloc[:, 2] if macd.shape[1] > 2 else macd.iloc[:, 0]
    else:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9, adjust=False).mean()
        df["macd_hist"] = macd_line - signal
    vol_ma5 = df["volume"].rolling(5).mean()
    df["volume_ratio"] = df["volume"] / vol_ma5.replace(0, 1)
    return df


def latest_indicator_row(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {}
    row = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else row
    return {
        "close": float(row.get("close", 0) or 0),
        "ma5": _f(row.get("ma5")),
        "ma20": _f(row.get("ma20")),
        "rsi": _f(row.get("rsi")),
        "macd_hist": _f(row.get("macd_hist")),
        "macd_hist_prev": _f(prev.get("macd_hist")),
        "volume_ratio": _f(row.get("volume_ratio")),
        "ma5_prev": _f(prev.get("ma5")),
        "ma20_prev": _f(prev.get("ma20")),
        "rsi_prev": _f(prev.get("rsi")),
    }


def indicator_fingerprint(ind: dict[str, Any]) -> str:
    keys = ("rsi", "ma5", "ma20", "macd_hist", "volume_ratio")
    parts = [f"{k}:{round(ind.get(k) or 0, 2)}" for k in keys]
    return "|".join(parts)


def _f(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return float(v)
