# 單一 Fugle WebSocket，最多訂閱 5 檔

即時行情透過一條 Fugle Market Data WebSocket 連線，同時訂閱不超過 5 檔自選股（免費方案上限）。自選股變更時 unsubscribe 再 subscribe。無 API 金鑰時改走本機 mock 報價供開發與測試。
