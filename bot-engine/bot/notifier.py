"""
Notification Module
Sends alerts via Telegram, Email, and WhatsApp when:
- Signal fires (EMA55 cross detected)
- Trade opens (LONG/SHORT)
- TP hits (position closed)
- SL hits (stop loss triggered)
- Bot starts/stops

All send methods run in background threads so they never block the bot.
"""
from __future__ import annotations

import logging
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class Notifier:
    """Multi-channel notifier: Telegram, Email, WhatsApp. Non-blocking."""

    def __init__(self, config: dict):
        self.config = config or {}
        self._apply_config(self.config)
        # Track last signal per symbol to avoid duplicate signal notifications
        self._last_signal_notified: dict = {}

    def _apply_config(self, config: dict):
        """Apply config to internal state."""
        # Telegram
        self.tg_enabled = bool(config.get("telegram_enabled"))
        self.tg_bot_token = (config.get("telegram_bot_token") or "").strip()
        self.tg_chat_id = (config.get("telegram_chat_id") or "").strip()
        # Email
        self.email_enabled = bool(config.get("email_enabled"))
        self.email_smtp_server = (config.get("email_smtp_server") or "smtp.gmail.com").strip()
        try:
            self.email_smtp_port = int(config.get("email_smtp_port", 587))
        except (ValueError, TypeError):
            self.email_smtp_port = 587
        self.email_sender = (config.get("email_sender") or "").strip()
        self.email_password = (config.get("email_password") or "").strip()
        self.email_receiver = (config.get("email_receiver") or "").strip()
        # WhatsApp
        self.whatsapp_enabled = bool(config.get("whatsapp_enabled"))
        self.whatsapp_phone = (config.get("whatsapp_phone") or "").strip()
        self.whatsapp_apikey = (config.get("whatsapp_apikey") or "").strip()

    def update_config(self, config: dict):
        """Update notifier config at runtime."""
        self.config = config or {}
        self._apply_config(self.config)

    def _validate_telegram(self) -> Optional[str]:
        """Validate Telegram config. Returns error message or None if OK."""
        if not self.tg_bot_token:
            return "Bot Token khali hai"
        if ":" not in self.tg_bot_token:
            return "Bot Token ka format galat hai (colon ':' missing). Example: 123456789:ABCdefGHIjkl"
        parts = self.tg_bot_token.split(":", 1)
        if not parts[0].isdigit() or len(parts[0]) < 5:
            return "Bot Token ka numeric part galat hai"
        if len(parts[1]) < 20:
            return "Bot Token ka secret part bahut chhota hai (likely incomplete)"
        if not self.tg_chat_id:
            return "Chat ID khali hai"
        if not self.tg_chat_id.lstrip("-").isdigit():
            return "Chat ID sirf numbers hona chahiye (aur optional leading -)"
        return None

    def _validate_email(self) -> Optional[str]:
        """Validate Email config."""
        if not self.email_sender:
            return "Sender Email khali hai"
        if "@" not in self.email_sender:
            return "Sender Email ka format galat hai"
        if not self.email_password:
            return "App Password khali hai"
        if not self.email_receiver:
            return "Receiver Email khali hai"
        if "@" not in self.email_receiver:
            return "Receiver Email ka format galat hai"
        return None

    def _validate_whatsapp(self) -> Optional[str]:
        """Validate WhatsApp config."""
        if not self.whatsapp_phone:
            return "Phone number khali hai"
        if not self.whatsapp_phone.isdigit():
            return "Phone number sirf numbers hona chahiye (country code ke saath, e.g. 923001234567)"
        if len(self.whatsapp_phone) < 10:
            return "Phone number bahut chhota hai"
        if not self.whatsapp_apikey:
            return "API Key khali hai"
        return None

    def send(self, title: str, message: str) -> dict:
        """Send notification via all enabled channels. Non-blocking.
        Returns dict of results per channel."""
        full_msg = f"🤖 *{title}*\n\n{message}"
        plain_msg = f"{title}\n\n{message}"
        results = {"telegram": None, "email": None, "whatsapp": None}

        threads = []

        if self.tg_enabled:
            err = self._validate_telegram()
            if err:
                results["telegram"] = {"success": False, "error": err}
                logger.error("Telegram validation failed: %s", err)
            else:
                t = threading.Thread(target=self._send_telegram_sync,
                                     args=(full_msg, results), daemon=True)
                t.start()
                threads.append(t)

        if self.email_enabled:
            err = self._validate_email()
            if err:
                results["email"] = {"success": False, "error": err}
                logger.error("Email validation failed: %s", err)
            else:
                t = threading.Thread(target=self._send_email_sync,
                                     args=(title, plain_msg, results), daemon=True)
                t.start()
                threads.append(t)

        if self.whatsapp_enabled:
            err = self._validate_whatsapp()
            if err:
                results["whatsapp"] = {"success": False, "error": err}
                logger.error("WhatsApp validation failed: %s", err)
            else:
                t = threading.Thread(target=self._send_whatsapp_sync,
                                     args=(plain_msg, results), daemon=True)
                t.start()
                threads.append(t)

        # Wait for all to finish (max 20 seconds)
        for t in threads:
            t.join(timeout=20)
        return results

    # ---------- Telegram ----------

    def _send_telegram_sync(self, message: str, results: dict):
        """Send message via Telegram Bot API (blocking, runs in thread)."""
        try:
            url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
            payload = {
                "chat_id": self.tg_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    logger.info("Telegram notification sent to chat_id=%s", self.tg_chat_id)
                    results["telegram"] = {"success": True}
                    return
                else:
                    err = data.get("description", "Unknown error")
                    logger.error("Telegram API error: %s", err)
                    results["telegram"] = {"success": False, "error": err}
                    return
            else:
                try:
                    data = resp.json()
                    err = data.get("description", f"HTTP {resp.status_code}")
                except Exception:
                    err = f"HTTP {resp.status_code} - {resp.text[:200]}"
                logger.error("Telegram send failed: %s", err)
                results["telegram"] = {"success": False, "error": err}
        except requests.exceptions.Timeout:
            err = "Timeout - internet slow hai ya Telegram block hai"
            logger.error("Telegram timeout: %s", err)
            results["telegram"] = {"success": False, "error": err}
        except requests.exceptions.ConnectionError as e:
            err = f"Connection error - internet check karein: {e}"
            logger.error("Telegram connection error: %s", err)
            results["telegram"] = {"success": False, "error": err}
        except Exception as e:
            logger.error("Telegram send error: %s", e)
            results["telegram"] = {"success": False, "error": str(e)}

    # ---------- Email ----------

    def _send_email_sync(self, subject: str, body: str, results: dict):
        """Send email via SMTP (blocking, runs in thread)."""
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.email_sender
            msg["To"] = self.email_receiver
            msg["Subject"] = f"[Trading Bot] {subject}"
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.email_smtp_server, self.email_smtp_port, timeout=15) as server:
                server.starttls()
                server.login(self.email_sender, self.email_password)
                server.sendmail(self.email_sender, self.email_receiver, msg.as_string())
            logger.info("Email sent to %s", self.email_receiver)
            results["email"] = {"success": True}
        except smtplib.SMTPAuthenticationError as e:
            err = f"Auth fail - App Password galat hai: {e}"
            logger.error("Email auth error: %s", err)
            results["email"] = {"success": False, "error": err}
        except smtplib.SMTPException as e:
            err = f"SMTP error: {e}"
            logger.error("Email SMTP error: %s", err)
            results["email"] = {"success": False, "error": err}
        except Exception as e:
            err = f"Email error: {e}"
            logger.error("Email send error: %s", err)
            results["email"] = {"success": False, "error": err}

    # ---------- WhatsApp (CallMeBot) ----------

    def _send_whatsapp_sync(self, message: str, results: dict):
        """Send WhatsApp message via CallMeBot API (blocking, runs in thread)."""
        try:
            url = "https://api.callmebot.com/whatsapp.php"
            params = {
                "phone": self.whatsapp_phone,
                "text": message,
                "apikey": self.whatsapp_apikey,
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200 and ("Message queued" in resp.text or "queued" in resp.text.lower()):
                logger.info("WhatsApp sent to %s", self.whatsapp_phone)
                results["whatsapp"] = {"success": True}
            else:
                err = f"HTTP {resp.status_code} - {resp.text[:300]}"
                logger.error("WhatsApp failed: %s", err)
                results["whatsapp"] = {"success": False, "error": err}
        except requests.exceptions.Timeout:
            err = "Timeout - internet slow hai"
            logger.error("WhatsApp timeout: %s", err)
            results["whatsapp"] = {"success": False, "error": err}
        except Exception as e:
            err = f"WhatsApp error: {e}"
            logger.error("WhatsApp send error: %s", err)
            results["whatsapp"] = {"success": False, "error": err}

    # ---------- Convenience methods ----------

    def notify_signal(self, symbol: str, signal: str, reason: str, emas: dict):
        """Send signal notification. Avoids duplicate per symbol."""
        key = f"{symbol}:{signal}"
        if self._last_signal_notified.get(symbol) == key:
            return  # already notified this signal
        self._last_signal_notified[symbol] = key
        title = f"Signal: {signal} on {symbol}"
        msg = (
            f"Symbol: {symbol}\n"
            f"Signal: {signal}\n"
            f"Reason: {reason}\n\n"
            f"EMA 8:  {emas.get('ema_8', '?')}\n"
            f"EMA 13: {emas.get('ema_13', '?')}\n"
            f"EMA 21: {emas.get('ema_21', '?')}\n"
            f"EMA 55: {emas.get('ema_55', '?')}\n\n"
            f"⚡ EMA55 line abhi cross hui hai"
        )
        return self.send(title, msg)

    def notify_trade_open(self, symbol: str, side: str, qty: float, price: float, emas: dict):
        """Send trade open notification."""
        title = f"Trade Opened: {side} {symbol}"
        emoji = "🟢" if side == "LONG" else "🔴"
        msg = (
            f"{emoji} {side} position opened\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {side}\n"
            f"Quantity: {qty}\n"
            f"Entry Price: ${price:.4f}\n\n"
            f"EMA 8:  {emas.get('ema_8', '?')}\n"
            f"EMA 13: {emas.get('ema_13', '?')}\n"
            f"EMA 21: {emas.get('ema_21', '?')}\n"
            f"EMA 55: {emas.get('ema_55', '?')}"
        )
        return self.send(title, msg)

    def notify_tp(self, symbol: str, side: str, entry_price: float, close_price: float,
                  pnl_pct: float, emas: dict):
        """Send TP hit notification."""
        title = f"TP Hit: {symbol} closed"
        msg = (
            f"✅ Take Profit hit!\n\n"
            f"Symbol: {symbol}\n"
            f"Closed: {side}\n"
            f"Entry: ${entry_price:.4f}\n"
            f"Exit:  ${close_price:.4f}\n"
            f"PnL: {pnl_pct:+.2f}%\n\n"
            f"EMA 55 line neeche aagai hai"
        )
        return self.send(title, msg)

    def notify_sl(self, symbol: str, side: str, entry_price: float, close_price: float,
                  pnl_pct: float):
        """Send SL hit notification."""
        title = f"SL Hit: {symbol} closed"
        msg = (
            f"🛑 Stop Loss hit!\n\n"
            f"Symbol: {symbol}\n"
            f"Closed: {side}\n"
            f"Entry: ${entry_price:.4f}\n"
            f"Exit:  ${close_price:.4f}\n"
            f"PnL: {pnl_pct:+.2f}%"
        )
        return self.send(title, msg)

    def notify_bot_start(self, config: dict):
        """Send bot start notification."""
        title = "Bot Started"
        exchange = config.get("exchange", "binance").upper()
        symbols = ",".join(config.get("symbols_list", []))
        msg = (
            f"Exchange: {exchange}\n"
            f"Symbols: {symbols}\n"
            f"Timeframe: {config.get('timeframe')}\n"
            f"Leverage: {config.get('leverage')}x\n"
            f"Mode: {config.get('mode')}\n"
            f"SL: {config.get('stop_loss_pct', 0)}%\n"
            f"TP: {config.get('take_profit_pct', 0)}% (or opposite-signal)\n"
            f"Environment: {'TESTNET' if config.get('testnet') else 'MAINNET'}"
        )
        return self.send(title, msg)

    def notify_bot_stop(self):
        """Send bot stop notification."""
        return self.send("Bot Stopped", "Bot ko user ne stop kar diya hai.")
