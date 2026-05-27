import json

import google.generativeai as genai

from backend.ai.base import AIEngine, rule_based_analysis
from backend.config import GEMINI_API_KEY
from backend.models import AnalysisResult


class GeminiEngine(AIEngine):
    name = "gemini"

    def analyze(self, symbol: str, indicators: dict, triggers: list[dict]) -> AnalysisResult:
        if not GEMINI_API_KEY:
            return rule_based_analysis(symbol, triggers)
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"標的 {symbol} 觸發 {triggers} 指標 {indicators}。"
            "只回 JSON: direction(buy|hold|sell), confidence, reason 繁中。"
        )
        resp = model.generate_content(prompt)
        text = resp.text or "{}"
        start = text.find("{")
        data = json.loads(text[start:] if start >= 0 else text)
        return AnalysisResult(
            direction=data.get("direction", "hold"),
            confidence=data.get("confidence", "medium"),
            reason=data.get("reason", ""),
        )
