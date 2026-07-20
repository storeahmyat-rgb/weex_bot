"""
TradeBot SaaS — Webapp (Wrapper around Bot-Engine)
====================================================

Yeh webapp bot-engine ke charon taraf ek WRAPPER hai.
Bot-engine ko BILKUL MODIFY NAHI KIYA — woh original simple trading bot hai.

Architecture:
  Webapp (port 5000)
    ├── Login page (email + password)
    ├── License activation (admin ne di hoti hai)
    ├── Admin panel (license generate karo, users manage karo)
    └── Dashboard → bot-engine ko iframe/proxy karta hai

  Bot-Engine (port 5001+ — ek per user)
    ├── Original trading dashboard (UNCHANGED)
    ├── EMA 8,13,21,55 strategy (UNCHANGED)
    ├── 1:3 RR hardcoded (UNCHANGED)
    └── Sab trading logic (UNCHANGED)

Flow:
  1. User signup → login
  2. User license key enter kare (admin se mili)
  3. License valid → webapp user ka bot-engine spawn karta hai (port 5001+)
  4. Webapp dashboard mein bot-engine ka dashboard iframe mein dikhta hai
  5. User API keys enter kare, coins add kare, START dabaye
  6. Bot 24/7 chalega (server pe)

Bot-engine mein KOI MODIFICATION NAHI — yeh sirf wrapper hai.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import hashlib
import secrets
import subprocess
import time
import uuid
import shutil
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request, Response, session, redirect, url_for
from flask_socketio import SocketIO
import urllib.request
import urllib.error
import requests as req_lib
import threading

# ============================================================
# Setup
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
BOT_ENGINE_DIR = BASE_DIR / "bot-engine"
DB_FILE = BASE_DIR / "database.json"
LOG_DIR = BASE_DIR / "logs"
USER_CONFIGS_DIR = BASE_DIR / "user_configs"
LOG_DIR.mkdir(exist_ok=True)
USER_CONFIGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "saas.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("saas")

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET", "tradebot-saas-secret-change-me-32chars")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                    ping_timeout=60, ping_interval=25)

# ============================================================
# Configuration
# ============================================================

# Admin password — change via ADMIN_SECRET env var
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "AdminBot@2024!")

# Encryption key for API keys (must be 32+ chars)
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "tradebot-cloud-encryption-key-CHANGE-ME-32-chars")

# Port range for per-user bot-engine instances
PORT_START = 5001
PORT_END = 5999

logger.info("=" * 60)
logger.info(" TradeBot SaaS Webapp - Starting")
logger.info(f" Bot engine dir: {BOT_ENGINE_DIR}")
logger.info(f" Admin password: ***{ADMIN_SECRET[-3:]}")
logger.info("=" * 60)

# ============================================================
# Encryption (XOR + base64) — simple but effective for API keys
# ============================================================

def encrypt(plain_text: str) -> str:
    if not plain_text:
        return ""
    try:
        import base64
        key = ENCRYPTION_KEY.encode("utf-8")
        text = plain_text.encode("utf-8")
        result = bytes([text[i] ^ key[i % len(key)] for i in range(len(text))])
        return base64.b64encode(result).decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return ""

def decrypt(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        import base64
        key = ENCRYPTION_KEY.encode("utf-8")
        data = base64.b64decode(cipher_text.encode("utf-8"))
        result = bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])
        return result.decode("utf-8")
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return ""

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, hashed = stored.split("$")
        return hashlib.sha256((salt + password).encode()).hexdigest() == hashed
    except:
        return False

# ============================================================
# Database (JSON file)
# ============================================================

def load_db() -> dict:
    if DB_FILE.exists():
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"DB load failed: {e}")
    return {"users": {}, "licenses": {}, "bot_processes": {}}

def save_db(db: dict):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"DB save failed: {e}")

DB = load_db()

# ============================================================
# Auth helpers
# ============================================================

def is_logged_in() -> bool:
    return "user_id" in session

def is_admin() -> bool:
    user_id = session.get("user_id")
    if not user_id:
        return False
    user = DB["users"].get(user_id, {})
    return user.get("role") == "admin"

def current_user() -> Optional[dict]:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return DB["users"].get(user_id)

def check_subscription(user: dict) -> dict:
    """Check user's subscription status."""
    sub = user.get("subscription", {})
    if not sub:
        return {"active": False, "status": "none", "days_left": 0, "plan": "none"}

    expires_at = sub.get("expires_at")
    if not expires_at:
        return {"active": False, "status": "none", "days_left": 0, "plan": "none"}

    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", ""))
        now = datetime.utcnow()
        days_left = (expiry - now).days

        if days_left <= 0:
            return {"active": False, "status": "expired", "days_left": 0,
                    "plan": sub.get("plan", "trial"), "expires_at": expires_at}

        return {"active": True, "status": "active", "days_left": days_left,
                "plan": sub.get("plan", "trial"), "expires_at": expires_at}
    except:
        return {"active": False, "status": "error", "days_left": 0, "plan": "none"}

# ============================================================
# Bot-Engine Process Manager
# ============================================================

def find_free_port() -> int:
    """Find a free port for a new bot-engine instance."""
    used_ports = set()
    for proc_info in DB.get("bot_processes", {}).values():
        if proc_info.get("port"):
            used_ports.add(proc_info["port"])

    for port in range(PORT_START, PORT_END + 1):
        if port not in used_ports:
            return port
    raise RuntimeError("No free ports available")

def write_user_bot_config(user_id: str) -> str:
    """Write user's bot config to bot-engine's config.json.
    This is the ONLY file we touch in bot-engine dir — its config.json."""
    user = DB["users"].get(user_id, {})
    config = user.get("bot_config", {})

    # Decrypt API credentials
    api_key = decrypt(config.get("api_key_enc", ""))
    api_secret = decrypt(config.get("api_secret_enc", ""))
    api_passphrase = decrypt(config.get("api_passphrase_enc", ""))

    # Build config.json for bot-engine (matches bot-engine's expected format)
    bot_config = {
        "api_key": api_key,
        "api_secret": api_secret,
        "api_passphrase": api_passphrase,
        "exchange": config.get("exchange", "binance"),
        "testnet": config.get("testnet", True),
        "symbol": (config.get("symbols_list", ["BTCUSDT"]) or ["BTCUSDT"])[0],
        "symbols_list": config.get("symbols_list", ["BTCUSDT"]),
        "timeframe": config.get("timeframe", "5m"),
        "leverage": config.get("leverage", 10),
        "amount_mode": config.get("amount_mode", "fixed"),
        "amount": config.get("amount", 100),
        "amount_pct": config.get("amount_pct", 10),
        "stop_loss_pct": config.get("stop_loss_pct", 2),
        "take_profit_pct": config.get("take_profit_pct", 6),
        "mode": config.get("mode", "both"),
        "auto_start": False,
        "telegram_enabled": config.get("telegram_enabled", False),
        "telegram_bot_token": decrypt(config.get("telegram_bot_token_enc", "")),
        "telegram_chat_id": config.get("telegram_chat_id", ""),
        "email_enabled": config.get("email_enabled", False),
        "email_smtp_server": "smtp.gmail.com",
        "email_smtp_port": 587,
        "email_sender": config.get("email_sender", ""),
        "email_password": decrypt(config.get("email_password_enc", "")),
        "email_receiver": config.get("email_receiver", ""),
        "whatsapp_enabled": config.get("whatsapp_enabled", False),
        "whatsapp_phone": config.get("whatsapp_phone", ""),
        "whatsapp_apikey": decrypt(config.get("whatsapp_apikey_enc", "")),
    }

    # Write to bot-engine's config.json (this is THE config file bot-engine reads)
    config_path = BOT_ENGINE_DIR / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(bot_config, f, indent=2, ensure_ascii=False)

    return str(config_path)

def start_user_bot(user_id: str, write_config: bool = True) -> dict:
    """Start a user's bot-engine instance.
    If write_config=True, writes SaaS DB config to bot-engine's config.json first.
    If write_config=False, starts bot-engine with its existing config.json (for dashboard setup)."""
    user = DB["users"].get(user_id)
    if not user:
        return {"success": False, "error": "User not found"}

    # Check if already running
    existing = DB.get("bot_processes", {}).get(user_id)
    if existing and existing.get("port"):
        if _is_port_open(existing["port"]):
            return {"success": True, "port": existing["port"], "message": "Bot already running"}
        else:
            DB.get("bot_processes", {}).pop(user_id, None)
            save_db(DB)

    if write_config:
        # Validate config from SaaS DB
        config = user.get("bot_config", {})
        if not config.get("api_key_enc"):
            return {"success": False, "error": "API key not set. Please save settings first."}
        if config.get("exchange") == "weex" and not config.get("api_passphrase_enc"):
            return {"success": False, "error": "WEEX passphrase required"}
        if not config.get("symbols_list"):
            return {"success": False, "error": "Please add at least one coin"}

    # Find free port
    try:
        port = find_free_port()
    except Exception as e:
        return {"success": False, "error": str(e)}

    if write_config:
        # Write user config to bot-engine's config.json
        try:
            write_user_bot_config(user_id)
        except Exception as e:
            return {"success": False, "error": f"Config write failed: {e}"}

    # Spawn bot-engine process
    try:
        import platform
        python_cmd = "python" if platform.system() == "Windows" else "python3"
        
        # Create log file
        log_file = LOG_DIR / f"bot_{user_id}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        proc = subprocess.Popen(
            [python_cmd, "app.py"],
            cwd=str(BOT_ENGINE_DIR),
            env={**os.environ, "PORT": str(port), "HOST": "127.0.0.1"},
            stdout=open(log_file, "w"),
            stderr=subprocess.STDOUT,
            preexec_fn=None if platform.system() == "Windows" else lambda: os.setsid(),
        )

        DB.setdefault("bot_processes", {})[user_id] = {
            "pid": proc.pid,
            "port": port,
            "started_at": datetime.utcnow().isoformat() + "Z",
        }
        save_db(DB)

        logger.info(f"Started bot-engine for user {user_id}: PID={proc.pid}, port={port}")

        # Use longer timeout on Railway (or any non-Windows environment)
        is_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT_NAME"))
        max_wait = 30 if is_railway else 15
        port_timeout = 5.0 if is_railway else 2.0
        
        for i in range(max_wait):
            time.sleep(1)
            
            # Check if process is still alive
            if not _check_bot_process_alive(proc.pid):
                # Process died, read the log to see what went wrong
                try:
                    with open(log_file, "r") as f:
                        last_lines = f.readlines()[-20:]  # Last 20 lines
                    error_msg = "".join(last_lines)
                    logger.error(f"Bot process {proc.pid} died. Last logs:\n{error_msg}")
                except:
                    pass
                DB.get("bot_processes", {}).pop(user_id, None)
                save_db(DB)
                return {"success": False, "error": "Bot process crashed on startup. Check logs."}
            
            # Check if port is open
            if _is_port_open(port, timeout=port_timeout):
                logger.info(f"Bot-engine ready on port {port} after {i+1}s")
                return {"success": True, "port": port, "pid": proc.pid}
        
        # Timeout - bot didn't come up but process is still alive
        logger.warning(f"Bot-engine port {port} not ready after {max_wait}s, but process alive (PID={proc.pid})")
        # Return success anyway - user might need to wait a bit longer
        return {"success": True, "port": port, "pid": proc.pid, "warning": "Bot starting, please wait..."}
        
    except Exception as e:
        logger.error(f"Failed to start bot for {user_id}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

def stop_user_bot(user_id: str) -> dict:
    """Stop a user's bot-engine instance."""
    proc_info = DB.get("bot_processes", {}).get(user_id)
    if not proc_info or not proc_info.get("pid"):
        return {"success": True, "message": "Bot not running"}

    pid = proc_info["pid"]
    port = proc_info.get("port")

    # Kill by PID (best effort)
    try:
        import platform
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(pid, signal.SIGKILL)
            except:
                pass
    except Exception as e:
        logger.error(f"Failed to kill bot PID {pid}: {e}")

    # Also kill by port (catch zombie processes on Windows)
    if port:
        try:
            import platform
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if parts:
                            zap_pid = parts[-1]
                            subprocess.run(["taskkill", "/F", "/PID", zap_pid], capture_output=True, timeout=5)
            else:
                subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, timeout=5)
        except Exception as e:
            logger.error(f"Failed to kill by port {port}: {e}")

    DB.get("bot_processes", {}).pop(user_id, None)
    save_db(DB)
    logger.info(f"Stopped bot-engine for user {user_id}")
    return {"success": True, "message": "Bot stopped"}

def _is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Check if a port is accepting TCP connections (works on all OS including Windows)."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False

def _check_bot_process_alive(pid: int) -> bool:
    """Check if a process is still alive (cross-platform)."""
    import platform
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.kernel32.GetExitCodeProcess(int(pid), ctypes.byref(ctypes.c_ulong())) != 0
        else:
            os.kill(pid, 0)  # Signal 0 doesn't kill, just checks if process exists
            return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def get_bot_status(user_id: str) -> dict:
    """Get bot status for a user. Uses port check instead of os.kill (Windows safe)."""
    proc_info = DB.get("bot_processes", {}).get(user_id)
    if not proc_info or not proc_info.get("port"):
        return {"running": False}

    port = proc_info["port"]
    pid = proc_info.get("pid")
    
    # Check if process is still alive first
    if pid and not _check_bot_process_alive(pid):
        logger.warning(f"get_bot_status({user_id[:8]}): Process {pid} is dead, removing entry")
        DB.get("bot_processes", {}).pop(user_id, None)
        save_db(DB)
        return {"running": False}

    # Use longer timeout on Railway
    is_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT_NAME"))
    port_timeout = 5.0 if is_railway else 2.0
    
    if _is_port_open(port, timeout=port_timeout):
        return {
            "running": True,
            "port": port,
            "pid": pid,
            "started_at": proc_info.get("started_at"),
        }

    started_at = proc_info.get("started_at", "")
    try:
        from datetime import datetime, timezone
        started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - started_dt).total_seconds()
    except:
        age = 999

    # On Railway, give bot more time to start (up to 60 seconds)
    grace_period = 60 if is_railway else 15
    
    if age < grace_period:
        logger.debug(f"get_bot_status({user_id[:8]}): port {port} not ready yet, bot age {age:.0f}s, grace period {grace_period}s")
        return {
            "running": True,
            "port": port,
            "pid": pid,
            "started_at": proc_info.get("started_at"),
            "starting": True,
        }

    logger.warning(f"get_bot_status({user_id[:8]}): port {port} not open after {age:.0f}s (grace {grace_period}s), clearing entry")
    DB.get("bot_processes", {}).pop(user_id, None)
    save_db(DB)
    return {"running": False}

def proxy_to_bot(user_id: str, method: str, path: str, body=None) -> dict:
    """Proxy a request to user's bot-engine instance."""
    status = get_bot_status(user_id)
    if not status["running"] or not status.get("port"):
        return {"success": False, "error": "Bot is not running"}

    try:
        url = f"http://127.0.0.1:{status['port']}{path}"
        data = json.dumps(body).encode("utf-8") if body and method != "GET" else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        
        # Use longer timeout on Railway
        is_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT_NAME"))
        proxy_timeout = 30.0 if is_railway else 10.0
        
        with urllib.request.urlopen(req, timeout=proxy_timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except:
            return {"success": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        logger.error(f"Proxy error for user {user_id}: {e}")
        return {"success": False, "error": str(e)}

# ============================================================
# Routes — Pages
# ============================================================

@app.route("/")
def index():
    """Main page — login if not authenticated, dashboard if logged in."""
    if not is_logged_in():
        return render_template("saas_login.html")
    return render_template("saas_dashboard.html")

@app.route("/admin")
def admin_panel():
    """Admin panel."""
    if not is_admin():
        return render_template("saas_admin.html", admin_login_required=True)
    return render_template("saas_admin.html", admin_login_required=False)

@app.route("/favicon.ico")
def favicon():
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63000100000005000100"
        "0d0a2db40000000049454e44ae426082"
    )
    return Response(png_bytes, mimetype="image/png")

# ============================================================
# Auth API
# ============================================================

@app.route("/api/auth/signup", methods=["POST"])
def api_signup():
    """User signup with email + password."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")
    name = (data.get("name") or "").strip()

    if not email or not password:
        return jsonify({"success": False, "error": "Email aur password zaroori hai"})
    if len(password) < 6:
        return jsonify({"success": False, "error": "Password kam az kam 6 characters ka hona chahiye"})
    if "@" not in email or "." not in email:
        return jsonify({"success": False, "error": "Sahi email address daalein"})

    # Check if exists
    for u in DB["users"].values():
        if u.get("email") == email:
            return jsonify({"success": False, "error": "Yeh email pehle se registered hai"})

    # First user becomes admin
    role = "admin" if len(DB["users"]) == 0 else "user"

    user_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + "Z"

    user = {
        "id": user_id,
        "email": email,
        "name": name or email.split("@")[0],
        "password_hash": hash_password(password),
        "role": role,
        "banned": False,
        "created_at": now,
        "subscription": {
            "plan": "none",
            "status": "inactive",  # user must enter license key
            "started_at": now,
            "expires_at": now,
        },
        "license_key": None,
        "bot_config": {
            "exchange": "binance",
            "testnet": True,
            "symbols_list": [],
            "timeframe": "5m",
            "leverage": 10,
            "amount_mode": "fixed",
            "amount": 100,
            "amount_pct": 10,
            "stop_loss_pct": 2,
            "take_profit_pct": 6,
            "mode": "both",
            "api_key_enc": "",
            "api_secret_enc": "",
            "api_passphrase_enc": "",
        },
    }
    DB["users"][user_id] = user
    save_db(DB)

    session["user_id"] = user_id
    session.permanent = True

    logger.info(f"New user signup: {email} (role={role})")

    return jsonify({
        "success": True,
        "user": {"id": user_id, "email": email, "name": user["name"], "role": role},
        "subscription": user["subscription"],
        "message": "Account created! Ab license key enter karein." if role == "user" else "Welcome Admin!",
    })

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """User login with email + password."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"success": False, "error": "Email aur password daalein"})

    user = None
    for u in DB["users"].values():
        if u.get("email") == email:
            user = u
            break

    if not user or not verify_password(password, user.get("password_hash", "")):
        return jsonify({"success": False, "error": "Email ya password galat hai"})

    if user.get("banned"):
        return jsonify({"success": False, "error": "Account suspended. Admin se contact karein."})

    session["user_id"] = user["id"]
    session.permanent = True

    logger.info(f"User login: {email}")

    return jsonify({
        "success": True,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]},
        "subscription": user.get("subscription", {}),
    })

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.pop("user_id", None)
    return jsonify({"success": True})

@app.route("/api/auth/me", methods=["GET"])
def api_me():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"})

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"})

    sub_status = check_subscription(user)
    bot_status = get_bot_status(user["id"])

    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
        },
        "subscription": sub_status,
        "license_key": user.get("license_key"),
        "bot_config": {
            **user.get("bot_config", {}),
            "api_key_enc": None,
            "api_secret_enc": None,
            "api_passphrase_enc": None,
            "has_api_key": bool(user.get("bot_config", {}).get("api_key_enc")),
            "has_passphrase": bool(user.get("bot_config", {}).get("api_passphrase_enc")),
        },
        "bot_running": bot_status.get("running", False),
        "bot_port": bot_status.get("port"),
    })

# ============================================================
# License API
# ============================================================

@app.route("/api/license/activate", methods=["POST"])
def api_license_activate():
    """User activates a license key."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip().upper()

    if not key:
        return jsonify({"success": False, "error": "License key daalein"})

    # Check license in DB
    lic = DB.get("licenses", {}).get(key)
    if not lic:
        return jsonify({"success": False, "error": "License key invalid hai"})

    if lic.get("revoked"):
        return jsonify({"success": False, "error": "Yeh license revoke kar diya gaya hai. Admin se contact karein."})

    if lic.get("used_by") and lic["used_by"] != user["id"]:
        return jsonify({"success": False, "error": "Yeh license dusre user pe activate hai. Ek license sirf ek user pe chalta hai."})

    # Check expiry
    try:
        expiry = datetime.fromisoformat(lic["expires_at"].replace("Z", ""))
        if datetime.utcnow() > expiry:
            return jsonify({"success": False, "error": "License expire ho gaya. Admin se new license lein."})
    except:
        return jsonify({"success": False, "error": "License expiry check fail"})

    # Activate license for this user
    lic["used_by"] = user["id"]
    lic["activated_at"] = datetime.utcnow().isoformat() + "Z"
    lic["active"] = True

    # Update user subscription
    now = datetime.utcnow()
    user["subscription"] = {
        "plan": lic.get("plan", "basic"),
        "status": "active",
        "started_at": now.isoformat() + "Z",
        "expires_at": lic["expires_at"],
    }
    user["license_key"] = key

    save_db(DB)
    logger.info(f"License {key} activated for user {user['email']}")

    days_left = (expiry - now).days
    return jsonify({
        "success": True,
        "message": f"License activated! {days_left} days remaining.",
        "subscription": user["subscription"],
    })

# ============================================================
# Bot Config API
# ============================================================

@app.route("/api/bot/config", methods=["GET", "POST"])
def api_bot_config():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    if request.method == "GET":
        config = user.get("bot_config", {})
        return jsonify({
            "success": True,
            "config": {
                **config,
                "api_key_enc": None,
                "api_secret_enc": None,
                "api_passphrase_enc": None,
                "has_api_key": bool(config.get("api_key_enc")),
                "has_passphrase": bool(config.get("api_passphrase_enc")),
            }
        })

    # POST — save config
    data = request.get_json(force=True)
    config = user.setdefault("bot_config", {})

    if "exchange" in data:
        config["exchange"] = "weex" if data["exchange"] == "weex" else "binance"
    if "testnet" in data:
        config["testnet"] = bool(data["testnet"])
    if data.get("api_key") and str(data["api_key"]).strip():
        config["api_key_enc"] = encrypt(str(data["api_key"]).strip())
    if data.get("api_secret") and str(data["api_secret"]).strip():
        config["api_secret_enc"] = encrypt(str(data["api_secret"]).strip())
    if "api_passphrase" in data:
        if data["api_passphrase"] and str(data["api_passphrase"]).strip():
            config["api_passphrase_enc"] = encrypt(str(data["api_passphrase"]).strip())
        elif data["api_passphrase"] == "":
            config["api_passphrase_enc"] = ""
    if "symbols_list" in data:
        symbols = data["symbols_list"] if isinstance(data["symbols_list"], list) else []
        config["symbols_list"] = [str(s).upper().strip() for s in symbols if str(s).strip()]
    if "timeframe" in data:
        config["timeframe"] = data["timeframe"]
    if "leverage" in data:
        max_lev = 500 if config.get("exchange") == "weex" else 125
        config["leverage"] = max(1, min(max_lev, int(data["leverage"]) or 10))
    if "amount_mode" in data:
        config["amount_mode"] = "percent" if data["amount_mode"] == "percent" else "fixed"
    if "amount" in data:
        config["amount"] = max(1, float(data["amount"]) or 100)
    if "amount_pct" in data:
        config["amount_pct"] = max(1, min(100, float(data["amount_pct"]) or 10))
    if "stop_loss_pct" in data:
        sl = max(0.5, min(50, float(data["stop_loss_pct"]) or 2))
        config["stop_loss_pct"] = sl
        config["take_profit_pct"] = sl * 3  # 1:3 RR hardcoded
    if "mode" in data:
        config["mode"] = data["mode"] if data["mode"] in ("long", "short", "both") else "both"

    save_db(DB)
    return jsonify({
        "success": True,
        "config": {
            **config,
            "api_key_enc": None,
            "api_secret_enc": None,
            "api_passphrase_enc": None,
            "has_api_key": bool(config.get("api_key_enc")),
            "has_passphrase": bool(config.get("api_passphrase_enc")),
        }
    })

# ============================================================
# Bot Control API
# ============================================================

@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    sub = check_subscription(user)
    if not sub["active"]:
        return jsonify({"success": False, "error": "Subscription inactive/expired. License activate karein."}), 403

    result = start_user_bot(user["id"])
    return jsonify(result)

@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    result = stop_user_bot(user["id"])
    return jsonify(result)

@app.route("/api/bot/status", methods=["GET"])
def api_bot_status():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    status = get_bot_status(user["id"])
    if not status["running"]:
        return jsonify({"success": True, "running": False})

    # Fetch live data from bot-engine
    bot_data = proxy_to_bot(user["id"], "GET", "/api/status")
    bot_balance = proxy_to_bot(user["id"], "GET", "/api/balance")

    return jsonify({
        "success": True,
        "running": True,
        "port": status["port"],
        "started_at": status.get("started_at"),
        "bot_status": bot_data,
        "balance": bot_balance,
    })

@app.route("/api/bot/proxy", methods=["GET", "POST"])
def api_bot_proxy():
    """Proxy ANY request to user's bot-engine instance.
    This lets the dashboard talk to bot-engine without modifying bot-engine."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    path = request.args.get("path", "/")
    method = request.args.get("method", request.method).upper()
    body = request.get_json(silent=True) if request.method == "POST" else None

    result = proxy_to_bot(user["id"], method, path, body)
    return jsonify(result)

@app.route("/api/bot/embed")
def api_bot_embed():
    """Get bot-engine dashboard URL for iframe embedding."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    status = get_bot_status(user["id"])
    if not status["running"]:
        return jsonify({"success": False, "error": "Bot not running. Start bot first."})

    return jsonify({
        "success": True,
        "url": f"/bot/",
        "port": status["port"],
    })


@app.route("/api/bot/ensure_running", methods=["POST"])
def api_bot_ensure_running():
    """Ensure bot-engine Flask server is running for the logged-in user.
    This is called when the dashboard loads so the user can configure settings
    before starting the actual trading bot."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    sub = check_subscription(user)
    if not sub["active"]:
        return jsonify({"success": False, "error": "Subscription inactive/expired. License activate karein."}), 403

    status = get_bot_status(user["id"])
    if status["running"]:
        return jsonify({"success": True, "port": status["port"], "message": "Bot engine already running"})

    # Sync user's SaaS config to bot-engine config.json before starting
    # This ensures bot-engine starts with correct settings (exchange, testnet, etc.)
    bot_config = user.get("bot_config", {})
    if bot_config:
        try:
            write_user_bot_config(user["id"])
            logger.info(f"Synced SaaS config to bot-engine for user {user['id']}")
        except Exception as e:
            logger.warning(f"Config sync failed for {user['id']}: {e}")

    result = start_user_bot(user["id"], write_config=False)
    return jsonify(result)


# ============================================================
# Bot-Engine API Proxy
# All /api/<path> routes that are NOT defined above get proxied
# to the user's bot-engine instance. This lets the bot-engine's
# dashboard work directly from the SaaS app without iframe.
# ============================================================

BOT_ENGINE_API_ROUTES = {
    "config", "start", "stop", "force_stop", "status", "close",
    "price", "symbols", "test_chart", "preview", "test_connection",
    "balance", "test_notification", "active_symbol",
}


@app.route("/api/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def bot_api_proxy(path):
    """Proxy API calls to the user's bot-engine instance."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    # Only proxy known bot-engine routes
    first_segment = path.split("/")[0].split("?")[0]
    if first_segment not in BOT_ENGINE_API_ROUTES:
        return jsonify({"success": False, "error": "Unknown API route"}), 404

    status = get_bot_status(user["id"])
    if not status["running"] or not status.get("port"):
        return jsonify({"success": False, "error": "Bot engine not running. Dashboard pe Start karein."}), 400

    # Intercept POST /api/config to save config to SaaS DB
    if first_segment == "config" and request.method == "POST":
        body = request.get_json(force=True, silent=True)
        if body:
            bot_config = user.get("bot_config", {})
            if body.get("api_key") and body["api_key"] != "":
                bot_config["api_key_enc"] = encrypt(body["api_key"])
            if body.get("api_secret") and body["api_secret"] != "":
                bot_config["api_secret_enc"] = encrypt(body["api_secret"])
            if body.get("api_passphrase") and body["api_passphrase"] != "":
                bot_config["api_passphrase_enc"] = encrypt(body["api_passphrase"])
            for key in ["exchange", "symbols_list", "timeframe", "leverage",
                         "amount_mode", "amount", "amount_pct", "stop_loss_pct",
                         "take_profit_pct", "mode"]:
                if key in body:
                    bot_config[key] = body[key]
            if "testnet" in body:
                bot_config["testnet"] = body["testnet"]
            for key in ["telegram_enabled", "telegram_bot_token", "telegram_chat_id",
                         "email_enabled", "email_sender", "email_password", "email_receiver",
                         "email_smtp_server", "email_smtp_port",
                         "whatsapp_enabled", "whatsapp_phone", "whatsapp_apikey"]:
                if key in body:
                    enc_key = f"{key}_enc" if key in ["telegram_bot_token", "email_password", "whatsapp_apikey"] else None
                    if enc_key and body[key]:
                        bot_config[enc_key] = encrypt(body[key])
                    else:
                        bot_config[key] = body[key]
            DB["users"][user["id"]]["bot_config"] = bot_config
            save_db(DB)

    method = request.method
    target_url = f"http://127.0.0.1:{status['port']}/api/{path}"
    if request.query_string:
        target_url += f"?{request.query_string.decode()}"

    fwd_headers = {}
    for k, v in request.headers:
        if k.lower() not in ('host', 'cookie', 'content-length'):
            fwd_headers[k] = v
    fwd_headers['Content-Type'] = 'application/json'

    body = request.get_data() if method in ('POST', 'PUT', 'PATCH') else None

    try:
        resp = req_lib.request(method, target_url, headers=fwd_headers, data=body, timeout=30)
        excluded = {'content-encoding', 'transfer-encoding', 'connection', 'content-length', 'keep-alive'}
        response_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
        return Response(resp.content, status=resp.status_code, headers=response_headers)
    except req_lib.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "Bot engine not responding"}), 502
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# FULL PROXY — serves bot-engine dashboard in iframe
# This proxies HTML, CSS, JS, API calls, AND socket.io polling
# so the bot-engine's full dashboard works inside the SaaS app.
# ============================================================

@app.route('/bot/')
@app.route('/bot/<path:path>')
def bot_engine_proxy(path=''):
    """Proxy ALL requests to user's bot-engine instance.
    This makes the bot-engine dashboard work inside an iframe,
    with all CSS, JS, chart, and real-time updates."""
    if not is_logged_in():
        return "Not authorized", 401

    user = current_user()
    if not user:
        return "User not found", 404

    status = get_bot_status(user["id"])
    if not status["running"]:
        return "Bot not running. Start the bot first.", 400

    port = status["port"]
    method = request.method

    # Build target URL
    url = f"http://127.0.0.1:{port}/{path}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"

    # Forward request headers (excluding host/cookie)
    fwd_headers = {}
    for k, v in request.headers:
        if k.lower() not in ('host', 'cookie', 'content-length'):
            fwd_headers[k] = v

    # Get request body
    body = request.get_data() if method in ('POST', 'PUT', 'PATCH') else None

    try:
        resp = req_lib.request(method, url, headers=fwd_headers, data=body,
                               stream=True, timeout=30, allow_redirects=False)
    except req_lib.exceptions.ConnectionError:
        return "Bot engine not responding. Please restart the bot.", 502
    except Exception as e:
        return f"Proxy error: {str(e)}", 500

    # Build response headers (excluding hop-by-hop headers)
    excluded = {'content-encoding', 'transfer-encoding', 'connection',
                'content-length', 'keep-alive'}
    response_headers = [(k, v) for k, v in resp.headers.items()
                       if k.lower() not in excluded]

    content = resp.content
    content_type = resp.headers.get('content-type', '')

    # If HTML, rewrite URLs so they go through /bot/ prefix
    if 'text/html' in content_type:
        html = content.decode('utf-8', errors='replace')
        # Rewrite static file URLs
        html = html.replace('href="/static/', 'href="/bot/static/')
        html = html.replace('src="/static/', 'src="/bot/static/')
        # Rewrite API URLs in inline JS
        html = html.replace("fetch('/api/", "fetch('/bot/api/")
        html = html.replace('fetch("/api/', 'fetch("/bot/api/')
        # Rewrite socket.io to use /bot/ prefix
        html = html.replace("io({", "io({path: '/bot/socket.io', ")
        html = html.replace("io()", "io({path: '/bot/socket.io'})")
        content = html.encode('utf-8')

    # If JavaScript, rewrite fetch/socket URLs
    elif 'javascript' in content_type:
        js = content.decode('utf-8', errors='replace')
        js = js.replace("fetch('/api/", "fetch('/bot/api/")
        js = js.replace('fetch("/api/', 'fetch("/bot/api/')
        js = js.replace("io({", "io({path: '/bot/socket.io', ")
        js = js.replace("io()", "io({path: '/bot/socket.io'})")
        content = js.encode('utf-8')

    return Response(content, status=resp.status_code, headers=response_headers)


# ============================================================
# SocketIO — Real-time relay from bot-engine to dashboard
# ============================================================

# Track which user is connected via socketio and their bot-engine port
_socket_users = {}  # sid -> user_id
_bot_clients = {}   # user_id -> socketio.Client (connection to bot-engine)
_relay_lock = threading.Lock()


@socketio.on("connect")
def on_socket_connect():
    from flask_socketio import join_room
    sid = request.sid
    user_id = session.get("user_id")
    if not user_id:
        return False

    _socket_users[sid] = user_id
    join_room(user_id)
    logger.info(f"SocketIO client connected: sid={sid}, user={user_id}")

    # Send current bot status
    status = get_bot_status(user_id)
    socketio.emit("status", {
        "running": status.get("running", False),
        "symbols": [],
        "message": "Connected to TradeBot SaaS",
    }, room=user_id)

    _connect_to_bot_engine(user_id)


@socketio.on("disconnect")
def on_socket_disconnect():
    sid = request.sid
    user_id = _socket_users.pop(sid, None)
    if user_id:
        still_connected = any(uid == user_id for uid in _socket_users.values())
        if not still_connected:
            _disconnect_bot_client(user_id)
        logger.info(f"SocketIO client disconnected: sid={sid}")


@socketio.on("log")
def on_socket_log(data):
    pass


# Events to relay from bot-engine to SaaS clients
_RELAY_EVENTS = ["status", "log", "chart_data", "indicators", "signal", "position", "balance"]


def _connect_to_bot_engine(user_id: str):
    """Connect to user's bot-engine via socketio client and relay events."""
    with _relay_lock:
        if user_id in _bot_clients:
            return  # already connected

    status = get_bot_status(user_id)
    if not status.get("running") or not status.get("port"):
        logger.info(f"Relay skip for {user_id}: bot not running")
        return

    port = status["port"]
    import socketio as sio_lib

    client = sio_lib.Client(logger=False, engineio_logger=False)

    for event in _RELAY_EVENTS:
        def make_handler(evt):
            def handler(data):
                socketio.emit(evt, data, room=user_id)
            return handler
        client.on(event, make_handler(event))

    def on_connect():
        logger.info(f"Bot-engine connected for user {user_id} (port {port})")
        client.emit("log", {"level": "success", "msg": "SaaS relay connected to bot-engine"})

    def on_disconnect():
        logger.info(f"Bot-engine disconnected for user {user_id}")
        with _relay_lock:
            _bot_clients.pop(user_id, None)
        # Notify browser
        socketio.emit("status", {"running": False, "message": "Bot engine disconnected"},
                      room=user_id)

    def on_connect_error(data):
        logger.warning(f"Bot-engine connection error for {user_id}: {data}")
        socketio.emit("log", {"level": "error", "msg": f"Cannot connect to bot-engine: {data}"},
                      room=user_id)

    client.on("connect", on_connect)
    client.on("disconnect", on_disconnect)
    client.on("connect_error", on_connect_error)

    with _relay_lock:
        _bot_clients[user_id] = client

    def _run_client():
        try:
            # Retry connecting to bot-engine (it may still be starting up)
            for attempt in range(1, 11):
                try:
                    client.connect(f"http://127.0.0.1:{port}", wait_timeout=5)
                    client.wait()
                    return  # connected and running
                except Exception as ce:
                    if attempt < 10:
                        logger.info(f"Relay retry {attempt}/10 for {user_id}: {ce}")
                        time.sleep(2)
                    else:
                        raise
        except Exception as e:
            logger.error(f"Bot-engine client failed for {user_id}: {e}")
            socketio.emit("log", {"level": "error", "msg": f"Cannot connect to bot-engine: {e}"},
                          room=user_id)
            with _relay_lock:
                _bot_clients.pop(user_id, None)

    t = threading.Thread(target=_run_client, daemon=True, name=f"relay-{user_id[:8]}")
    t.start()


def _disconnect_bot_client(user_id: str):
    """Disconnect the bot-engine client for a user."""
    with _relay_lock:
        client = _bot_clients.pop(user_id, None)
    if client:
        try:
            client.disconnect()
        except:
            pass


# ============================================================
# Admin API
# ============================================================

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    """Admin login (separate from user)."""
    data = request.get_json(force=True)
    password = data.get("password", "")

    if password != ADMIN_SECRET:
        return jsonify({"success": False, "error": "Admin password galat hai"})

    # Find admin user
    admin_user = None
    for u in DB["users"].values():
        if u.get("role") == "admin":
            admin_user = u
            break

    if not admin_user:
        admin_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        admin_user = {
            "id": admin_id,
            "email": "admin@tradebot.com",
            "name": "Admin",
            "password_hash": hash_password(password),
            "role": "admin",
            "banned": False,
            "created_at": now,
            "subscription": {"plan": "lifetime", "status": "active", "started_at": now,
                            "expires_at": "9999-12-31T23:59:59Z"},
            "license_key": None,
            "bot_config": {},
        }
        DB["users"][admin_id] = admin_user
        save_db(DB)

    session["user_id"] = admin_user["id"]
    session.permanent = True
    return jsonify({"success": True, "user": {"id": admin_user["id"], "email": admin_user["email"], "role": "admin"}})

@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    users = []
    for u in DB["users"].values():
        if u.get("role") == "admin":
            continue
        sub = check_subscription(u)
        bot_status = get_bot_status(u["id"])
        users.append({
            "id": u["id"],
            "email": u["email"],
            "name": u.get("name", ""),
            "role": u.get("role", "user"),
            "banned": u.get("banned", False),
            "created_at": u.get("created_at"),
            "subscription": sub,
            "license_key": u.get("license_key"),
            "bot_running": bot_status.get("running", False),
            "exchange": u.get("bot_config", {}).get("exchange", "none"),
        })

    return jsonify({"success": True, "users": users})

@app.route("/api/admin/licenses", methods=["GET"])
def api_admin_list_licenses():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    licenses = list(DB.get("licenses", {}).values())
    return jsonify({"success": True, "licenses": licenses})

@app.route("/api/admin/licenses/create", methods=["POST"])
def api_admin_create_license():
    """Admin creates a license key.
    Body: {days: int, plan: str, note: str}"""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    days = int(data.get("days", 30))
    plan = data.get("plan", "basic")
    note = data.get("note", "")

    if days <= 0:
        return jsonify({"success": False, "error": "Days must be positive"})

    # Generate license key: TRDBOT-XXXX-XXXX-XXXX-XXXX
    parts = []
    for _ in range(4):
        parts.append(secrets.token_hex(2).upper())
    key = f"TRDBOT-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"

    now = datetime.utcnow()
    expires = now + timedelta(days=days)

    lic = {
        "key": key,
        "plan": plan,
        "days": days,
        "note": note,
        "created_at": now.isoformat() + "Z",
        "expires_at": expires.isoformat() + "Z",
        "used_by": None,
        "activated_at": None,
        "active": False,
        "revoked": False,
    }

    DB.setdefault("licenses", {})[key] = lic
    save_db(DB)

    logger.info(f"Admin created license: {key} ({days}d)")
    return jsonify({"success": True, "license": lic})

@app.route("/api/admin/licenses/revoke", methods=["POST"])
def api_admin_revoke_license():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip().upper()

    lic = DB.get("licenses", {}).get(key)
    if not lic:
        return jsonify({"success": False, "error": "License not found"})

    lic["revoked"] = True
    lic["active"] = False

    # Also deactivate user's subscription if license was used
    if lic.get("used_by"):
        user = DB["users"].get(lic["used_by"])
        if user:
            user["subscription"] = {"plan": "none", "status": "inactive",
                                   "started_at": datetime.utcnow().isoformat() + "Z",
                                   "expires_at": datetime.utcnow().isoformat() + "Z"}
            # Stop their bot
            stop_user_bot(lic["used_by"])

    save_db(DB)
    return jsonify({"success": True, "message": f"License {key} revoked"})

@app.route("/api/admin/licenses/delete", methods=["POST"])
def api_admin_delete_license():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip().upper()

    if key not in DB.get("licenses", {}):
        return jsonify({"success": False, "error": "License not found"})

    DB["licenses"].pop(key, None)
    save_db(DB)
    return jsonify({"success": True, "message": f"License {key} deleted"})

@app.route("/api/admin/ban", methods=["POST"])
def api_admin_ban():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    user_id = data.get("user_id")
    banned = bool(data.get("banned", False))

    user = DB["users"].get(user_id)
    if not user:
        return jsonify({"success": False, "error": "User not found"})

    if user.get("role") == "admin" and banned:
        return jsonify({"success": False, "error": "Cannot ban admin"})

    user["banned"] = banned
    if banned:
        stop_user_bot(user_id)
    save_db(DB)

    return jsonify({"success": True, "banned": banned, "message": "Banned" if banned else "Unbanned"})

@app.route("/api/admin/delete", methods=["POST"])
def api_admin_delete():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    user_id = data.get("user_id")

    user = DB["users"].get(user_id)
    if not user:
        return jsonify({"success": False, "error": "User not found"})

    if user.get("role") == "admin":
        return jsonify({"success": False, "error": "Cannot delete admin"})

    stop_user_bot(user_id)
    DB["users"].pop(user_id, None)
    save_db(DB)
    return jsonify({"success": True, "message": "User deleted"})

# ============================================================
# Health check + Keep-alive (prevents Railway sleep)
# ============================================================

@app.route("/health")
def health_check():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"})

def _keep_alive_ping():
    """Background thread that pings itself every 5 minutes to prevent Railway sleep."""
    import urllib.request, urllib.error
    while True:
        time.sleep(300)  # 5 minutes
        try:
            port = int(os.environ.get("PORT", 5000))
            host = os.environ.get("HOST", "0.0.0.0")
            url_host = "127.0.0.1" if host in ("0.0.0.0", "localhost") else host
            req = urllib.request.Request(f"http://{url_host}:{port}/health")
            urllib.request.urlopen(req, timeout=10)
            logger.debug("Keep-alive ping sent")
        except Exception as e:
            logger.debug(f"Keep-alive ping failed: {e}")

# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"SaaS webapp running on port {port}")

    # Start keep-alive thread (prevents Railway sleep)
    threading.Thread(target=_keep_alive_ping, daemon=True).start()

    socketio.run(app, host=host, port=port, debug=False,
                 allow_unsafe_werkzeug=True, use_reloader=False)
