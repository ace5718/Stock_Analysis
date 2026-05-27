from backend.condition import evaluate_triggers, has_directional_trigger


def test_rsi_oversold_fires():
    ind = {"rsi": 28, "rsi_prev": 32, "ma5": None, "ma20": None}
    fired = evaluate_triggers(ind, {"rsi_oversold": 30, "trigger_rsi": True, "trigger_ma_cross": False, "trigger_macd": False, "trigger_volume": False})
    assert any(t["type"] == "rsi_oversold" for t in fired)
    assert has_directional_trigger(fired)


def test_volume_not_directional():
    fired = [{"type": "volume_spike", "label": "量比"}]
    assert not has_directional_trigger(fired)
