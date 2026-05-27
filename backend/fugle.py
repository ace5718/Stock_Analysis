import asyncio
import math
import random
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import httpx
import pandas as pd

from backend.config import FUGLE_API_KEY

_quotes: dict[str, dict[str, Any]] = {}
_kline_cache: dict[str, pd.DataFrame] = {}
_mock_tasks: list[asyncio.Task] = []


def get_quote(symbol: str) -> dict[str, Any]:
    return _quotes.get(symbol.upper(), _empty_quote(symbol))


def get_all_quotes() -> dict[str, dict[str, Any]]:
    return dict(_quotes)


def _empty_quote(symbol: str) -> dict:
    return {
        "symbol": symbol.upper(),
        "name": symbol,
        "price": 0.0,
        "change": 0.0,
        "change_percent": 0.0,
        "volume": 0,
        "high": 0.0,
        "low": 0.0,
    }


def _mock_price(symbol: str, base: float) -> dict:
    t = datetime.now().timestamp() / 60
    seed = sum(ord(c) for c in symbol)
    price = base * (1 + 0.02 * math.sin(t / 10 + seed))
    prev = base
    change = price - prev
    pct = change / prev * 100 if prev else 0
    return {
        "symbol": symbol.upper(),
        "name": symbol,
        "price": round(price, 2),
        "change": round(change, 2),
        "change_percent": round(pct, 2),
        "volume": int(1000 + random.randint(0, 5000)),
        "high": round(price * 1.01, 2),
        "low": round(price * 0.99, 2),
    }


_BASES = {"2330": 980, "2317": 180, "0050": 180, "2454": 1200, "2881": 35}


async def start_quote_stream(symbols: list[str], on_update: Callable[[dict], Any]) -> None:
    global _mock_tasks
    for t in _mock_tasks:
        t.cancel()
    _mock_tasks.clear()
    if not symbols:
        return
    if FUGLE_API_KEY:
        task = asyncio.create_task(_fugle_poll_loop(symbols, on_update))
    else:
        task = asyncio.create_task(_mock_loop(symbols, on_update))
    _mock_tasks.append(task)


async def _mock_loop(symbols: list[str], on_update: Callable[[dict], Any]) -> None:
    while True:
        for sym in symbols:
            base = _BASES.get(sym, 100.0)
            q = _mock_price(sym, base)
            _quotes[sym.upper()] = q
            await on_update(q)
        await asyncio.sleep(2)


async def _fugle_poll_loop(symbols: list[str], on_update: Callable[[dict], Any]) -> None:
    headers = {"X-API-KEY": FUGLE_API_KEY}
    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            for sym in symbols:
                try:
                    r = await client.get(
                        f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sym}",
                        headers=headers,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        q = _parse_fugle_quote(sym, data)
                        _quotes[sym.upper()] = q
                        await on_update(q)
                except Exception:
                    q = _mock_price(sym, _BASES.get(sym, 100.0))
                    _quotes[sym.upper()] = q
                    await on_update(q)
            await asyncio.sleep(3)


def _parse_fugle_quote(symbol: str, data: dict) -> dict:
    last = data.get("lastPrice") or data.get("price") or 0
    prev = data.get("previousClose") or data.get("prevClose") or last
    change = float(last) - float(prev) if prev else 0
    pct = change / float(prev) * 100 if prev else 0
    return {
        "symbol": symbol.upper(),
        "name": data.get("name", symbol),
        "price": float(last),
        "change": round(change, 2),
        "change_percent": round(pct, 2),
        "volume": int(data.get("totalVolume") or data.get("volume") or 0),
        "high": float(data.get("highPrice") or last),
        "low": float(data.get("lowPrice") or last),
    }


def fetch_klines(symbol: str, days: int = 120) -> pd.DataFrame:
    sym = symbol.upper()
    if sym in _kline_cache and len(_kline_cache[sym]) >= days:
        return _kline_cache[sym].tail(days).copy()
    if FUGLE_API_KEY:
        df = _fetch_fugle_candles(sym, days)
    else:
        df = _generate_mock_ohlcv(sym, days)
    _kline_cache[sym] = df
    return df.copy()


def _fetch_fugle_candles(symbol: str, days: int) -> pd.DataFrame:
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol}",
                headers={"X-API-KEY": FUGLE_API_KEY},
                params={"timeframe": "D"},
            )
            if r.status_code == 200:
                rows = r.json().get("data", r.json())
                if isinstance(rows, list) and rows:
                    df = pd.DataFrame(rows)
                    colmap = {
                        "open": "open",
                        "high": "high",
                        "low": "low",
                        "close": "close",
                        "volume": "volume",
                        "date": "time",
                    }
                    for k, v in colmap.items():
                        if k in df.columns and v not in df.columns:
                            df[v] = df[k]
                    if "time" not in df.columns:
                        df["time"] = range(len(df))
                    return df[["time", "open", "high", "low", "close", "volume"]].tail(days)
    except Exception:
        pass
    return _generate_mock_ohlcv(symbol, days)


def _generate_mock_ohlcv(symbol: str, days: int) -> pd.DataFrame:
    base = _BASES.get(symbol, 100.0)
    seed = sum(ord(c) for c in symbol)
    random.seed(seed)
    rows = []
    price = base
    start = datetime.now() - timedelta(days=days)
    for i in range(days):
        d = start + timedelta(days=i)
        o = price
        c = o * (1 + random.uniform(-0.03, 0.03))
        h = max(o, c) * (1 + random.uniform(0, 0.01))
        l = min(o, c) * (1 - random.uniform(0, 0.01))
        v = random.randint(1_000_000, 10_000_000)
        rows.append(
            {
                "time": d.strftime("%Y-%m-%d"),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": v,
            }
        )
        price = c
    return pd.DataFrame(rows)


def fetch_klines_range(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    df = fetch_klines(symbol, days=730)
    if df.empty:
        return df
    mask = (df["time"] >= start_date) & (df["time"] <= end_date)
    return df.loc[mask].copy()
