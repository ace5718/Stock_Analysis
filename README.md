# 台股 AI 模擬交易系統

個人台股波段模擬交易：即時行情（Fugle 或 mock）、技術指標觸發、可切換 AI 建議、模擬下單、Gmail 通知、歷史回測。

## 快速開始

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 編輯 .env 填入金鑰（無 Fugle 金鑰時使用 mock 行情）

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

瀏覽 http://localhost:8000

## 測試

```bash
pytest
```

## 文件

- 領域詞彙：[CONTEXT.md](CONTEXT.md)
- 架構決策：[docs/adr/](docs/adr/)
- 規格書：[docs/台股AI模擬交易系統_規格書.md](docs/台股AI模擬交易系統_規格書.md)
