import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any

from backend import database as db
from backend.config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

logger = logging.getLogger(__name__)


def send_signal_email(
    symbol: str,
    analysis: dict[str, Any],
    indicators: dict[str, Any],
    signal_type: str = "ai_signal",
) -> bool:
    if not db.get_setting("notify_enabled", True):
        return False
    if db.notification_sent_today(symbol, signal_type):
        return False
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.warning("Gmail 未設定，略過通知")
        return False
    subject = f"[模擬交易] {symbol} — {analysis.get('direction', 'hold')}"
    body = (
        f"股票：{symbol}\n"
        f"建議：{analysis.get('direction')}\n"
        f"信心：{analysis.get('confidence')}\n"
        f"理由：{analysis.get('reason')}\n\n"
        f"RSI: {indicators.get('rsi')}  MA5: {indicators.get('ma5')}  MA20: {indicators.get('ma20')}\n"
        f"MACD柱: {indicators.get('macd_hist')}  量比: {indicators.get('volume_ratio')}\n\n"
        f"{analysis.get('disclaimer', '')}"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, [GMAIL_ADDRESS], msg.as_string())
        db.mark_notification_sent(symbol, signal_type)
        return True
    except Exception as e:
        logger.error("Gmail 寄信失敗: %s", e)
        return False
