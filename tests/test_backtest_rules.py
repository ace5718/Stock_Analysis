from backend.backtest_rules import map_triggers_to_direction


def test_buy_on_oversold():
    assert map_triggers_to_direction(["rsi_oversold"]) == "buy"


def test_sell_on_overbought():
    assert map_triggers_to_direction(["rsi_overbought"]) == "sell"


def test_volume_only_hold():
    assert map_triggers_to_direction(["volume_spike"]) == "hold"


def test_conflict_hold():
    assert map_triggers_to_direction(["rsi_oversold", "rsi_overbought"]) == "hold"
