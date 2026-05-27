from abc import ABC, abstractmethod

from backend import database as db
from backend.models import AnalysisResult, AiEngineName


class AIEngine(ABC):
    name: AiEngineName

    @abstractmethod
    def analyze(self, symbol: str, indicators: dict, triggers: list[dict]) -> AnalysisResult:
        raise NotImplementedError


def get_engine(name: str | None = None) -> AIEngine:
    engine_name = name or db.get_setting("ai_engine", "openai")
    if engine_name == "claude":
        from backend.ai.claude import ClaudeEngine

        return ClaudeEngine()
    if engine_name == "gemini":
        from backend.ai.gemini import GeminiEngine

        return GeminiEngine()
    from backend.ai.openai_engine import OpenAIEngine

    return OpenAIEngine()


def rule_based_analysis(symbol: str, triggers: list[dict]) -> AnalysisResult:
    from backend.backtest_rules import map_triggers_to_direction

    types = [t["type"] for t in triggers]
    direction = map_triggers_to_direction(types)
    labels = ", ".join(t["label"] for t in triggers) or "無觸發"
    conf = "medium" if direction != "hold" else "low"
    reason = f"規則引擎：{labels} → 建議{'買進' if direction == 'buy' else '賣出' if direction == 'sell' else '觀望'}"
    return AnalysisResult(direction=direction, confidence=conf, reason=reason)
