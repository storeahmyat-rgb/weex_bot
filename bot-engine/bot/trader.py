"""
Binance Futures Trader Module
Handles all interactions with Binance USDT-M Futures API.

Uses the official `binance-futures-connector` package (v1.5.0+) for API calls.
Falls back to `python-binance` if the connector is not available.

Functions:
- Set leverage
- Place market orders (long / short)
- Query account balance & open positions
- Close positions
- Fetch historical klines for strategy
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Try to import a Binance futures client.
# Preferred: `binance-futures-connector` (official, v1.5.0+).
# Fallback: `python-binance`.
try:
    from binance.futures import Futures as FuturesClient  # noqa: F401
    _CONNECTOR = "binance-futures-connector"
except Exception:  # pragma: no cover
    try:
        from binance.client import Client as _BClient  # python-binance
        FuturesClient = None
        _CONNECTOR = "python-binance"
    except Exception:
        FuturesClient = None
        _CONNECTOR = "none"


@dataclass
class Position:
    symbol: str
    side: str            # "LONG" / "SHORT" / "NONE"
    size: float          # base asset qty (signed: + long, - short)
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int


class BinanceFuturesTrader:
    """Wraps Binance USDT-M Futures API for the bot. Supports testnet and mainnet."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.client = None
        self._exchange_info_cache: dict = {}  # symbol -> {step_size, min_qty, tick_size}
        self._connect()

    def _connect(self):
        if _CONNECTOR == "binance-futures-connector":
            # v1.5.0 API: Futures(key=..., secret=..., base_url=...)
            # IMPORTANT: do NOT add /fapi suffix - the library already prepends /fapi/v1/... to paths
            base_url = (
                "https://testnet.binancefuture.com"
                if self.testnet else "https://fapi.binance.com"
            )
            self.client = FuturesClient(
                key=self.api_key,
                secret=self.api_secret,
                base_url=base_url,
            )
            logger.info("Connected to Binance Futures (%s) via binance-futures-connector",
                        "TESTNET" if self.testnet else "MAINNET")
        elif _CONNECTOR == "python-binance":
            self.client = _BClient(self.api_key, self.api_secret, testnet=self.testnet)
            try:
                self.client.FUTURES_URL = (
                    "https://testnet.binancefuture.com/fapi"
                    if self.testnet else "https://fapi.binance.com/fapi"
                )
            except Exception:
                pass
            logger.info("Connected to Binance Futures (%s) via python-binance",
                        "TESTNET" if self.testnet else "MAINNET")
        else:
            raise RuntimeError(
                "No Binance library installed. Run: pip install -r requirements.txt"
            )

    # ---------- Market data ----------

    def _retry_api_call(self, func, *args, max_retries=3, **kwargs):
        """Retry an API call on network errors with exponential backoff.
        Prevents bot crashes from temporary internet drops."""
        import time
        last_error = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                # Only retry on network/connection errors, not on auth errors
                is_network_error = any(x in err_str for x in [
                    "connection aborted", "remotedisconnected", "connectionerror",
                    "timeout", "timed out", "connection reset", "max retries",
                    "ssl", "eof", "broken pipe", "remote end closed"
                ])
                if not is_network_error:
                    # Don't retry on auth errors, invalid symbol, etc.
                    raise
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"API call failed (attempt {attempt+1}/{max_retries}), "
                                   f"retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API call failed after {max_retries} attempts: {e}")
        raise last_error

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 200) -> pd.DataFrame:
        """
        Fetch historical klines (candlesticks). Auto-retries on network errors.

        Args:
            symbol: e.g. "BTCUSDT"
            interval: "1m","5m","15m","1h","4h","1d","1w"
            limit: number of candles (max 1500)

        Returns:
            DataFrame indexed by open time with columns: open, high, low, close, volume.
        """
        if _CONNECTOR == "binance-futures-connector":
            raw = self._retry_api_call(self.client.klines, symbol=symbol, interval=interval, limit=limit)
        else:
            raw = self._retry_api_call(self.client.futures_klines, symbol=symbol, interval=interval, limit=limit)

        cols = ["open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"]
        df = pd.DataFrame(raw, columns=cols)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        return df[["open", "high", "low", "close", "volume"]]

    def get_mark_price(self, symbol: str) -> float:
        """Get current mark price for a symbol. Auto-retries on network errors."""
        if _CONNECTOR == "binance-futures-connector":
            data = self._retry_api_call(self.client.mark_price, symbol=symbol)
            if isinstance(data, list):
                data = data[0]
            return float(data["markPrice"])
        else:
            data = self._retry_api_call(self.client.futures_mark_price, symbol=symbol)
            return float(data["markPrice"])

    # ---------- Account ----------

    def get_balance(self) -> float:
        """Get USDT balance available for trading. Auto-retries on network errors."""
        if _CONNECTOR == "binance-futures-connector":
            acct = self._retry_api_call(self.client.balance)
            for item in acct:
                if item.get("asset") == "USDT":
                    return float(item.get("availableBalance", 0))
            return 0.0
        else:
            acct = self._retry_api_call(self.client.futures_account)
            for item in acct.get("assets", []):
                if item.get("asset") == "USDT":
                    return float(item.get("availableBalance", 0))
            return 0.0

    def get_position(self, symbol: str) -> Position:
        """Get current position for a symbol using /fapi/v2/positionRisk. Auto-retries."""
        if _CONNECTOR == "binance-futures-connector":
            try:
                positions = self._retry_api_call(self.client.get_position_risk, symbol=symbol)
            except Exception as e:
                logger.warning("get_position_risk failed: %s. Returning NONE.", e)
                return Position(symbol, "NONE", 0.0, 0.0, 0.0, 0.0, 1)
            if not positions:
                return Position(symbol, "NONE", 0.0, 0.0, 0.0, 0.0, 1)
            p = positions[0]
            amt = float(p.get("positionAmt", 0))
            side = "LONG" if amt > 0 else ("SHORT" if amt < 0 else "NONE")
            return Position(
                symbol=symbol,
                side=side,
                size=amt,
                entry_price=float(p.get("entryPrice", 0)),
                mark_price=float(p.get("markPrice", 0)),
                unrealized_pnl=float(p.get("unRealizedProfit", 0)),
                leverage=int(float(p.get("leverage", 1))),
            )
        else:
            positions = self.client.futures_position_information(symbol=symbol)
            if not positions:
                return Position(symbol, "NONE", 0.0, 0.0, 0.0, 0.0, 1)
            p = positions[0]
            amt = float(p.get("positionAmt", 0))
            side = "LONG" if amt > 0 else ("SHORT" if amt < 0 else "NONE")
            return Position(
                symbol=symbol,
                side=side,
                size=amt,
                entry_price=float(p.get("entryPrice", 0)),
                mark_price=float(p.get("markPrice", 0)),
                unrealized_pnl=float(p.get("unRealizedProfit", 0)),
                leverage=int(float(p.get("leverage", 1))),
            )

    # ---------- Orders ----------

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set leverage for a symbol (1-125). Auto-adjusts if leverage
        exceeds the symbol's max allowed leverage (error -4028)."""
        leverage = max(1, min(125, int(leverage)))
        try:
            if _CONNECTOR == "binance-futures-connector":
                resp = self.client.change_leverage(symbol=symbol, leverage=leverage)
            else:
                resp = self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info("Leverage set to %dx for %s", leverage, symbol)
            return {"success": True, "leverage": leverage, "raw": resp}
        except Exception as e:
            msg = str(e)
            # Auto-fix: Leverage too high for this coin → reduce and retry
            if "-4028" in msg or "not valid" in msg.lower():
                # Try progressively lower leverage
                for try_lev in [75, 50, 25, 20, 10, 5, 3, 1]:
                    if try_lev >= leverage:
                        continue
                    try:
                        if _CONNECTOR == "binance-futures-connector":
                            resp = self.client.change_leverage(symbol=symbol, leverage=try_lev)
                        else:
                            resp = self.client.futures_change_leverage(symbol=symbol, leverage=try_lev)
                        logger.info("Leverage auto-adjusted to %dx for %s (requested %dx)",
                                    try_lev, symbol, leverage)
                        return {"success": True, "leverage": try_lev, "raw": resp,
                                "adjusted": True, "original": leverage}
                    except Exception:
                        continue
                logger.error("Could not set any leverage for %s", symbol)
                return {"success": False, "error": f"Leverage set nahi ho saka (tried 1-{leverage}x): {msg}"}
            # Symbol closed/delisted
            if "-4141" in msg or "Symbol is closed" in msg:
                return {"success": False, "error": f"Symbol {symbol} band/closed hai (delisted). Isko coins list se hatao."}
            # Binance throws if leverage is unchanged; treat as success
            if "No need to change leverage" in msg or "leverage not changed" in msg.lower() \
               or "-4046" in msg:
                return {"success": True, "leverage": leverage, "raw": msg}
            logger.error("Failed to set leverage: %s", e)
            return {"success": False, "error": msg}

    def get_symbol_filters(self, symbol: str) -> dict:
        """Fetch exchange info filters (LOT_SIZE step, min qty, PRICE_FILTER tick) for a symbol.
        Caches results to avoid repeated API calls.

        Returns:
            dict with keys: step_size, min_qty, tick_size, max_qty
            Falls back to defaults if API fails.
        """
        symbol = symbol.upper()
        if symbol in self._exchange_info_cache:
            return self._exchange_info_cache[symbol]

        defaults = {
            "step_size": 0.001,
            "min_qty": 0.001,
            "max_qty": 1e9,
            "tick_size": 0.01,
        }
        try:
            if _CONNECTOR == "binance-futures-connector":
                info = self.client.exchange_info()
            else:
                info = self.client.futures_exchange_info()

            for s in info.get("symbols", []):
                if s.get("symbol") == symbol:
                    filters = {f["filterType"]: f for f in s.get("filters", [])}
                    lot = filters.get("LOT_SIZE", {})
                    price = filters.get("PRICE_FILTER", {})
                    result = {
                        "step_size": float(lot.get("stepSize", 0.001)),
                        "min_qty": float(lot.get("minQty", 0.001)),
                        "max_qty": float(lot.get("maxQty", 1e9)),
                        "tick_size": float(price.get("tickSize", 0.01)),
                    }
                    self._exchange_info_cache[symbol] = result
                    logger.info("Symbol filters for %s: %s", symbol, result)
                    return result
            # Symbol not found in exchange info - use defaults
            self._exchange_info_cache[symbol] = defaults
            return defaults
        except Exception as e:
            logger.warning("Failed to fetch exchange_info for %s: %s. Using defaults.", symbol, e)
            self._exchange_info_cache[symbol] = defaults
            return defaults

    @staticmethod
    def _round_to_step(value: float, step: float) -> float:
        """Round value down to the nearest multiple of step."""
        if step <= 0:
            return value
        # Determine decimal places from step
        import math
        decimals = max(0, int(math.ceil(-math.log10(step))))
        rounded = math.floor(value / step) * step
        return round(rounded, decimals)

    def place_market_order(self, symbol: str, side: str, quantity: float,
                           reduce_only: bool = False) -> dict:
        """
        Place a MARKET order. Automatically rounds quantity to the symbol's
        LOT_SIZE step size to avoid Binance error -1111 (Precision over maximum).

        Args:
            symbol: e.g. "BTCUSDT"
            side: "BUY" or "SELL"
            quantity: base-asset quantity (>0)
            reduce_only: if True, only reduces existing position (for exits)

        Returns:
            dict with success flag and order info.
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            return {"success": False, "error": f"Invalid side: {side}"}
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be > 0"}

        # Fetch symbol filters and round quantity properly
        try:
            filters = self.get_symbol_filters(symbol)
            step = filters["step_size"]
            min_qty = filters["min_qty"]
            quantity = self._round_to_step(quantity, step)
            if quantity < min_qty:
                return {"success": False,
                        "error": f"Quantity {quantity} below min_qty {min_qty} for {symbol}"}
        except Exception as e:
            logger.warning("Could not apply step size rounding for %s: %s. Using raw qty.", symbol, e)
            quantity = round(quantity, 6)

        try:
            if _CONNECTOR == "binance-futures-connector":
                kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": quantity,
                }
                if reduce_only:
                    kwargs["reduceOnly"] = "true"
                resp = self.client.new_order(**kwargs)
            else:
                resp = self.client.futures_create_order(
                    symbol=symbol, side=side, type="MARKET",
                    quantity=quantity, reduceOnly=reduce_only,
                )

            oid = resp.get("orderId", "?") if isinstance(resp, dict) else "?"
            logger.info("Order placed: %s %s qty=%s reduceOnly=%s -> orderId=%s",
                        side, symbol, quantity, reduce_only, oid)
            return {"success": True, "order": resp, "quantity": quantity}
        except Exception as e:
            logger.error("Order failed: %s", e)
            return {"success": False, "error": str(e), "quantity": quantity}

    def close_position(self, symbol: str) -> dict:
        """Close the current position for the symbol using reduceOnly market order."""
        pos = self.get_position(symbol)
        if pos.side == "NONE" or pos.size == 0:
            return {"success": True, "message": "No position to close"}
        close_side = "SELL" if pos.side == "LONG" else "BUY"
        return self.place_market_order(
            symbol=symbol,
            side=close_side,
            quantity=abs(pos.size),
            reduce_only=True,
        )

    def open_long(self, symbol: str, quantity: float,
                  sl_price: float = None, tp_price: float = None) -> dict:
        """Open a LONG position (or add to one).

        For Binance, SL/TP is placed AFTER the order fills via separate
        STOP_MARKET / TAKE_PROFIT_MARKET orders (Binance doesn't support
        attaching SL/TP to the entry order like WEEX does).
        The software watchdog in engine.py also monitors these.
        """
        result = self.place_market_order(symbol, "BUY", quantity, reduce_only=False)
        # If order succeeded and SL/TP provided, place them as separate orders
        if result.get("success") and (sl_price or tp_price):
            if sl_price and sl_price > 0:
                sl_result = self.place_stop_loss(symbol, "SELL", sl_price, quantity)
                if not sl_result.get("success"):
                    logger.warning(f"[{symbol}] SL order failed (software watchdog will back up): {sl_result.get('error')}")
            if tp_price and tp_price > 0:
                tp_result = self.place_take_profit(symbol, "SELL", tp_price, quantity)
                if not tp_result.get("success"):
                    logger.warning(f"[{symbol}] TP order failed (software watchdog will back up): {tp_result.get('error')}")
        return result

    def open_short(self, symbol: str, quantity: float,
                   sl_price: float = None, tp_price: float = None) -> dict:
        """Open a SHORT position (or add to one).

        For Binance, SL/TP is placed AFTER the order fills via separate
        STOP_MARKET / TAKE_PROFIT_MARKET orders.
        The software watchdog in engine.py also monitors these.
        """
        result = self.place_market_order(symbol, "SELL", quantity, reduce_only=False)
        if result.get("success") and (sl_price or tp_price):
            if sl_price and sl_price > 0:
                sl_result = self.place_stop_loss(symbol, "BUY", sl_price, quantity)
                if not sl_result.get("success"):
                    logger.warning(f"[{symbol}] SL order failed (software watchdog will back up): {sl_result.get('error')}")
            if tp_price and tp_price > 0:
                tp_result = self.place_take_profit(symbol, "BUY", tp_price, quantity)
                if not tp_result.get("success"):
                    logger.warning(f"[{symbol}] TP order failed (software watchdog will back up): {tp_result.get('error')}")
        return result

    # ---------- Stop Loss / Take Profit Orders ----------

    def place_stop_loss(self, symbol: str, side: str, stop_price: float, quantity: float) -> dict:
        """Place a STOP_MARKET order for Stop Loss.
        side: opposite of position side (e.g. 'SELL' for LONG position)."""
        try:
            filters = self.get_symbol_filters(symbol)
            tick = filters["tick_size"]
            stop_price = self._round_to_step(stop_price, tick)
            qty = self._round_to_step(quantity, filters["step_size"])
            if _CONNECTOR == "binance-futures-connector":
                resp = self.client.new_order(
                    symbol=symbol, side=side, type="STOP_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly="true",
                    workingType="MARK_PRICE",
                )
            else:
                resp = self.client.futures_create_order(
                    symbol=symbol, side=side, type="STOP_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly=True,
                    workingType="MARK_PRICE",
                )
            logger.info("SL placed: %s %s qty=%s stopPrice=%s -> orderId=%s",
                        side, symbol, qty, stop_price, resp.get("orderId"))
            return {"success": True, "order": resp}
        except Exception as e:
            logger.error("SL order failed: %s", e)
            return {"success": False, "error": str(e)}

    def place_take_profit(self, symbol: str, side: str, stop_price: float, quantity: float) -> dict:
        """Place a TAKE_PROFIT_MARKET order.
        side: opposite of position side (e.g. 'SELL' for LONG position)."""
        try:
            filters = self.get_symbol_filters(symbol)
            tick = filters["tick_size"]
            stop_price = self._round_to_step(stop_price, tick)
            qty = self._round_to_step(quantity, filters["step_size"])
            if _CONNECTOR == "binance-futures-connector":
                resp = self.client.new_order(
                    symbol=symbol, side=side, type="TAKE_PROFIT_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly="true",
                    workingType="MARK_PRICE",
                )
            else:
                resp = self.client.futures_create_order(
                    symbol=symbol, side=side, type="TAKE_PROFIT_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly=True,
                    workingType="MARK_PRICE",
                )
            logger.info("TP placed: %s %s qty=%s stopPrice=%s -> orderId=%s",
                        side, symbol, qty, stop_price, resp.get("orderId"))
            return {"success": True, "order": resp}
        except Exception as e:
            logger.error("TP order failed: %s", e)
            return {"success": False, "error": str(e)}

    def cancel_open_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol (used before placing new SL/TP)."""
        try:
            if _CONNECTOR == "binance-futures-connector":
                resp = self.client.cancel_open_orders(symbol=symbol)
            else:
                resp = self.client.futures_cancel_all_open_orders(symbol=symbol)
            return {"success": True, "raw": resp}
        except Exception as e:
            logger.error("Cancel orders failed: %s", e)
            return {"success": False, "error": str(e)}

    # ---------- Helpers ----------

    def compute_quantity(self, notional_usdt: float, price: float,
                         leverage: int, qty_step: float = 0.001) -> float:
        """
        Compute base-asset quantity from desired USDT notional exposure.

        quantity = notional_usdt / price
        (Leverage affects margin requirement, not position size, when
        `notional_usdt` represents the user's intended position value.)
        """
        if price <= 0:
            return 0.0
        raw_qty = notional_usdt / price
        stepped = round(raw_qty / qty_step) * qty_step
        return round(stepped, 6)

    def get_all_symbols(self) -> list:
        """Fetch ALL available USDT futures symbols from Binance.
        Returns list of symbol strings (e.g. ['BTCUSDT', 'ETHUSDT', ...])."""
        try:
            if _CONNECTOR == "binance-futures-connector":
                info = self._retry_api_call(self.client.exchange_info)
            else:
                info = self._retry_api_call(self.client.futures_exchange_info)
            symbols = []
            for s in info.get("symbols", []):
                if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL":
                    if s.get("status") == "TRADING":
                        symbols.append(s.get("symbol"))
            symbols.sort()
            logger.info(f"Fetched {len(symbols)} USDT perpetual symbols from Binance")
            return symbols
        except Exception as e:
            logger.error(f"Failed to fetch all symbols: {e}")
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
                    "DOTUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "UNIUSDT"]

    def test_connection(self) -> dict:
        """Test API connection by fetching balance. Returns detailed result."""
        try:
            balance = self.get_balance()
            return {
                "success": True,
                "message": f"Connected successfully! Balance: ${balance:.2f}",
                "balance": balance,
                "exchange": "binance",
                "demo": self.testnet,
            }
        except Exception as e:
            err_str = str(e)
            if "-2015" in err_str or "Invalid API-key" in err_str:
                cause = "API Key or Secret is invalid"
                fix = "Go to Binance Futures → API Management and create new keys"
            elif "-2014" in err_str or "Invalid JSON" in err_str:
                cause = "API key format is wrong"
                fix = "Make sure you copied the full API key and secret without extra spaces"
            elif "timeout" in err_str.lower():
                cause = "Network timeout"
                fix = "Check your internet connection"
            else:
                cause = "Unknown error"
                fix = "Check the bot logs for details"
            return {
                "success": False,
                "error": err_str,
                "cause": cause,
                "fix": fix,
            }
