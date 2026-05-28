import pytest

from backend import database as db
from backend.config import DATA_DIR, DB_PATH
from backend import trade


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    db.init_db()
    db.patch_settings({"virtual_cash_tw": 1_000_000, "virtual_cash_crypto": 1_000_000})


def test_buy_and_sell_pnl():
    trade.execute_trade("2330", "buy", 1000, 100.0, market="tw")
    result = trade.execute_trade("2330", "sell", 1000, 110.0, market="tw")
    assert result["pnl"] is not None
    assert trade.available_cash("tw") > 1_000_000 - 100_000


def test_calc_buy_qty_percent():
    db.patch_settings({"order_size_mode": "percent", "order_size_value": 20})
    qty = trade.calc_buy_qty(50.0, market="tw")
    assert qty >= 1000
    assert int(qty) % 1000 == 0


def test_crypto_trade_separate_cash():
    trade.execute_trade("BTC", "buy", 0.01, 50000.0, market="crypto")
    assert trade.available_cash("crypto") < 1_000_000
    assert trade.available_cash("tw") == 1_000_000
