# 回測預設規則引擎，AI 為 opt-in 加配額

回測預設 `backtest_use_ai=false`，依觸發類型映射買／賣／觀望（方案 A）；同一 K 棒相反訊號或僅量比異常時為觀望。開啟 AI 時受 `backtest_ai_max_calls` 與 `monthly_first_trigger` 抽樣限制，避免兩年歷史資料燒盡 LLM 配額。
