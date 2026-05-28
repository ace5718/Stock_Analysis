import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Optional

from backend.config import DATA_DIR, DB_PATH
from backend.markets import MARKET_TW, MAX_WATCHLIST, normalize_market, normalize_symbol

DEFAULT_SETTINGS: dict[str, Any] = {
    "ai_engine": "openai",
    "order_mode": "notify_confirm",
    "order_size_mode": "percent",
    "order_size_value": 20,
    "virtual_cash": 1_000_000.0,
    "virtual_cash_tw": 1_000_000.0,
    "virtual_cash_crypto": 1_000_000.0,
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
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                name TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (market, symbol)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS positions (
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_cost REAL NOT NULL,
                opened_at TEXT NOT NULL,
                PRIMARY KEY (market, symbol)
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL,
                tax REAL NOT NULL,
                pnl REAL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analysis_cache (
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                result_json TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                PRIMARY KEY (market, symbol)
            );
            CREATE TABLE IF NOT EXISTS signal_notifications (
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (market, symbol, signal_type, date)
            );
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                date TEXT PRIMARY KEY,
                total_equity REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
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
        _migrate_legacy_schema(conn)


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    ordered = sorted((r[5], r[1]) for r in rows if r[5])
    return [name for _, name in ordered]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _rebuild_table(conn: sqlite3.Connection, table: str, create_sql: str, copy_sql: str) -> None:
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
    conn.execute(create_sql)
    conn.execute(copy_sql)
    conn.execute(f"DROP TABLE {table}_old")


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    """舊版僅 symbol 主鍵的資料庫升級為分市場結構。"""
    if not _table_exists(conn, "watchlist"):
        return

    cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist)").fetchall()}
    if cols and "market" not in cols:
        _rebuild_table(
            conn,
            "watchlist",
            """
            CREATE TABLE watchlist (
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                name TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (market, symbol)
            )
            """,
            """
            INSERT INTO watchlist (market, symbol, name, sort_order, created_at)
            SELECT 'tw', symbol, name, sort_order, created_at FROM watchlist_old
            """,
        )

    for table in ("positions", "trades", "pending_orders"):
        tcols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if tcols and "market" not in tcols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN market TEXT NOT NULL DEFAULT 'tw'"
            )

    if _table_exists(conn, "positions") and _pk_columns(conn, "positions") == ["symbol"]:
        _rebuild_table(
            conn,
            "positions",
            """
            CREATE TABLE positions (
                market TEXT NOT NULL DEFAULT 'tw',
                symbol TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_cost REAL NOT NULL,
                opened_at TEXT NOT NULL,
                PRIMARY KEY (market, symbol)
            )
            """,
            """
            INSERT INTO positions (market, symbol, qty, avg_cost, opened_at)
            SELECT COALESCE(market, 'tw'), symbol, qty, avg_cost, opened_at
            FROM positions_old
            """,
        )

    if _table_exists(conn, "analysis_cache"):
        acols = {r[1] for r in conn.execute("PRAGMA table_info(analysis_cache)").fetchall()}
        if acols and "market" not in acols:
            conn.execute(
                "ALTER TABLE analysis_cache ADD COLUMN market TEXT NOT NULL DEFAULT 'tw'"
            )
        if _pk_columns(conn, "analysis_cache") != ["market", "symbol"]:
            _rebuild_table(
                conn,
                "analysis_cache",
                """
                CREATE TABLE analysis_cache (
                    market TEXT NOT NULL DEFAULT 'tw',
                    symbol TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    PRIMARY KEY (market, symbol)
                )
                """,
                """
                INSERT INTO analysis_cache
                    (market, symbol, fingerprint, result_json, analyzed_at)
                SELECT COALESCE(market, 'tw'), symbol, fingerprint, result_json, analyzed_at
                FROM analysis_cache_old
                """,
            )

    if _table_exists(conn, "signal_notifications"):
        scols = {
            r[1] for r in conn.execute("PRAGMA table_info(signal_notifications)").fetchall()
        }
        if scols and "market" not in scols:
            conn.execute(
                "ALTER TABLE signal_notifications ADD COLUMN market TEXT NOT NULL DEFAULT 'tw'"
            )
        if _pk_columns(conn, "signal_notifications") != [
            "market",
            "symbol",
            "signal_type",
            "date",
        ]:
            _rebuild_table(
                conn,
                "signal_notifications",
                """
                CREATE TABLE signal_notifications (
                    market TEXT NOT NULL DEFAULT 'tw',
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    date TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY (market, symbol, signal_type, date)
                )
                """,
                """
                INSERT INTO signal_notifications
                    (market, symbol, signal_type, date, sent_at)
                SELECT COALESCE(market, 'tw'), symbol, signal_type, date, sent_at
                FROM signal_notifications_old
                """,
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


def list_watchlist(market: str = MARKET_TW) -> list[dict]:
    market = normalize_market(market)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT market, symbol, name, sort_order, created_at FROM watchlist
            WHERE market = ? ORDER BY sort_order, symbol
            """,
            (market,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_watchlist(symbol: str, name: Optional[str] = None, market: str = MARKET_TW) -> dict:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    items = list_watchlist(market)
    if len(items) >= MAX_WATCHLIST and symbol not in {i["symbol"] for i in items}:
        raise ValueError(f"自選清單最多 {MAX_WATCHLIST} 檔")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO watchlist (market, symbol, name, sort_order, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(market, symbol) DO UPDATE SET
                name = COALESCE(excluded.name, watchlist.name)
            """,
            (
                market,
                symbol,
                name or symbol.replace("USDT", "") if market == "crypto" else symbol,
                len(items),
                datetime.utcnow().isoformat(),
            ),
        )
    return next(i for i in list_watchlist(market) if i["symbol"] == symbol)


def remove_watchlist(symbol: str, market: str = MARKET_TW) -> None:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE market = ? AND symbol = ?",
            (market, symbol),
        )


def get_position(symbol: str, market: str = MARKET_TW) -> Optional[dict]:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT market, symbol, qty, avg_cost, opened_at FROM positions
            WHERE market = ? AND symbol = ?
            """,
            (market, symbol),
        ).fetchone()
    return dict(row) if row else None


def list_positions(market: str = MARKET_TW) -> list[dict]:
    market = normalize_market(market)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT market, symbol, qty, avg_cost, opened_at FROM positions
            WHERE market = ?
            """,
            (market,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_trades(limit: int = 200, market: str = MARKET_TW) -> list[dict]:
    market = normalize_market(market)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM trades WHERE market = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (market, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def insert_trade(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    fee: float,
    tax: float,
    pnl: Optional[float] = None,
    market: str = MARKET_TW,
) -> int:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO trades (market, symbol, side, qty, price, fee, tax, pnl, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market,
                symbol,
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


def upsert_position(
    symbol: str, qty: float, avg_cost: float, market: str = MARKET_TW
) -> None:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        if qty <= 0:
            conn.execute(
                "DELETE FROM positions WHERE market = ? AND symbol = ?",
                (market, symbol),
            )
        else:
            conn.execute(
                """
                INSERT INTO positions (market, symbol, qty, avg_cost, opened_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(market, symbol) DO UPDATE SET
                    qty=excluded.qty, avg_cost=excluded.avg_cost
                """,
                (market, symbol, qty, avg_cost, datetime.utcnow().isoformat()),
            )


def get_analysis_cache(symbol: str, market: str = MARKET_TW) -> Optional[dict]:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT market, symbol, fingerprint, result_json, analyzed_at
            FROM analysis_cache WHERE market = ? AND symbol = ?
            """,
            (market, symbol),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d.pop("result_json"))
    return d


def set_analysis_cache(
    symbol: str, fingerprint: str, result: dict, market: str = MARKET_TW
) -> None:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO analysis_cache (market, symbol, fingerprint, result_json, analyzed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(market, symbol) DO UPDATE SET
                fingerprint=excluded.fingerprint,
                result_json=excluded.result_json,
                analyzed_at=excluded.analyzed_at
            """,
            (
                market,
                symbol,
                fingerprint,
                json.dumps(result),
                datetime.utcnow().isoformat(),
            ),
        )


def notification_sent_today(
    symbol: str, signal_type: str, market: str = MARKET_TW
) -> bool:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM signal_notifications
            WHERE market = ? AND symbol = ? AND signal_type = ? AND date = ?
            """,
            (market, symbol, signal_type, today),
        ).fetchone()
    return row is not None


def mark_notification_sent(symbol: str, signal_type: str, market: str = MARKET_TW) -> None:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO signal_notifications
            (market, symbol, signal_type, date, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                market,
                symbol,
                signal_type,
                date.today().isoformat(),
                datetime.utcnow().isoformat(),
            ),
        )


def add_pending_order(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    reason: str,
    market: str = MARKET_TW,
) -> int:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO pending_orders (market, symbol, side, qty, price, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market,
                symbol,
                side,
                qty,
                price,
                reason,
                datetime.utcnow().isoformat(),
            ),
        )
        return int(cur.lastrowid)


def list_pending_orders(market: str = MARKET_TW) -> list[dict]:
    market = normalize_market(market)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM pending_orders WHERE market = ?
            ORDER BY created_at DESC
            """,
            (market,),
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
