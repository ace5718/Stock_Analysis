import json

import anthropic

from backend.ai.base import AIEngine, rule_based_analysis
from backend.config import ANTHROPIC_API_KEY
from backend.models import AnalysisResult


class ClaudeEngine(AIEngine):
    name = "claude"

    def analyze(self, symbol: str, indicators: dict, triggers: list[dict]) -> AnalysisResult:
        if not ANTHROPIC_API_KEY:
            return rule_based_analysis(symbol, triggers)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = (
            f"標的 {symbol} 觸發 {triggers} 指標 {indicators}。"
            "回 JSON: direction(buy|hold|sell), confidence, reason 繁中。"
        )
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        start = text.find("{")
        data = json.loads(text[start:] if start >= 0 else text)
        return AnalysisResult(
            direction=data.get("direction", "hold"),
            confidence=data.get("confidence", "medium"),
            reason=data.get("reason", ""),
        )
