import json

from openai import OpenAI

from backend.ai.base import AIEngine, rule_based_analysis
from backend.config import OPENAI_API_KEY
from backend.models import AnalysisResult


class OpenAIEngine(AIEngine):
    name = "openai"

    def analyze(self, symbol: str, indicators: dict, triggers: list[dict]) -> AnalysisResult:
        if not OPENAI_API_KEY:
            return rule_based_analysis(symbol, triggers)
        client = OpenAI(api_key=OPENAI_API_KEY)
        prompt = _prompt(symbol, indicators, triggers)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "你是台股技術分析助手。只回 JSON：direction(buy|hold|sell), confidence(high|medium|low), reason(繁中字串)。",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return AnalysisResult(
            direction=data.get("direction", "hold"),
            confidence=data.get("confidence", "medium"),
            reason=data.get("reason", ""),
        )


def _prompt(symbol: str, ind: dict, triggers: list[dict]) -> str:
    t = ", ".join(x["label"] for x in triggers)
    return (
        f"標的 {symbol}。觸發：{t}。"
        f"RSI={ind.get('rsi')} MA5={ind.get('ma5')} MA20={ind.get('ma20')} "
        f"MACD柱={ind.get('macd_hist')} 量比={ind.get('volume_ratio')} 收盤={ind.get('close')}"
    )
