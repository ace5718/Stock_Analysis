"""市場類型：台股與虛擬貨幣分開，不共用自選股與模擬帳戶。"""

MARKET_TW = "tw"
MARKET_CRYPTO = "crypto"
VALID_MARKETS = (MARKET_TW, MARKET_CRYPTO)

MAX_WATCHLIST = 5


def normalize_market(market: str) -> str:
    m = (market or MARKET_TW).lower().strip()
    if m not in VALID_MARKETS:
        raise ValueError("market 須為 tw 或 crypto")
    return m


def normalize_symbol(symbol: str, market: str) -> str:
    s = symbol.strip().upper()
    if market == MARKET_CRYPTO:
        if not s.endswith("USDT"):
            s = f"{s}USDT"
        return s
    if not s.isdigit() or len(s) != 4:
        raise ValueError("台股代號須為 4 位數字，例如 2330")
    return s
