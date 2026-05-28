"""Binance 公開行情（虛擬貨幣），與台股 Fugle 分離。"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Callable

import httpx
import pandas as pd

from backend.markets import MARKET_CRYPTO, normalize_symbol

BINANCE_API = "https://api.binance.com"
_quotes: dict[str, dict[str, Any]] = {}
_kline_cache: dict[str, pd.DataFrame] = {}
_stream_task: asyncio.Task | None = None


def clear_kline_cache() -> None:
    _kline_cache.clear()


def get_quote(symbol: str) -> dict[str, Any]:
    sym = normalize_symbol(symbol, MARKET_CRYPTO)
    return _quotes.get(sym, _empty_quote(sym))


def get_all_quotes() -> dict[str, dict[str, Any]]:
    return dict(_quotes)


def _empty_quote(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "name": symbol.replace("USDT", ""),
        "market": MARKET_CRYPTO,
        "price": 0.0,
        "change": 0.0,
        "change_percent": 0.0,
        "volume": 0.0,
        "high": 0.0,
        "low": 0.0,
    }


async def start_quote_stream(symbols: list[str], on_update: Callable[[dict], Any]) -> None:
    global _stream_task
    if _stream_task:
        _stream_task.cancel()
    if not symbols:
        return
    _stream_task = asyncio.create_task(_poll_loop(symbols, on_update))


async def _poll_loop(symbols: list[str], on_update: Callable[[dict], Any]) -> None:
    syms = [normalize_symbol(s, MARKET_CRYPTO) for s in symbols]
    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            for sym in syms:
                try:
                    r = await client.get(
                        f"{BINANCE_API}/api/v3/ticker/24hr",
                        params={"symbol": sym},
                    )
                    if r.status_code == 200:
                        q = _parse_ticker(sym, r.json())
                        _quotes[sym] = q
                        await on_update(q)
                except Exception:
                    pass
            await asyncio.sleep(3)


def _parse_ticker(symbol: str, data: dict) -> dict:
    price = float(data.get("lastPrice") or 0)
    change = float(data.get("priceChange") or 0)
    pct = float(data.get("priceChangePercent") or 0)
    return {
        "symbol": symbol,
        "name": symbol.replace("USDT", ""),
        "market": MARKET_CRYPTO,
        "price": round(price, 4),
        "change": round(change, 4),
        "change_percent": round(pct, 2),
        "volume": float(data.get("volume") or 0),
        "high": float(data.get("highPrice") or price),
        "low": float(data.get("lowPrice") or price),
    }


def fetch_klines(symbol: str, days: int = 120) -> pd.DataFrame:
    sym = normalize_symbol(symbol, MARKET_CRYPTO)
    if sym in _kline_cache and len(_kline_cache[sym]) >= days:
        return _kline_cache[sym].tail(days).reset_index(drop=True).copy()
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                f"{BINANCE_API}/api/v3/klines",
                params={"symbol": sym, "interval": "1d", "limit": min(days, 1000)},
            )
            if r.status_code == 200:
                rows = r.json()
                data = []
                for row in rows:
                    ts = int(row[0]) / 1000
                    dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                    data.append(
                        {
                            "time": dt,
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "volume": float(row[5]),
                        }
                    )
                df = pd.DataFrame(data)
                if not df.empty:
                    df = df.sort_values("time").reset_index(drop=True)
                    _kline_cache[sym] = df
                    return df.copy()
    except Exception:
        pass
    return _generate_mock_ohlcv(sym, days)


def _generate_mock_ohlcv(symbol: str, days: int) -> pd.DataFrame:
    import random

    base = 50000.0 if "BTC" in symbol else 3000.0
    seed = sum(ord(c) for c in symbol)
    random.seed(seed)
    rows = []
    price = base
    start = datetime.utcnow() - timedelta(days=days)
    for i in range(days):
        d = start + timedelta(days=i)
        o = price
        c = o * (1 + random.uniform(-0.05, 0.05))
        h = max(o, c) * 1.01
        l = min(o, c) * 0.99
        rows.append(
            {
                "time": d.strftime("%Y-%m-%d"),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": random.randint(1000, 50000),
            }
        )
        price = c
    return pd.DataFrame(rows)
