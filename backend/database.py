import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Optional

from backend.config import DATA_DIR, DB_PATH

DEFAULT_SETTINGS: dict[str, Any] = {
    "ai_engine": "openai",
    "order_mode": "notify_confirm",
    "order_size_mode": "percent",
    "order_size_value": 20,
    "virtual_cash": 1_000_000.0,
    "notify_enabled": True,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "volume_ratio_threshold": 2.0,
    "trigger_rsi": True,
    "trigger_ma_cross": True,
    "trigger_macd": True,
    "trigger_volume": True,
    "stop_loss_pct": 8.0,
    "daily_loss_limit_pct": 5.0,
    "backtest_use_ai": False,
    "backtest_ai_max_calls": 30,
    "backtest_ai_sample": "monthly_first_trigger",
    "trading_halted": False,
    "halt_reason": "",
    "day_start_equity": None,
}


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                qty INTEGER NOT NULL,
                avg_cost REAL NOT NULL,
                opened_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL,
                tax REAL NOT NULL,
                pnl REAL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analysis_cache (
                symbol TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                result_json TEXT NOT NULL,
                analyzed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS signal_notifications (
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (symbol, signal_type, date)
            );
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                date TEXT PRIMARY KEY,
                total_equity REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price REAL NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        for key, val in DEFAULT_SETTINGS.items():
            row = conn.execute(
                "SELECT 1 FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO settings (key, value_json) VALUES (?, ?)",
                    (key, json.dumps(val)),
                )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value_json FROM settings WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return DEFAULT_SETTINGS.get(key, default)
    return json.loads(row["value_json"])


def get_all_settings() -> dict[str, Any]:
    result = dict(DEFAULT_SETTINGS)
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
    for row in rows:
        result[row["key"]] = json.loads(row["value_json"])
    return result


def set_setting(key: str, value: Any) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            (key, json.dumps(value)),
        )


def patch_settings(updates: dict[str, Any]) -> dict[str, Any]:
    for k, v in updates.items():
        if v is not None:
            set_setting(k, v)
    return get_all_settings()


def list_watchlist() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, name, sort_order, created_at FROM watchlist ORDER BY sort_order, symbol"
        ).fetchall()
    return [dict(r) for r in rows]


def add_watchlist(symbol: str, name: Optional[str] = None) -> dict:
    symbol = symbol.strip().upper()
    items = list_watchlist()
    if len(items) >= 5 and symbol not in {i["symbol"] for i in items}:
        raise ValueError("自選股最多 5 檔")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO watchlist (symbol, name, sort_order, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET name = COALESCE(excluded.name, watchlist.name)
            """,
            (symbol, name or symbol, len(items), datetime.utcnow().isoformat()),
        )
    return next(i for i in list_watchlist() if i["symbol"] == symbol)


def remove_watchlist(symbol: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))


def get_position(symbol: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT symbol, qty, avg_cost, opened_at FROM positions WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
    return dict(row) if row else None


def list_positions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, qty, avg_cost, opened_at FROM positions"
        ).fetchall()
    return [dict(r) for r in rows]


def list_trades(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def insert_trade(
    symbol: str,
    side: str,
    qty: int,
    price: float,
    fee: float,
    tax: float,
    pnl: Optional[float] = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO trades (symbol, side, qty, price, fee, tax, pnl, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol.upper(),
                side,
                qty,
                price,
                fee,
                tax,
                pnl,
                datetime.utcnow().isoformat(),
            ),
        )
        return int(cur.lastrowid)


def upsert_position(symbol: str, qty: int, avg_cost: float) -> None:
    with get_conn() as conn:
        if qty <= 0:
            conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol.upper(),))
        else:
            conn.execute(
                """
                INSERT INTO positions (symbol, qty, avg_cost, opened_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty, avg_cost=excluded.avg_cost
                """,
                (symbol.upper(), qty, avg_cost, datetime.utcnow().isoformat()),
            )


def get_analysis_cache(symbol: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT symbol, fingerprint, result_json, analyzed_at FROM analysis_cache WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d.pop("result_json"))
    return d


def set_analysis_cache(symbol: str, fingerprint: str, result: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO analysis_cache (symbol, fingerprint, result_json, analyzed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                fingerprint=excluded.fingerprint,
                result_json=excluded.result_json,
                analyzed_at=excluded.analyzed_at
            """,
            (
                symbol.upper(),
                fingerprint,
                json.dumps(result),
                datetime.utcnow().isoformat(),
            ),
        )


def notification_sent_today(symbol: str, signal_type: str) -> bool:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM signal_notifications
            WHERE symbol = ? AND signal_type = ? AND date = ?
            """,
            (symbol.upper(), signal_type, today),
        ).fetchone()
    return row is not None


def mark_notification_sent(symbol: str, signal_type: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO signal_notifications (symbol, signal_type, date, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                symbol.upper(),
                signal_type,
                date.today().isoformat(),
                datetime.utcnow().isoformat(),
            ),
        )


def add_pending_order(symbol: str, side: str, qty: int, price: float, reason: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO pending_orders (symbol, side, qty, price, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (symbol.upper(), side, qty, price, reason, datetime.utcnow().isoformat()),
        )
        return int(cur.lastrowid)


def list_pending_orders() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_orders ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_pending_order(order_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_orders WHERE id = ?", (order_id,))


def record_equity_snapshot(total_equity: float) -> None:
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO equity_snapshots (date, total_equity) VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET total_equity = excluded.total_equity
            """,
            (today, total_equity),
        )


def list_equity_snapshots() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, total_equity FROM equity_snapshots ORDER BY date"
        ).fetchall()
    return [dict(r) for r in rows]
