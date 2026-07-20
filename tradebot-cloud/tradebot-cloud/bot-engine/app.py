"""
Flask Web Application - Binance Futures Trading Bot UI
BOT ENGINE — No authentication (handled by parent SaaS app)

Yeh bot engine SaaS app ke through spawn hota hai. Login/license
parent SaaS app handle karta hai. Yeh sirf trading bot hai.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, Response, session
from flask_socketio import SocketIO

from bot.engine import BotEngine

# ---------- Setup ----------

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("app")

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))
app.config["SECRET_KEY"] = "bot-engine-secret"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_timeout=60,
    ping_interval=25,
    logger=False,
    engineio_logger=False,
)

# ---------- Default config ----------

DEFAULT_CONFIG = {
    "api_key": "",
    "api_secret": "",
    "api_passphrase": "",
    "exchange": "binance",
    "testnet": True,
    "symbol": "BTCUSDT",
    "symbols_list": ["BTCUSDT"],
    "timeframe": "5m",
    "leverage": 10,
    "amount_mode": "fixed",
    "amount": 100,
    "amount_pct": 10,
    "stop_loss_pct": 2,
    "take_profit_pct": 6,
    "mode": "both",
    "auto_start": False,
    "telegram_enabled": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "email_enabled": False,
    "email_smtp_server": "smtp.gmail.com",
    "email_smtp_port": 587,
    "email_sender": "",
    "email_password": "",
    "email_receiver": "",
    "whatsapp_enabled": False,
    "whatsapp_phone": "",
    "whatsapp_apikey": "",
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return {**DEFAULT_CONFIG, **cfg}
        except Exception as e:
            logger.error("Failed to load config: %s", e)
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


CONFIG = load_config()
ENGINE = BotEngine(socketio, CONFIG)


# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("dashboard.html", config=CONFIG)


@app.route("/favicon.ico")
def favicon():
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63000100000005000100"
        "0d0a2db40000000049454e44ae426082"
    )
    return Response(png_bytes, mimetype="image/png")


@app.route("/api/config", methods=["GET"])
def get_config():
    safe = {**CONFIG}
    if safe.get("api_key"):
        safe["api_key_masked"] = safe["api_key"][:4] + "***" + safe["api_key"][-4:]
    if safe.get("api_secret"):
        safe["api_secret_masked"] = "***"
    safe["api_key"] = safe.get("api_key", "")
    safe["api_secret"] = safe.get("api_secret", "")
    return jsonify(safe)


@app.route("/api/config", methods=["POST"])
def update_config():
    global CONFIG
    data = request.get_json(force=True)

    for k in ["exchange", "api_passphrase", "symbol", "symbols_list", "timeframe",
              "leverage", "amount", "amount_mode", "amount_pct",
              "stop_loss_pct", "take_profit_pct", "mode", "testnet", "auto_start",
              "telegram_enabled", "telegram_bot_token", "telegram_chat_id",
              "email_enabled", "email_smtp_server", "email_smtp_port",
              "email_sender", "email_password", "email_receiver",
              "whatsapp_enabled", "whatsapp_phone", "whatsapp_apikey"]:
        if k in data:
            CONFIG[k] = data[k]

    if data.get("api_key"):
        CONFIG["api_key"] = data["api_key"]
    if data.get("api_secret"):
        CONFIG["api_secret"] = data["api_secret"]

    CONFIG["exchange"] = (CONFIG.get("exchange") or "binance").lower()
    if CONFIG["exchange"] not in ("binance", "weex"):
        CONFIG["exchange"] = "binance"
    max_lev = 500 if CONFIG["exchange"] == "weex" else 125
    CONFIG["leverage"] = max(1, min(max_lev, int(CONFIG["leverage"])))
    CONFIG["amount"] = max(1, float(CONFIG["amount"]))
    CONFIG["amount_pct"] = max(1, min(100, float(CONFIG["amount_pct"])))
    CONFIG["stop_loss_pct"] = max(0.5, min(50, float(CONFIG.get("stop_loss_pct", 2))))
    CONFIG["take_profit_pct"] = CONFIG["stop_loss_pct"] * 3
    CONFIG["testnet"] = bool(CONFIG["testnet"])
    CONFIG["telegram_enabled"] = bool(CONFIG.get("telegram_enabled"))
    CONFIG["email_enabled"] = bool(CONFIG.get("email_enabled"))
    CONFIG["whatsapp_enabled"] = bool(CONFIG.get("whatsapp_enabled"))
    CONFIG["email_smtp_port"] = int(CONFIG.get("email_smtp_port", 587))

    if isinstance(CONFIG.get("symbols_list"), str):
        CONFIG["symbols_list"] = [s.strip().upper() for s in CONFIG["symbols_list"].split(",") if s.strip()]
    elif isinstance(CONFIG.get("symbols_list"), list):
        CONFIG["symbols_list"] = [str(s).strip().upper() for s in CONFIG["symbols_list"] if str(s).strip()]
    if CONFIG["symbols_list"]:
        CONFIG["symbol"] = CONFIG["symbols_list"][0]

    save_config(CONFIG)

    # Auto-start monitor
    try:
        ENGINE.start_monitor(CONFIG)
    except Exception as e:
        logger.error(f"Monitor auto-start failed: {e}")

    safe_keys = ("api_secret", "email_password", "telegram_bot_token", "whatsapp_apikey")
    return jsonify({"success": True, "config": {k: v for k, v in CONFIG.items() if k not in safe_keys}})


@app.route("/api/test_notification", methods=["POST"])
def test_notification():
    try:
        ENGINE.notifier.update_config(CONFIG)
        results = ENGINE.notifier.send("Test Notification",
            "Yeh bot se test notification hai. Agar yeh aapko mil raha hai, toh settings sahi hain!")
        summary_parts = []
        any_enabled = False
        any_success = False
        for channel in ("telegram", "email", "whatsapp"):
            if CONFIG.get(f"{channel}_enabled"):
                any_enabled = True
                r = results.get(channel)
                if r is None:
                    summary_parts.append(f"{channel}: still sending...")
                elif r.get("success"):
                    summary_parts.append(f"{channel}: ✅ sent")
                    any_success = True
                else:
                    summary_parts.append(f"{channel}: ❌ {r.get('error', 'unknown')}")
        if not any_enabled:
            return jsonify({"success": False, "error": "Koi notification channel enabled nahi hai."})
        return jsonify({"success": any_success, "message": " | ".join(summary_parts), "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/start", methods=["POST"])
def start_bot():
    try:
        if not CONFIG.get("api_key") or not CONFIG.get("api_secret"):
            return jsonify({"success": False, "error": "API key aur secret pehle set karo"})
        if CONFIG.get("exchange") == "weex" and not CONFIG.get("api_passphrase"):
            return jsonify({"success": False, "error": "WEEX ke liye Passphrase bhi chahiye"})
        if not CONFIG.get("symbols_list"):
            return jsonify({"success": False, "error": "Kam az kam ek symbol add karo"})
        result = ENGINE.start(CONFIG)
        return jsonify(result)
    except Exception as e:
        logger.exception("START BOT CRASHED:")
        return jsonify({"success": False, "error": f"Bot start error: {str(e)}"})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    result = ENGINE.stop()
    return jsonify(result)


@app.route("/api/force_stop", methods=["POST"])
def force_stop_bot():
    result = ENGINE.force_stop()
    return jsonify(result)


@app.route("/api/active_symbol", methods=["POST"])
def set_active_symbol():
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"success": False, "error": "Symbol required"})
    ENGINE.set_active_symbol(symbol)
    return jsonify({"success": True, "active_symbol": symbol})


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify(ENGINE.status())


@app.route("/api/close", methods=["POST"])
def close_position():
    if not ENGINE.trader:
        return jsonify({"success": False, "error": "Bot not connected"})
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol") or CONFIG.get("symbol", "BTCUSDT")
    result = ENGINE.trader.close_position(symbol)
    socketio.emit("log", {"level": "info", "msg": f"Manual close requested for {symbol}: {result}"})
    return jsonify(result)


@app.route("/api/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol", CONFIG.get("symbol", "BTCUSDT"))
    if not ENGINE.trader:
        return jsonify({"success": False, "error": "Bot not connected"})
    try:
        price = ENGINE.trader.get_mark_price(symbol)
        return jsonify({"success": True, "symbol": symbol, "price": price})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/symbols", methods=["GET"])
def get_all_symbols():
    """Fetch ALL USDT perpetual symbols from the SELECTED exchange."""
    exchange = (CONFIG.get("exchange") or "binance").lower()
    testnet = CONFIG.get("testnet", True)
    import requests as _req

    if exchange == "weex":
        try:
            resp = _req.get(
                "https://api-contract.weex.com/capi/v3/market/apiTradingSymbols",
                timeout=10,
            )
            data = resp.json()
            all_symbols = []
            if isinstance(data, list):
                for sym in data:
                    if isinstance(sym, str) and sym.upper().endswith("USDT"):
                        all_symbols.append(sym.upper())
            all_symbols = sorted(set(all_symbols))

            if testnet:
                symbols = [s for s in all_symbols if s.endswith("SUSDT")]
                mode_label = "demo"
            else:
                symbols = [s for s in all_symbols
                           if s.endswith("USDT") and not s.endswith("SUSDT")]
                mode_label = "live"

            if symbols:
                return jsonify({"success": True, "symbols": symbols, "count": len(symbols),
                                "exchange": "weex", "mode": mode_label})
        except Exception as e:
            logger.error(f"Failed to fetch WEEX symbols: {e}")
        if testnet:
            fallback = ["BTCSUSDT", "ETHSUSDT", "BNBSUSDT", "SOLSUSDT", "XRPSUSDT"]
        else:
            fallback = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
        return jsonify({"success": True, "symbols": fallback, "count": len(fallback),
                        "exchange": "weex", "mode": "demo" if testnet else "live"})

    try:
        resp = _req.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=10)
        data = resp.json()
        symbols = []
        for s in data.get("symbols", []):
            if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL":
                if s.get("status") == "TRADING":
                    symbols.append(s.get("symbol"))
        symbols.sort()
        if symbols:
            return jsonify({"success": True, "symbols": symbols, "count": len(symbols),
                            "exchange": "binance"})
    except Exception as e:
        logger.error(f"Failed to fetch Binance symbols: {e}")
    return jsonify({"success": True, "symbols": [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    ], "count": 10, "exchange": "binance"})


@app.route("/api/test_chart", methods=["GET"])
def test_chart():
    symbol = request.args.get("symbol", CONFIG.get("symbol", "BTCUSDT"))
    if not ENGINE.trader:
        return jsonify({"success": False, "error": "Bot not running"})
    try:
        df = ENGINE.trader.get_klines(symbol, interval=CONFIG.get("timeframe", "5m"), limit=5)
        if df is None or len(df) == 0:
            return jsonify({"success": False, "error": "No klines data", "rows": 0})
        candles = []
        for ts, row in df.iterrows():
            candles.append({"time": int(ts.timestamp()), "open": float(row["open"]),
                "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])})
        return jsonify({"success": True, "symbol": symbol, "rows": len(df), "candles": candles})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/preview", methods=["POST"])
def start_preview():
    try:
        result = ENGINE.start_monitor(CONFIG)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/test_connection", methods=["POST"])
def test_connection():
    try:
        from bot.engine import get_trader
        trader = get_trader(CONFIG)
        result = trader.test_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/balance", methods=["GET"])
def get_balance():
    trader = ENGINE.trader or ENGINE.monitor_trader
    if not trader:
        return jsonify({"success": False, "error": "Bot not connected"})
    try:
        bal = trader.get_balance()
        return jsonify({"success": True, "balance": bal,
                        "exchange": CONFIG.get("exchange", "binance"),
                        "testnet": CONFIG.get("testnet", True)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ---------- SocketIO ----------

@socketio.on("connect")
def on_connect():
    socketio.emit("log", {"level": "info", "msg": "UI connected to bot"})
    socketio.emit("status", ENGINE.status())

@socketio.on("disconnect")
def on_disconnect():
    logger.info("UI disconnected")


# ---------- Entry point ----------

def _crash_handler(exc_type, exc_value, exc_tb):
    import traceback
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.error("FATAL ERROR:\n%s", error_msg)
    try:
        with open("crash.log", "w", encoding="utf-8") as f:
            f.write(f"Crash Report\nTime: {datetime.now().isoformat()}\n\n{error_msg}")
    except Exception:
        pass
    sys.exit(1)


if __name__ == "__main__":
    sys.excepthook = _crash_handler
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info("="*60)
    logger.info(" Bot Engine - Starting (port %d)", port)
    logger.info("="*60)
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True, use_reloader=False)
