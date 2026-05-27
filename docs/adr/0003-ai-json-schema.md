# AI 輸出結構化 JSON 與 schema 驗證

所有 AI 引擎須回傳並驗證同一 `AnalysisResult` 形狀：`direction`（buy/hold/sell）、`confidence`（high/medium/low）、`reason`（字串）、`disclaimer`（固定免責）。利於 UI、自動下單與快取 fingerprint 比對。
