from typing import Literal, Optional

from pydantic import BaseModel, Field

Direction = Literal["buy", "hold", "sell"]
Confidence = Literal["high", "medium", "low"]
OrderMode = Literal["notify_confirm", "full_auto"]
OrderSizeMode = Literal["percent", "fixed_lots"]
AiEngineName = Literal["openai", "claude", "gemini"]


class AnalysisResult(BaseModel):
    direction: Direction
    confidence: Confidence
    reason: str
    disclaimer: str = "AI 判斷僅供參考，不構成投資建議。"


class WatchlistItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    sort_order: int = 0


class WatchlistCreate(BaseModel):
    symbol: str
    name: Optional[str] = None


class TradeRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    qty: int = Field(gt=0)


class SettingsPatch(BaseModel):
    ai_engine: Optional[AiEngineName] = None
    order_mode: Optional[OrderMode] = None
    order_size_mode: Optional[OrderSizeMode] = None
    order_size_value: Optional[float] = None
    virtual_cash: Optional[float] = None
    notify_enabled: Optional[bool] = None
    rsi_oversold: Optional[float] = None
    rsi_overbought: Optional[float] = None
    volume_ratio_threshold: Optional[float] = None
    trigger_rsi: Optional[bool] = None
    trigger_ma_cross: Optional[bool] = None
    trigger_macd: Optional[bool] = None
    trigger_volume: Optional[bool] = None
    stop_loss_pct: Optional[float] = None
    daily_loss_limit_pct: Optional[float] = None
    backtest_use_ai: Optional[bool] = None
    backtest_ai_max_calls: Optional[int] = None


class BacktestRequest(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    use_ai: Optional[bool] = None


class ConfirmOrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    qty: Optional[int] = None
