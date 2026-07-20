"""
WEEX Exchange Futures Trader Module
Direct HTTP adapter for WEEX V3 contract API.

WEEX uses OKX-style authentication:
- 3 credentials: API Key + Secret Key + Passphrase
- HMAC-SHA256 signature, Base64-encoded
- 4 headers: ACCESS-KEY, ACCESS-PASSPHRASE, ACCESS-TIMESTAMP, ACCESS-SIGN

Base URL (mainnet): https://api-contract.weex.com
Demo mode: same host, paths swap "account" -> "sim"

Docs: https://www.weex.com/api-doc/contract/intro
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

WEEX_BASE_URL = "https://api-contract.weex.com"


@dataclass
class WEEXPosition:
    symbol: str
    side: str            # "LONG" / "SHORT" / "NONE"
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int


class WEEXFuturesTrader:
    """
    WEEX Futures API wrapper with same interface as BinanceFuturesTrader.
    Supports demo (paper) mode and live mode on same base URL.
    """

    def __init__(self, api_key: str, api_secret: str, passphrase: str,
                 testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.demo = testnet  # WEEX uses "demo mode" instead of separate testnet
        self.base_url = WEEX_BASE_URL
        self.session = requests.Session()
        self._contract_cache: dict = {}  # symbol -> contract specs

        if not (api_key and api_secret and passphrase):
            raise ValueError("WEEX requires API Key, Secret, AND Passphrase")

        logger.info("Connected to WEEX Futures (%s)",
                    "DEMO" if self.demo else "LIVE")

    # ---------- Auth ----------

    def _sign(self, method: str, path: str, query: str = "", body: str = "") -> dict:
        """Build the 4 ACCESS-* headers required by WEEX V3."""
        timestamp = str(int(time.time() * 1000))
        # Build the message: timestamp + METHOD + path[?query] + body
        if query:
            message = f"{timestamp}{method.upper()}{path}?{query}{body}"
        else:
            message = f"{timestamp}{method.upper()}{path}{body}"
        mac = hmac.new(self.api_secret.encode("utf-8"),
                       message.encode("utf-8"),
                       hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode("utf-8")
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-PASSPHRASE": self.passphrase,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-SIGN": sign,
            "Content-Type": "application/json",
        }

    # Paths that DO have a demo (/sim/) variant on WEEX
    _DEMO_PATHS = (
        "/capi/v3/account/balance",        # -> /capi/v3/sim/balance
        "/capi/v3/account/position",       # -> /capi/v3/sim/position
        "/capi/v3/order",                  # -> /capi/v3/sim/order
    )

    def _path(self, live_path: str) -> str:
        """Convert live path to demo path if demo mode is on.

        IMPORTANT: WEEX demo paths are INCONSISTENT - only some endpoints
        have a /sim/ variant. Testing confirmed:
        - /account/balance         -> /sim/balance          (has demo)
        - /account/position/allPosition -> /sim/position/allPosition  (has demo)
        - /order                   -> /sim/order            (has demo)
        - /account/leverage        -> /account/leverage     (NO demo - same path!)
        - /account/marginType      -> /account/marginType   (NO demo - same path!)

        So we ONLY replace the specific paths that have demo variants.
        """
        if not self.demo:
            return live_path
        for p in self._DEMO_PATHS:
            if live_path == p or live_path.startswith(p + "/"):
                # Replace the matched prefix /capi/v3/account/... -> /capi/v3/sim/...
                return live_path.replace(p, p.replace("/account/", "/sim/").replace("/order", "/sim/order"), 1)
        return live_path

    def _request(self, method: str, path: str, params: dict = None,
                 body: dict = None, signed: bool = False):
        """Execute HTTP request with optional signing."""
        params = params or {}
        body = body or {}
        original_path = path  # Keep original for debugging
        path = self._path(path)
        url = self.base_url + path

        body_str = json.dumps(body) if body and method.upper() == "POST" else ""
        query_str = "&".join(f"{k}={v}" for k, v in params.items()) if params else ""

        headers = {"Content-Type": "application/json"}
        if signed:
            headers = self._sign(method, path, query_str, body_str)

        try:
            if method.upper() == "GET":
                resp = self.session.get(url, params=params, headers=headers, timeout=8)
            else:
                resp = self.session.post(url, data=body_str, params=params,
                                         headers=headers, timeout=8)
            data = resp.json()
            if resp.status_code >= 400:
                err_msg = data.get("msg") or data.get("error") or f"HTTP {resp.status_code}"
                err_code = data.get("code", "?")
                # Log full response for debugging
                logger.error("WEEX API error: code=%s, msg=%s (path=%s, original=%s, params=%s, signed=%s)",
                             err_code, err_msg, path, original_path, params, signed)
                # Provide user-friendly error messages for common WEEX errors
                if err_code == -1044 or "Invalid ACCESS_KEY" in str(err_msg):
                    err_msg = (f"WEEX API key invalid (code -1044). Check that API Key is correct. "
                               f"Create keys at weex.com → User Center → API Management.")
                elif "authentication failed" in str(err_msg).lower() or err_code in (-1005, -1006, 401):
                    err_msg = (f"WEEX signature authentication failed (code {err_code}). "
                               f"Most likely causes: (1) API Secret is wrong, "
                               f"(2) Passphrase is wrong, (3) System clock is out of sync. "
                               f"Please re-check your API Secret and Passphrase in settings.")
                raise RuntimeError(f"WEEX API error: {err_msg}")
            return data
        except requests.exceptions.Timeout:
            logger.error("WEEX request TIMEOUT (8s): %s %s", method, path)
            raise RuntimeError(f"WEEX API timeout (8s) - check internet connection")
        except requests.exceptions.ConnectionError as e:
            logger.error("WEEX connection error: %s", e)
            raise RuntimeError(f"WEEX connection failed - check internet or API endpoint")
        except requests.exceptions.RequestException as e:
            logger.error("WEEX request failed: %s", e)
            raise

    def test_connection(self) -> dict:
        """Test API connection by fetching balance. Returns detailed result.

        This is used by the /api/test_connection endpoint to give the user
        clear feedback about whether their API credentials work.
        """
        try:
            balance = self.get_balance()
            return {
                "success": True,
                "message": f"Connected successfully! Balance: ${balance:.2f}",
                "balance": balance,
                "exchange": "weex",
                "demo": self.demo,
            }
        except Exception as e:
            err_str = str(e)
            # Determine the specific cause
            if "-1044" in err_str or "Invalid ACCESS_KEY" in err_str:
                cause = "API Key is invalid or doesn't exist"
                fix = "Go to weex.com → User Center → API Management and copy the correct API Key"
            elif "authentication failed" in err_str.lower():
                cause = "Signature authentication failed"
                fix = "Your API Secret or Passphrase is wrong. Re-enter them carefully. " \
                      "Note: Passphrase is what YOU set when creating the API key (not your account password)."
            elif "timeout" in err_str.lower():
                cause = "Network timeout"
                fix = "Check your internet connection"
            elif "connection" in err_str.lower():
                cause = "Cannot connect to WEEX"
                fix = "Check your internet or firewall settings"
            else:
                cause = "Unknown error"
                fix = "Check the bot logs for details"
            return {
                "success": False,
                "error": err_str,
                "cause": cause,
                "fix": fix,
            }

    # ---------- Market data (public) ----------

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 200) -> pd.DataFrame:
        """Fetch historical klines. WEEX interval codes: 1m,5m,15m,30m,1h,4h,12h,1d,1w.

        IMPORTANT: Public market data ALWAYS uses plain format (BTCUSDT),
        even when the user selected a demo coin (BTCSUSDT). The _market_symbol()
        helper converts BTCSUSDT -> BTCUSDT automatically.
        """
        market_sym = self._market_symbol(symbol)
        path = "/capi/v3/market/klines"
        params = {"symbol": market_sym, "interval": interval, "limit": min(limit, 1000)}
        data = self._request("GET", path, params=params)

        # WEEX returns {"code":0,"data":[[time, open, high, low, close, volume, ...], ...]}
        rows = data.get("data", []) if isinstance(data, dict) else data
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # WEEX can return variable number of columns. Handle gracefully.
        # Known columns: time, open, high, low, close, volume, value, number, ...
        # We only need: time, open, high, low, close, volume (first 6)
        parsed_rows = []
        for row in rows:
            if isinstance(row, dict):
                # Dict format
                parsed_rows.append({
                    "time": row.get("time") or row.get("timestamp"),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0) or row.get("vol", 0)),
                })
            elif isinstance(row, (list, tuple)):
                # Array format - take first 6 elements
                if len(row) >= 6:
                    parsed_rows.append({
                        "time": row[0],
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    })

        if not parsed_rows:
            logger.warning("WEEX klines returned EMPTY for %s %s (raw=%s)", symbol, interval, str(data)[:200])
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(parsed_rows)
        df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
        df.set_index("time", inplace=True)
        df.dropna(subset=["open", "high", "low", "close"], inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

    def get_mark_price(self, symbol: str) -> float:
        """Get current mark price for a symbol.

        WEEX response format (verified via curl):
            {"symbol":"BTCUSDT","price":"64605.671","time":1784066657701}
        Note: NO 'data' wrapper - it's a flat object.

        IMPORTANT: Public market data ALWAYS uses plain format (BTCUSDT),
        even when the user selected a demo coin (BTCSUSDT). The _market_symbol()
        helper converts BTCSUSDT -> BTCUSDT automatically.
        """
        market_sym = self._market_symbol(symbol)
        path = "/capi/v3/market/symbolPrice"
        params = {"symbol": market_sym}
        try:
            data = self._request("GET", path, params=params)
        except Exception as e:
            logger.warning("WEEX get_mark_price failed for %s: %s", symbol, e)
            return 0.0
        # WEEX returns flat object: {symbol, price, time}
        # Be defensive: try 'data.price', then 'price'
        if isinstance(data, dict):
            if isinstance(data.get("data"), dict):
                price_str = data["data"].get("price", "0")
            else:
                price_str = data.get("price", "0")
            try:
                return float(price_str)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def get_contract_info(self, symbol: str) -> dict:
        """Fetch contract specs (lot size, tick size) for a symbol. Cached.

        WEEX has no public /capi/v3/market/contracts endpoint (returns 404).
        We fetch from /capi/v3/market/ticker/24hr (which returns all symbols)
        and just use sensible defaults for step/min/tick size.
        """
        symbol = symbol.upper()
        if symbol in self._contract_cache:
            return self._contract_cache[symbol]
        # Defaults based on price magnitude (good enough for most pairs)
        # For BTC ($64k): step=0.001 BTC, tick=$0.1
        # For low-price coins: step=1, tick=$0.0001
        try:
            price = self.get_mark_price(symbol)
            if price > 0:
                if price >= 1000:
                    defaults = {"step_size": 0.001, "min_qty": 0.001, "tick_size": 0.1, "contract_size": 1}
                elif price >= 100:
                    defaults = {"step_size": 0.01, "min_qty": 0.01, "tick_size": 0.01, "contract_size": 1}
                elif price >= 1:
                    defaults = {"step_size": 1.0, "min_qty": 1.0, "tick_size": 0.001, "contract_size": 1}
                else:
                    defaults = {"step_size": 100.0, "min_qty": 100.0, "tick_size": 0.0001, "contract_size": 1}
            else:
                defaults = {"step_size": 0.001, "min_qty": 0.001, "tick_size": 0.01, "contract_size": 1}
        except Exception:
            defaults = {"step_size": 0.001, "min_qty": 0.001, "tick_size": 0.01, "contract_size": 1}
        self._contract_cache[symbol] = defaults
        return defaults

    # ---------- Account (private, signed) ----------

    def get_balance(self) -> float:
        """Get USDT available balance.

        WEEX demo path: /capi/v3/sim/balance
        WEEX live path: /capi/v3/account/balance

        CRITICAL — Demo mode returns asset='SUSDT' (NOT 'USDT'):
            Live response: [{"asset":"USDT", "availableBalance":"5000"}]
            Demo response: [{"asset":"SUSDT", "availableBalance":"20000"}]

        If we only check for 'USDT', demo mode returns $0 — which is the
        ROOT CAUSE of the user seeing $0 balance in WEEX demo mode.
        """
        try:
            path = "/capi/v3/account/balance"
            data = self._request("GET", path, signed=True)
        except Exception as e:
            logger.error("WEEX get_balance failed: %s", e)
            return 0.0
        rows = data
        if isinstance(data, dict):
            rows = data.get("data", data.get("result", []))
        # DEBUG: Log raw response so we can diagnose $0 balance issues
        logger.info("WEEX balance raw response: %s", str(data)[:500])
        if isinstance(rows, dict):
            usdt = rows.get("USDT") or rows.get("usdt") or rows.get("SUSDT")
            if isinstance(usdt, dict):
                for k in ("availableBalance", "availBal", "available", "balance", "cashBal"):
                    if k in usdt:
                        try:
                            return float(usdt[k])
                        except (TypeError, ValueError):
                            pass
            logger.warning("WEEX balance: dict response but no USDT/SUSDT. Keys: %s",
                           list(rows.keys()) if isinstance(rows, dict) else "N/A")
            return 0.0
        if not isinstance(rows, list):
            logger.warning("WEEX balance: not a list. Type: %s", type(rows).__name__)
            return 0.0
        if len(rows) == 0:
            logger.warning("WEEX balance: EMPTY list. Account may have no funds "
                           "or API key lacks 'Read-only' permission.")
            return 0.0
        for a in rows:
            if not isinstance(a, dict):
                continue
            # CRITICAL: Check both 'USDT' (live) AND 'SUSDT' (demo)
            ccy = (a.get("asset") or a.get("ccy") or a.get("coin") or a.get("currency") or "").upper()
            if ccy in ("USDT", "SUSDT"):
                for k in ("availableBalance", "availBal", "available", "balance", "cashBal", "maxWithdrawAmount"):
                    if k in a and a[k] not in (None, ""):
                        try:
                            return float(a[k])
                        except (TypeError, ValueError):
                            continue
        # If we got here, response had data but no USDT/SUSDT
        assets_found = [a.get("asset") or a.get("ccy") for a in rows if isinstance(a, dict)]
        logger.warning("WEEX balance: no USDT/SUSDT asset found. Assets in response: %s", assets_found)
        return 0.0

    def get_position(self, symbol: str) -> WEEXPosition:
        """Get current position for a symbol.

        WEEX demo path: /capi/v3/sim/position/allPosition
        WEEX live path: /capi/v3/account/position/allPosition

        IMPORTANT — Demo mode returns symbol with 'S' suffix:
            Live response: [{"symbol":"BTCUSDT", ...}]
            Demo response: [{"symbol":"BTCSUSDT", ...}]

        So when looking for BTCUSDT in demo mode, we also need to match BTCSUSDT.
        """
        path = "/capi/v3/account/position/allPosition"
        try:
            data = self._request("GET", path, params={"symbol": symbol}, signed=True)
        except Exception as e:
            logger.warning("WEEX get_position failed: %s", e)
            return WEEXPosition(symbol, "NONE", 0, 0, 0, 0, 1)

        positions = data
        if isinstance(data, dict):
            positions = data.get("data", data.get("result", []))
        if not isinstance(positions, list):
            positions = []

        if not positions:
            return WEEXPosition(symbol, "NONE", 0, 0, 0, 0, 1)

        # Build list of acceptable symbol variants for matching.
        # In demo mode, position response uses 'BTCSUSDT' but order request uses 'BTCUSDT'
        # so we match either form. We also try the 'S' inserted before 'USDT'.
        sym_variants = {symbol.upper()}
        if symbol.upper().endswith("USDT"):
            base = symbol.upper()[:-4]  # strip USDT
            sym_variants.add(f"{base}SUSDT")  # BTCSUSDT
        if symbol.upper().endswith("SUSDT"):
            base = symbol.upper()[:-5]  # strip SUSDT
            sym_variants.add(f"{base}USDT")  # BTCUSDT

        for p in positions:
            if not isinstance(p, dict):
                continue
            sym_match = (p.get("symbol") or p.get("instId") or "").upper()
            sym_clean = sym_match.replace("-", "").replace("SWAP", "")
            if sym_clean not in sym_variants:
                continue
            # Get quantity - try multiple field names
            qty = 0.0
            for k in ("total", "positionAmt", "pos", "posSize", "size"):
                v = p.get(k)
                if v not in (None, "", 0, "0"):
                    try:
                        qty = float(v)
                        break
                    except (TypeError, ValueError):
                        continue
            if qty == 0:
                continue
            side = (p.get("positionSide") or p.get("posSide") or p.get("side") or "").upper()
            if side not in ("LONG", "SHORT"):
                side = "LONG" if qty > 0 else "SHORT"
            # Get entry, mark, pnl, leverage
            entry = 0.0
            for k in ("avgPrice", "entryPrice", "avgPx", "entry", "openPrice", "openValue"):
                v = p.get(k)
                if v not in (None, "", 0, "0"):
                    try:
                        entry = float(v); break
                    except (TypeError, ValueError):
                        continue
            mark = 0.0
            for k in ("markPrice", "markPx", "last", "lastPrice"):
                v = p.get(k)
                if v not in (None, "", 0, "0"):
                    try:
                        mark = float(v); break
                    except (TypeError, ValueError):
                        continue
            pnl = 0.0
            for k in ("unrealizedPNL", "unrealizePnl", "upl", "unrealizedProfit"):
                v = p.get(k)
                if v not in (None, "", 0, "0"):
                    try:
                        pnl = float(v); break
                    except (TypeError, ValueError):
                        continue
            lev = 1
            for k in ("leverage", "lever", "crossLeverage"):
                v = p.get(k)
                if v not in (None, "", 0, "0"):
                    try:
                        lev = int(float(v)); break
                    except (TypeError, ValueError):
                        continue
            return WEEXPosition(
                symbol=symbol, side=side, size=qty, entry_price=entry,
                mark_price=mark, unrealized_pnl=pnl, leverage=lev,
            )
        return WEEXPosition(symbol, "NONE", 0, 0, 0, 0, 1)

    # ---------- Orders ----------

    def _market_symbol(self, symbol: str) -> str:
        """Convert a (possibly demo-style) symbol to the format used by WEEX
        PUBLIC market data endpoints (klines, markPrice, ticker).

        Public market data ALWAYS uses plain format (BTCUSDT) — even in demo mode.
        But user-selected coins in demo mode are S-suffix (BTCSUSDT) because
        that's what the apiTradingSymbols endpoint returns for demo.

        So when fetching klines/mark_price for BTCSUSDT, we need to convert
        to BTCUSDT first. This helper does that conversion.

        Examples:
            BTCSUSDT  -> BTCUSDT   (strip the S before USDT)
            1000PEPESUSDT -> 1000PEPEUSDT
            BTCUSDT   -> BTCUSDT   (no change for live mode)
        """
        sym = symbol.upper()
        if sym.endswith("SUSDT"):
            return sym[:-5] + "USDT"  # strip 'S' between base and USDT
        return sym

    def _order_symbol(self, symbol: str) -> str:
        """Convert a (possibly plain) symbol to the format used by WEEX
        PRIVATE endpoints (orders, positions, leverage).

        In demo mode, private endpoints require S-suffix (BTCSUSDT).
        In live mode, private endpoints require plain format (BTCUSDT).

        If user is in demo mode and selected BTCSUSDT, no conversion needed.
        If user is in demo mode and somehow selected BTCUSDT (legacy), convert.
        If user is in live mode, no conversion needed.
        """
        sym = symbol.upper()
        if not self.demo:
            return sym
        # Demo mode: ensure S-suffix
        if sym.endswith("SUSDT"):
            return sym
        if sym.endswith("USDT"):
            return sym[:-4] + "SUSDT"
        return sym

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set leverage for a symbol. WEEX supports up to 500x.

        WEEX V3 API endpoint: POST /capi/v3/account/leverage
        - Works for BOTH live and demo (NO /sim/ variant)
        - In demo mode, symbol should be BTCSUSDT (auto-converted by _order_symbol)
        - In live mode, symbol should be BTCUSDT

        WEEX's leverage endpoint is picky about body format. We try multiple
        body shapes since WEEX docs are inconsistent. If all attempts fail
        with parameter errors (not auth errors), we treat it as success
        because:
          1. The bot will use the exchange's default leverage (usually 20x)
          2. Trades will still work — leverage just won't be the user's choice
          3. Blocking bot start over leverage setting is worse than using default
        """
        leverage = max(1, min(500, int(leverage)))
        # Convert to the format WEEX expects for this mode (BTCSUSDT for demo)
        order_sym = self._order_symbol(symbol)
        # WEEX expects: {symbol, marginType, crossLeverage}
        # Try multiple body shapes — WEEX has changed this format over time
        bodies_to_try = [
            {"symbol": order_sym, "marginType": "CROSSED", "crossLeverage": leverage},
            {"symbol": order_sym, "leverage": leverage, "marginType": "CROSSED"},
            {"symbol": order_sym, "crossLeverage": leverage},
        ]
        path = "/capi/v3/account/leverage"
        last_error = None
        parameter_errors = 0
        for body in bodies_to_try:
            try:
                resp = self._request("POST", path, body=body, signed=True)
                logger.info("WEEX leverage set to %dx for %s (symbol=%s, body=%s)",
                            leverage, symbol, order_sym, list(body.keys()))
                return {"success": True, "leverage": leverage, "raw": resp}
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                # Auth errors - fail immediately (don't try other bodies)
                if "-1044" in err_str or "invalid access_key" in err_str:
                    return {"success": False, "error": str(e)}
                # Parameter errors (symbol invalid, etc.) - try next body shape
                if ("-1141" in err_str or "-1142" in err_str or
                    "must not" in err_str or "invalid param" in err_str or
                    "is invalid" in err_str):
                    parameter_errors += 1
                    continue
                # "Trading pair not supported via API" - this coin isn't API-tradable
                if "not supported" in err_str and "api" in err_str:
                    return {"success": False, "error": str(e)}
                # Other error (e.g., leverage out of range) - return as failure
                return {"success": False, "error": str(e)}

        # All bodies failed with parameter errors
        # WEEX leverage API is unreliable — don't block the bot.
        # Bot will use exchange default leverage (usually 20x).
        logger.warning(
            "WEEX set_leverage failed for %s (tried %d body shapes, all returned parameter errors). "
            "Bot will use exchange default leverage. Last error: %s",
            symbol, parameter_errors, last_error,
        )
        return {
            "success": True,  # Don't block the bot
            "leverage": leverage,
            "warning": f"Could not set leverage to {leverage}x for {symbol} (WEEX API rejected all body formats). "
                       f"Bot will use WEEX's default leverage. "
                       f"Tip: Set leverage manually at weex.com → Futures → {symbol}",
            "raw": "default",
        }

    def place_market_order(self, symbol: str, side: str, quantity: float,
                           reduce_only: bool = False,
                           position_side: str = None,
                           sl_price: float = None,
                           tp_price: float = None) -> dict:
        """
        Place a MARKET order on WEEX with optional SL/TP attached.

        Confirmed working body fields (from WEEX API docs):
          - symbol (required) — "BTCUSDT" for live, "BTCSUSDT" for demo
          - side (required, "BUY"/"SELL")
          - positionSide (required, "LONG"/"SHORT")
          - type (required, "MARKET")
          - quantity (base-asset qty as string)
          - newClientOrderId (recommended, unique per order)
          - reduceOnly (optional, "true" for closing positions)
          - slTriggerPrice (optional) — Stop Loss trigger price
          - tpTriggerPrice (optional) — Take Profit trigger price
          - SlWorkingType (optional) — "MARK_PRICE" or "CONTRACT_PRICE"
          - TpWorkingType (optional) — "MARK_PRICE" or "CONTRACT_PRICE"

        WEEX demo path: /capi/v3/sim/order
        WEEX live path: /capi/v3/order

        IMPORTANT: In demo mode, the symbol in the order body must be
        BTCSUSDT (not BTCUSDT). The _order_symbol() helper handles this.

        SL/TP PRICES:
          - For LONG: SL < entry < TP (SL below, TP above)
          - For SHORT: TP < entry < SL (TP below, SL above)
          - Prices should be rounded to tick size
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            return {"success": False, "error": f"Invalid side: {side}"}
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be > 0"}

        # Convert symbol to WEEX-expected format (BTCSUSDT for demo, BTCUSDT for live)
        order_sym = self._order_symbol(symbol)
        # For contract info (public market data), use plain format
        market_sym = self._market_symbol(symbol)

        # Round quantity to contract step size
        try:
            info = self.get_contract_info(market_sym)
            step = info["step_size"]
            min_qty = info["min_qty"]
            tick = info.get("tick_size", 0.01)
            quantity = self._round_to_step(quantity, step)
            if quantity < min_qty:
                return {"success": False,
                        "error": f"Quantity {quantity} below min {min_qty} for {symbol}"}
            # Round SL/TP prices to tick size
            if sl_price and sl_price > 0:
                sl_price = self._round_to_step(sl_price, tick)
            if tp_price and tp_price > 0:
                tp_price = self._round_to_step(tp_price, tick)
        except Exception as e:
            logger.warning("Could not fetch WEEX contract info for %s, trying order anyway: %s", symbol, e)

        # Determine positionSide based on side and intent
        if position_side is None:
            position_side = "LONG" if side == "BUY" else "SHORT"
            if reduce_only:
                position_side = "LONG" if side == "SELL" else "SHORT"

        try:
            path = "/capi/v3/order"
            import uuid as _uuid
            import time as _time
            body = {
                "symbol": order_sym,
                "side": side,
                "positionSide": position_side,
                "type": "MARKET",
                "quantity": str(quantity),
                "newClientOrderId": f"{order_sym}{int(_time.time()*1000)}{_uuid.uuid4().hex[:8]}",
            }
            if reduce_only:
                body["reduceOnly"] = "true"
            # Attach SL/TP trigger prices to the order itself
            # This places REAL exchange-side SL/TP orders (not just software watchdog)
            if sl_price and sl_price > 0 and not reduce_only:
                body["slTriggerPrice"] = str(sl_price)
                body["SlWorkingType"] = "MARK_PRICE"
            if tp_price and tp_price > 0 and not reduce_only:
                body["tpTriggerPrice"] = str(tp_price)
                body["TpWorkingType"] = "CONTRACT_PRICE"
            resp = self._request("POST", path, body=body, signed=True)
            # Parse orderId from various response shapes
            oid = "?"
            if isinstance(resp, dict):
                inner = resp.get("data", resp)
                if isinstance(inner, dict):
                    oid = inner.get("orderId", inner.get("order_id", inner.get("id", "?")))
                else:
                    oid = resp.get("orderId", "?")
            sltp_info = ""
            if sl_price or tp_price:
                sltp_info = f" | SL={sl_price} TP={tp_price}"
            logger.info("WEEX order placed: %s %s qty=%s posSide=%s%s -> orderId=%s",
                        side, order_sym, quantity, position_side, sltp_info, oid)
            return {"success": True, "order": resp, "quantity": quantity,
                    "sl_price": sl_price, "tp_price": tp_price}
        except Exception as e:
            logger.error("WEEX order failed: %s", e)
            return {"success": False, "error": str(e), "quantity": quantity}

    def close_position(self, symbol: str) -> dict:
        """Close the current position using reduceOnly market order."""
        pos = self.get_position(symbol)
        if pos.side == "NONE" or pos.size == 0:
            return {"success": True, "message": "No position to close"}
        # Closing LONG -> SELL with reduceOnly; closing SHORT -> BUY with reduceOnly
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        return self.place_market_order(
            symbol=symbol,
            side=close_side,
            quantity=abs(pos.size),
            reduce_only=True,
            position_side=pos.side,
        )

    def open_long(self, symbol: str, quantity: float,
                  sl_price: float = None, tp_price: float = None) -> dict:
        """Open a LONG position with optional SL/TP attached.

        SL price should be BELOW entry price (e.g., entry*0.98 for 2% SL).
        TP price should be ABOVE entry price (e.g., entry*1.06 for 6% TP).
        """
        return self.place_market_order(symbol, "BUY", quantity,
                                       reduce_only=False, position_side="LONG",
                                       sl_price=sl_price, tp_price=tp_price)

    def open_short(self, symbol: str, quantity: float,
                   sl_price: float = None, tp_price: float = None) -> dict:
        """Open a SHORT position with optional SL/TP attached.

        SL price should be ABOVE entry price (e.g., entry*1.02 for 2% SL).
        TP price should be BELOW entry price (e.g., entry*0.94 for 6% TP).
        """
        return self.place_market_order(symbol, "SELL", quantity,
                                       reduce_only=False, position_side="SHORT",
                                       sl_price=sl_price, tp_price=tp_price)

    # ---------- Helpers ----------

    def get_all_symbols(self) -> list:
        """Fetch API-tradable USDT perpetual symbols from WEEX.

        CRITICAL FIX: Previously fetched from /capi/v3/market/ticker/24hr
        which returns ALL 867 symbols — but only 337 of those are actually
        tradable via API. Trying to trade the others gives:
            "The trading pair is not supported via the API"

        Now fetches from /capi/v3/market/apiTradingSymbols which returns
        ONLY the 337 API-tradable symbols. This is the official list WEEX
        returns in error messages.

        FILTERING BY MODE:
        - Demo mode: returns only S-suffix coins (BTCSUSDT, ETHSUSDT, ...) — 64 coins
        - Live mode: returns only plain coins (BTCUSDT, ETHUSDT, ...) — 273 coins

        WEEX demo and live use DIFFERENT symbol names:
          Live: BTCUSDT       Demo: BTCSUSDT      (extra 'S' before USDT)
        Only 40 coins have BOTH versions. The other coins work in ONE mode only.
        For example, 1000PEPEUSDT only exists in live mode — trading it in demo
        will fail with "trading pair not supported via the API".
        """
        # Try the official API-tradable symbols endpoint
        try:
            data = self._request("GET", "/capi/v3/market/apiTradingSymbols", params={})
            all_symbols = self._extract_symbols_from_response(data)
            if all_symbols:
                # Filter by mode
                if self.demo:
                    # Demo mode: only S-suffix coins (BTCSUSDT)
                    filtered = [s for s in all_symbols if s.endswith("SUSDT")]
                    logger.info(f"Fetched {len(filtered)} WEEX DEMO symbols (S-suffix) "
                                f"from {len(all_symbols)} total API-tradable")
                    return sorted(filtered)
                else:
                    # Live mode: only plain coins (BTCUSDT), exclude S-suffix
                    filtered = [s for s in all_symbols
                                if s.endswith("USDT") and not s.endswith("SUSDT")]
                    logger.info(f"Fetched {len(filtered)} WEEX LIVE symbols (plain) "
                                f"from {len(all_symbols)} total API-tradable")
                    return sorted(filtered)
        except Exception as e:
            logger.warning(f"WEEX apiTradingSymbols failed: {e}")

        # Fallback: comprehensive list (mode-filtered)
        logger.warning("Using fallback WEEX coin list (API endpoint not available)")
        fallback = self._get_weex_fallback_symbols()
        if self.demo:
            # Return only S-suffix versions
            return sorted([f"{s[:-4]}SUSDT" for s in fallback if s.endswith("USDT")])
        return fallback

    def _extract_symbols_from_response(self, data) -> list:
        """Extract USDT symbols from any WEEX API response format.

        The apiTradingSymbols endpoint returns a flat list of strings:
            ["0GUSDT", "1000BONKUSDT", "AAVESUSDT", "BTCUSDT", "BTCSUSDT", ...]
        """
        symbols = []
        rows = data
        if isinstance(data, dict):
            rows = data.get("data", data.get("result", data.get("symbols", [])))
            if isinstance(rows, dict):
                rows = [rows]
        if not isinstance(rows, list):
            return []

        for item in rows:
            if isinstance(item, dict):
                sym = (item.get("symbol") or item.get("contractName") or
                       item.get("pair") or item.get("name") or item.get("baseAsset", ""))
                if isinstance(sym, str) and sym.upper().endswith("USDT"):
                    symbols.append(sym.upper())
            elif isinstance(item, str) and item.upper().endswith("USDT"):
                symbols.append(item.upper())

        # Deduplicate and sort
        return sorted(list(set(symbols)))

    @staticmethod
    def _get_weex_fallback_symbols() -> list:
        """Comprehensive list of common WEEX USDT perpetual coins.
        Updated regularly. New coins appear when API endpoints work."""
        return sorted([
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
            "DOTUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "UNIUSDT",
            "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
            "SUIUSDT", "SEIUSDT", "TIAUSDT", "ORDIUSDT", "PEPEUSDT",
            "SHIBUSDT", "FILUSDT", "FTMUSDT", "ALGOUSDT", "EOSUSDT",
            "XTZUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "GALAUSDT",
            "GRTUSDT", "CHZUSDT", "ENJUSDT", "THETAUSDT", "RUNEUSDT",
            "AAVEUSDT", "SNXUSDT", "CRVUSDT", "1INCHUSDT", "YFIUSDT",
            "COMPUSDT", "MKRUSDT", "SUSHIUSDT", "BALUSDT", "RNDRUSDT",
            "IMXUSDT", "LDOUSDT", "STXUSDT", "FETUSDT", "AGIXUSDT",
            "OCEANUSDT", "WLDUSDT", "CYBERUSDT", "BLURUSDT", "GMXUSDT",
            "DYDXUSDT", "JOEUSDT", "PYTHUSDT", "JTOUSDT", "BONKUSDT",
            "WIFUSDT", "FLOKIUSDT", "MEMEUSDT", "TURBOUSDT", "BOMEUSDT",
            "JUPUSDT", "RAYUSDT", "PYRUSDT", "ACEUSDT", "NFPUSDT",
            "INSURUSDT", "MOVRUSDT", "GLMRUSDT", "ASTRUSDT", "CFXUSDT",
            "ZILUSDT", "KAVAUSDT", "KSMUSDT", "MINAUSDT", "ROSEUSDT",
            "IOTAUSDT", "FLOWUSDT", "XLMUSDT", "VETUSDT", "HBARUSDT",
            "ICPUSDT", "FILUSDT", "ARUSDT", "KLAYUSDT", "QNTUSDT",
            "FXSUSDT", "GMTUSDT", "APEUSDT", "GTCUSDT", "LRCUSDT",
        ])


    @staticmethod
    def _round_to_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        decimals = max(0, int(math.ceil(-math.log10(step))))
        rounded = math.floor(value / step) * step
        return round(rounded, decimals)

    def compute_quantity(self, notional_usdt: float, price: float,
                         leverage: int, qty_step: float = 0.001) -> float:
        """Compute contract quantity from USDT notional."""
        if price <= 0:
            return 0.0
        raw_qty = notional_usdt / price
        return raw_qty  # final rounding happens in place_market_order
