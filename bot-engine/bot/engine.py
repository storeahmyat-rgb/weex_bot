"""
Bot Engine - The brain that ties strategy + trader together.

Runs in a background thread per symbol, polls klines on the configured interval,
runs the strategy, and executes trades based on the signal.

Supports:
- Multi-symbol trading (parallel threads, one per coin)
- Amount mode: 'fixed' USDT  OR  'percent' of wallet balance
- Emits events via Flask-SocketIO for the UI to consume.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from .strategy import EMAQuadStrategy, Signal, StrategyResult
from .trader import BinanceFuturesTrader
from .notifier import Notifier

logger = logging.getLogger(__name__)


def get_trader(config: dict):
    """Factory: return the correct trader based on config['exchange']."""
    exchange = (config.get("exchange") or "binance").lower()
    if exchange == "weex":
        from .weex_trader import WEEXFuturesTrader
        return WEEXFuturesTrader(
            api_key=config["api_key"],
            api_secret=config["api_secret"],
            passphrase=config.get("api_passphrase", ""),
            testnet=config.get("testnet", True),
        )
    # Default: Binance
    return BinanceFuturesTrader(
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        testnet=config.get("testnet", True),
    )


class SymbolWorker(threading.Thread):
    """One worker per symbol. Runs strategy loop independently."""

    def __init__(self, engine, symbol: str, config: dict):
        super().__init__(daemon=True, name=f"worker-{symbol}")
        self.engine = engine
        self.symbol = symbol
        self.config = config
        self.stop_event = threading.Event()
        self.last_signal = Signal.HOLD
        self.candles_processed = 0
        self.trades_today = 0
        self.last_check = None
        # Strict mode: bot only trades on FRESH crosses.
        self.waiting_for_new_cross = True
        # Track what position we THINK is open (for sync detection).
        self.expected_pos_side = None
        # ===== SOFTWARE SL/TP WATCHDOG STATE =====
        # When a position is open, these store the SL/TP prices.
        # Bot polls mark_price every tick and closes position if hit.
        # This works on ALL exchanges (no exchange-specific order types needed).
        self.sl_price = None       # Stop Loss price (None = no SL active)
        self.tp_price = None       # Take Profit price (None = no TP active)
        self.entry_price = None    # Entry price of current position
        self.position_side = None  # "LONG" / "SHORT" / None
        self._last_df = None  # Cache last klines DataFrame for instant chart update
        self._last_mark_price = None  # Cache last mark price
        self._last_cross_time = 0  # Timestamp of last cross (prevent rapid crosses)

    def run(self):
        poll_seconds = BotEngine._poll_seconds(self.config["timeframe"])
        self.engine._emit("log", {
            "level": "info",
            "msg": f"[{self.symbol}] Worker started. Polling every {poll_seconds}s."
        })
        try:
            # Pre-seed: fetch klines once to set strategy state
            df = self.engine.trader.get_klines(self.symbol, interval=self.config["timeframe"], limit=200)
            self._last_df = df
            if df is not None and len(df) >= 60:
                seed_result = self.engine.strategy.analyze(df)
                if seed_result:
                    self.engine._emit("log", {
                        "level": "info",
                        "msg": (f"[{self.symbol}] Startup: signal={seed_result.signal.value}, "
                                f"candles={len(df)}. Waiting for FRESH cross.")
                    })
                    # Emit chart data immediately for active symbol
                    if self.engine.active_symbol == self.symbol:
                        self.engine._emit("chart_data", {
                            "symbol": self.symbol,
                            "candles": self._candles_to_list(df),
                            "emas": self._emas_to_list(df),
                        })
                        indicators = self.engine.strategy.latest_indicators(df)
                        try:
                            mp = self.engine.trader.get_mark_price(self.symbol)
                        except Exception:
                            mp = float(df.iloc[-1]["close"])
                        self.engine._emit("indicators", {
                            "symbol": self.symbol,
                            **indicators,
                            "mark_price": mp,
                        })
                        self.engine._emit("log", {
                            "level": "success",
                            "msg": f"[{self.symbol}] ✅ Chart data sent ({len(df)} candles)"
                        })
            else:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{self.symbol}] Not enough candles ({len(df) if df is not None else 0}). Need 60+."
                })
        except Exception as e:
            logger.error(f"[{self.symbol}] Pre-seed FAILED: {e}")
            self.engine._emit("log", {
                "level": "error",
                "msg": f"[{self.symbol}] Pre-seed failed: {str(e)[:100]}"
            })

        while not self.stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"[{self.symbol}] tick error")
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{self.symbol}] tick error: {str(e)[:100]}"
                })
            for _ in range(poll_seconds):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        self.engine._emit("log", {
            "level": "info",
            "msg": f"[{self.symbol}] Worker stopped."
        })

    def _tick(self):
        cfg = self.config
        symbol = self.symbol
        timeframe = cfg["timeframe"]

        # Safety: if trader is None (after force stop), skip tick
        if self.engine.trader is None:
            return

        # 1. Fetch klines (with auto-retry inside trader)
        try:
            df = self.engine.trader.get_klines(symbol, interval=timeframe, limit=200)
            self._last_df = df  # Cache for instant chart update
        except Exception as e:
            logger.error(f"[{symbol}] Failed to fetch klines after retries: {e}")
            # Don't spam logs every tick - only log every 12th tick (~1 min)
            if self.candles_processed % 12 == 0:
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{symbol}] Klines fetch fail: {str(e)[:100]}. Chart empty - API error."
                })
            # Try to use cached df if available
            if self._last_df is not None:
                df = self._last_df
            else:
                return  # No cached data, skip this tick

        self.candles_processed += 1
        self.last_check = datetime.utcnow().isoformat()

        # 2. Compute indicators
        indicators = self.engine.strategy.latest_indicators(df)
        # Get mark price - use close price as fallback (mark price API may fail)
        try:
            mark_price = self.engine.trader.get_mark_price(symbol)
            if mark_price is None or mark_price <= 0:
                mark_price = float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0
            self._last_mark_price = mark_price
        except Exception as e:
            logger.warning(f"[{symbol}] mark_price fetch failed: {e}, using close price")
            mark_price = self._last_mark_price or float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0

        # 3. Push indicator update (ALWAYS for active symbol, even if bot just started)
        is_active = (self.engine.active_symbol == symbol or self.engine.active_symbol is None)
        if is_active:
            self.engine._emit("indicators", {
                "symbol": symbol,
                **indicators,
                "mark_price": mark_price,
            })

        # 4. Push chart data for the active/selected coin (EVERY TICK = live update)
        if is_active:
            candles = self._candles_to_list(df)
            emas = self._emas_to_list(df)
            if candles:
                self.engine._emit("chart_data", {
                    "symbol": symbol,
                    "candles": candles,
                    "emas": emas,
                })

        # 5. Position update
        try:
            pos = self.engine.trader.get_position(symbol)
        except Exception as e:
            logger.warning(f"[{symbol}] get_position failed: {e}")
            class DefaultPos:
                side = "NONE"; size = 0; entry_price = 0; mark_price = mark_price if 'mark_price' in dir() else 0.0
                unrealized_pnl = 0; leverage = 1
            pos = DefaultPos()

        # ===== SOFTWARE SL/TP WATCHDOG CHECK =====
        # Check if SL or TP has been hit BEFORE doing anything else.
        # This runs on every tick (5s) - fast enough to catch price moves.
        if pos.side != "NONE" and pos.size != 0 and pos.mark_price > 0:
            sl_hit, tp_hit, reason = self._check_software_sl_tp(pos)
            if sl_hit or tp_hit:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{symbol}] ⚡ {reason} -> closing position @ {pos.mark_price:.4f}"
                })
                # Calculate PnL
                entry = self.entry_price or pos.entry_price
                if pos.side == "LONG":
                    pnl_pct = (pos.mark_price - entry) / entry * 100 if entry > 0 else 0
                else:
                    pnl_pct = (entry - pos.mark_price) / entry * 100 if entry > 0 else 0
                close_side_label = pos.side
                # Close position
                close = self.engine.trader.close_position(symbol)
                self._log_order(close, f"[{symbol}] {reason}")
                if close.get("success"):
                    self.trades_today += 1
                    # Reset SL/TP state
                    self.sl_price = None
                    self.tp_price = None
                    self.entry_price = None
                    self.position_side = None
                    self.expected_pos_side = None
                    self.waiting_for_new_cross = True
                    self.engine.strategy.reset_cross_state()
                    # Notification
                    try:
                        if sl_hit:
                            self.engine.notifier.notify_sl(
                                symbol, close_side_label, entry, pos.mark_price, pnl_pct
                            )
                        elif tp_hit:
                            self.engine.notifier.notify_tp(
                                symbol, close_side_label, entry, pos.mark_price, pnl_pct,
                                {"ema_8": e8 if 'e8' in dir() else 0,
                                 "ema_13": e13 if 'e13' in dir() else 0,
                                 "ema_21": e21 if 'e21' in dir() else 0,
                                 "ema_55": e55 if 'e55' in dir() else 0}
                            )
                    except Exception as e:
                        logger.error("SL/TP notification failed: %s", e)
                # Position closed - emit signal for UI and return
                result = self.engine.strategy.analyze(df)
                if result:
                    self.engine._emit("signal", {
                        "symbol": symbol,
                        "signal": result.signal.value,
                        "reason": result.reason,
                        "emas": {"ema_8": result.ema_8, "ema_13": result.ema_13,
                                 "ema_21": result.ema_21, "ema_55": result.ema_55},
                    })
                return

        # ===== POSITION SYNC CHECK =====
        actual_side = pos.side if (pos.side in ("LONG", "SHORT") and pos.size != 0) else "NONE"
        if actual_side != self.expected_pos_side:
            if self.expected_pos_side is not None and actual_side == "NONE":
                # Bot expected a position but it's gone now (user closed or SL/TP hit on exchange)
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ Position closed (SL/TP hit on exchange or manual close). "
                            f"Bot expected {self.expected_pos_side} but found NONE. "
                            f"Waiting for NEW cross before next trade.")
                })
                self.expected_pos_side = None
                self.waiting_for_new_cross = True  # Strict mode: must wait for fresh cross
                self.engine.strategy.reset_cross_state()
            elif actual_side != "NONE" and self.expected_pos_side != actual_side:
                # Position flipped or new opposite position opened externally
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ External trade detected! "
                            f"Bot expected {self.expected_pos_side or 'NONE'} but found {actual_side}. "
                            f"Syncing state to {actual_side}.")
                })
                self.expected_pos_side = actual_side
                try:
                    self.engine.notifier.send(
                        f"⚠️ External Trade Detected - {symbol}",
                        f"Position changed externally!\n\n"
                        f"Symbol: {symbol}\n"
                        f"Bot expected: {self.expected_pos_side or 'NONE'}\n"
                        f"Actual: {actual_side}\n"
                        f"Size: {pos.size}\n\n"
                        f"Bot ne apna state sync kar diya hai."
                    )
                except Exception as e:
                    logger.error("External trade notification failed: %s", e)

        # ===== AUTO-RESTORE SL/TP ON STARTUP =====
        # If there's an open position but SL/TP is not set (e.g., after bot restart),
        # automatically set SL/TP based on entry price from exchange
        if actual_side != "NONE" and self.sl_price is None and self.tp_price is None:
            entry = pos.entry_price
            if entry > 0:
                sl_pct_val = float(cfg.get("stop_loss_pct", 2))
                tp_pct_val = sl_pct_val * 3
                self._set_software_sl_tp(symbol, actual_side, entry, sl_pct_val, tp_pct_val)
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ AUTO-RESTORED SL/TP for existing {actual_side} position | "
                            f"Entry={entry:.4f} | SL={self.sl_price:.4f} | TP={self.tp_price:.4f} | "
                            f"Bot restart ke baad SL/TP auto-set hua.")
                })

        self.engine._emit("position", {
            "symbol": symbol,
            "side": pos.side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "mark_price": pos.mark_price,
            "unrealized_pnl": pos.unrealized_pnl,
            "leverage": pos.leverage,
        })

        # 6. Strategy analysis
        result = self.engine.strategy.analyze(df)
        if result is None:
            self.engine._emit("log", {
                "level": "warn",
                "msg": f"[{symbol}] Not enough data yet (need >= {self.engine.strategy.ema_long + 5} candles)."
            })
            return

        signal = result.signal
        mode = cfg.get("mode", "both")
        e8, e13, e21, e55 = result.ema_8, result.ema_13, result.ema_21, result.ema_55

        # Emit signal to UI (for indicator panel) - but DON'T spam logs
        # Only emit if signal changed from last tick
        signal_changed = (signal != self.last_signal)
        self.engine._emit("signal", {
            "symbol": symbol,
            "signal": signal.value,
            "reason": result.reason,
            "emas": {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55},
            "just_crossed": result.just_crossed,
        })

        # Signal notification ONLY on FRESH cross (instant, no delay)
        if result.just_crossed and signal in (Signal.BUY, Signal.SELL) and signal_changed:
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 📊 FRESH {signal.value} CROSS detected! "
                        f"EMA55 {'BOTTOM' if signal == Signal.BUY else 'TOP'} | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f}")
            })
            try:
                self.engine.notifier.notify_signal(
                    symbol, signal.value, result.reason,
                    {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55}
                )
            except Exception as e:
                logger.error("Signal notification failed: %s", e)

        # ===================================================================
        # STRICT MODE ENTRY LOGIC (SILENT when waiting)
        # ===================================================================
        # Rules:
        # 1. Bot ONLY trades on a FRESH cross (just_crossed = True)
        # 2. If bot just started and line is already crossed → NO TRADE (wait silently)
        # 3. After a trade closes (SL/TP hit), waiting_for_new_cross = True
        # 4. Once a fresh cross happens, waiting_for_new_cross = False → trade allowed
        # 5. SL and TP set immediately via software watchdog (1:3 RR)
        # 6. Bot is SILENT while waiting - no spam logs
        # ===================================================================

        # If we already have an open position, do nothing (SL/TP handled by watchdog)
        if pos.side != "NONE" and pos.size != 0:
            return

        # No position. Check if we should enter a new trade.
        # STRICT: Only enter on a FRESH cross.
        if not result.just_crossed:
            # SILENT: Don't log anything when waiting (no spam!)
            # Only log ONCE when transitioning to waiting state
            if self.waiting_for_new_cross and not hasattr(self, '_waiting_logged'):
                self._waiting_logged = True
                self.engine._emit("log", {
                    "level": "info",
                    "msg": (f"[{symbol}] ⏳ Waiting for FRESH cross before entering trade... (silent mode)")
                })
            return

        # Fresh cross happened! Check cooldown (min 30s between crosses)
        import time as _time
        now = _time.time()
        if now - self._last_cross_time < 30:
            # Too soon after last cross - ignore (prevents rapid false crosses)
            return
        self._last_cross_time = now

        # Clear waiting state.
        self.waiting_for_new_cross = False
        if hasattr(self, '_waiting_logged'):
            delattr(self, '_waiting_logged')

        # Check mode allows this trade
        if signal == Signal.BUY and mode not in ("long", "both"):
            self.engine._emit("log", {
                "level": "info",
                "msg": f"[{symbol}] Fresh BUY cross but mode is '{mode}' - skipping LONG entry."
            })
            return
        if signal == Signal.SELL and mode not in ("short", "both"):
            self.engine._emit("log", {
                "level": "info",
                "msg": f"[{symbol}] Fresh SELL cross but mode is '{mode}' - skipping SHORT entry."
            })
            return

        # Compute trade size
        trade_size = self._compute_trade_size(mark_price, cfg.get("leverage", 10))
        if trade_size <= 0:
            if self.candles_processed % 12 == 0:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{symbol}] Trade size 0 - wallet balance too low for 1% trade. Use Fixed USDT mode instead."
                })
            return

        # Check minimum quantity for this symbol
        try:
            filters = self.engine.trader.get_symbol_filters(symbol)
            min_qty = filters.get("min_qty", 0.001)
            if trade_size < min_qty:
                if self.candles_processed % 12 == 0:
                    self.engine._emit("log", {
                        "level": "warn",
                        "msg": f"[{symbol}] Quantity {trade_size:.6f} below min {min_qty}. Increase amount or use Fixed USDT."
                    })
                return
        except Exception:
            pass  # If we can't check filters, try anyway

        # ===================================================================
        # ENTER TRADE + PLACE SL/TP IMMEDIATELY (STRICT 1:3 RR)
        # ===================================================================
        # SL is HARDCODED - user cannot disable it. Min 0.5%, default 2%.
        # TP is ALWAYS SL × 3 (1:3 Risk-Reward ratio, hardcoded).
        # SL/TP placed on Binance exchange immediately after entry.
        # ===================================================================
        STRICT_SL_MIN = 0.5
        # Get SL from config - don't use 'or' because 0 is valid input
        sl_pct = cfg.get("stop_loss_pct", 2)
        try:
            sl_pct = float(sl_pct)
        except (TypeError, ValueError):
            sl_pct = 2.0
        if sl_pct < STRICT_SL_MIN:
            sl_pct = STRICT_SL_MIN
            self.engine._emit("log", {
                "level": "warn",
                "msg": f"[{symbol}] SL too low (was {sl_pct}%), set to minimum {STRICT_SL_MIN}%"
            })
        # Hardcoded 1:3 RR - TP always = SL × 3 (no override possible)
        tp_pct = sl_pct * 3

        if signal == Signal.BUY:
            # Open LONG
            # Calculate SL/TP prices from mark_price (will use actual entry after fill)
            sl_price_long = mark_price * (1 - sl_pct / 100)
            tp_price_long = mark_price * (1 + tp_pct / 100)
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 🟢 FRESH BUY cross -> opening LONG qty={trade_size:.6f} @ ~{mark_price:.4f} | "
                        f"SL={sl_pct}% ({sl_price_long:.4f}) TP={tp_pct}% ({tp_price_long:.4f}) STRICT 1:3 RR | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f}")
            })
            # Pass SL/TP prices to open_long — WEEX will attach them to the order
            # Binance will place separate STOP_MARKET orders after fill
            try:
                order = self.engine.trader.open_long(symbol, trade_size,
                                                     sl_price=sl_price_long,
                                                     tp_price=tp_price_long)
            except TypeError:
                # Fallback for old trader signature (no sl_price/tp_price params)
                order = self.engine.trader.open_long(symbol, trade_size)
            actual_qty = order.get("quantity", trade_size)
            self._log_order(order, f"[{symbol}] OPEN LONG qty={actual_qty:.6f}")
            if order.get("success"):
                self.trades_today += 1
                self.last_signal = Signal.BUY
                self.expected_pos_side = "LONG"
                # Get ACTUAL entry price from position (not mark_price)
                actual_entry = self._get_actual_entry_price(symbol, mark_price)
                # ALSO set software watchdog as backup (in case exchange SL/TP fails)
                self._set_software_sl_tp(symbol, "LONG", actual_entry, sl_pct, tp_pct)
                # Log exchange SL/TP status
                if order.get("sl_price") or order.get("tp_price"):
                    self.engine._emit("log", {
                        "level": "success",
                        "msg": (f"[{symbol}] ✅ Exchange SL/TP attached | "
                                f"SL={order.get('sl_price', 'N/A')} | "
                                f"TP={order.get('tp_price', 'N/A')} | "
                                f"(+ software watchdog backup active)")
                    })
                try:
                    self.engine.notifier.notify_trade_open(
                        symbol, "LONG", actual_qty, actual_entry,
                        {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55}
                    )
                except Exception as e:
                    logger.error("Trade open notification failed: %s", e)

        elif signal == Signal.SELL:
            # Open SHORT
            # For SHORT: SL above entry, TP below entry
            sl_price_short = mark_price * (1 + sl_pct / 100)
            tp_price_short = mark_price * (1 - tp_pct / 100)
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 🔴 FRESH SELL cross -> opening SHORT qty={trade_size:.6f} @ ~{mark_price:.4f} | "
                        f"SL={sl_pct}% ({sl_price_short:.4f}) TP={tp_pct}% ({tp_price_short:.4f}) STRICT 1:3 RR | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f}")
            })
            try:
                order = self.engine.trader.open_short(symbol, trade_size,
                                                      sl_price=sl_price_short,
                                                      tp_price=tp_price_short)
            except TypeError:
                order = self.engine.trader.open_short(symbol, trade_size)
            actual_qty = order.get("quantity", trade_size)
            self._log_order(order, f"[{symbol}] OPEN SHORT qty={actual_qty:.6f}")
            if order.get("success"):
                self.trades_today += 1
                self.last_signal = Signal.SELL
                self.expected_pos_side = "SHORT"
                # Get ACTUAL entry price from position (not mark_price)
                actual_entry = self._get_actual_entry_price(symbol, mark_price)
                # ALSO set software watchdog as backup
                self._set_software_sl_tp(symbol, "SHORT", actual_entry, sl_pct, tp_pct)
                # Log exchange SL/TP status
                if order.get("sl_price") or order.get("tp_price"):
                    self.engine._emit("log", {
                        "level": "success",
                        "msg": (f"[{symbol}] ✅ Exchange SL/TP attached | "
                                f"SL={order.get('sl_price', 'N/A')} | "
                                f"TP={order.get('tp_price', 'N/A')} | "
                                f"(+ software watchdog backup active)")
                    })
                try:
                    self.engine.notifier.notify_trade_open(
                        symbol, "SHORT", actual_qty, actual_entry,
                        {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55}
                    )
                except Exception as e:
                    logger.error("Trade open notification failed: %s", e)

    def _get_actual_entry_price(self, symbol: str, fallback: float) -> float:
        """Get actual entry price from Binance position after order fill."""
        try:
            pos = self.engine.trader.get_position(symbol)
            if pos.entry_price > 0:
                return pos.entry_price
        except Exception as e:
            logger.warning(f"[{symbol}] Could not fetch actual entry price: {e}")
        return fallback

    def _set_software_sl_tp(self, symbol: str, side: str, entry_price: float,
                            sl_pct: float, tp_pct: float):
        """Set SL/TP prices in memory (software watchdog).
        Bot will monitor mark_price and close position when SL/TP is hit.
        This works on ALL exchanges - no exchange-specific order types needed."""
        if entry_price <= 0:
            self.engine._emit("log", {
                "level": "error",
                "msg": f"[{symbol}] ❌ Cannot set SL/TP - invalid entry price"
            })
            return

        if side == "LONG":
            self.sl_price = entry_price * (1 - sl_pct / 100)
            self.tp_price = entry_price * (1 + tp_pct / 100)
        else:  # SHORT
            self.sl_price = entry_price * (1 + sl_pct / 100)
            self.tp_price = entry_price * (1 - tp_pct / 100)

        self.entry_price = entry_price
        self.position_side = side

        self.engine._emit("log", {
            "level": "success",
            "msg": (f"[{symbol}] ✅ Software SL/TP set | "
                    f"Entry={entry_price:.4f} | "
                    f"SL={self.sl_price:.4f} ({sl_pct}%) | "
                    f"TP={self.tp_price:.4f} ({tp_pct}%) | "
                    f"RR=1:3 | Side={side}")
        })

    def _check_software_sl_tp(self, pos) -> tuple:
        """Check if software SL or TP has been hit.
        Returns: (sl_hit: bool, tp_hit: bool, reason: str)"""
        if self.sl_price is None or self.tp_price is None:
            return (False, False, "")

        mark = pos.mark_price
        side = pos.side

        # CRITICAL: If mark_price is 0 or invalid, skip SL/TP check
        # (prevents false SL trigger when mark_price fetch fails)
        if mark is None or mark <= 0:
            return (False, False, "")

        if side == "LONG":
            # SL: price dropped below SL price
            if mark <= self.sl_price:
                pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (True, False, f"⚡ SL HIT (price {mark:.4f} <= SL {self.sl_price:.4f}, PnL={pnl_pct:+.2f}%)")
            # TP: price rose above TP price
            if mark >= self.tp_price:
                pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (False, True, f"⚡ TP HIT (price {mark:.4f} >= TP {self.tp_price:.4f}, PnL={pnl_pct:+.2f}%)")
        else:  # SHORT
            # SL: price rose above SL price
            if mark >= self.sl_price:
                pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (True, False, f"⚡ SL HIT (price {mark:.4f} >= SL {self.sl_price:.4f}, PnL={pnl_pct:+.2f}%)")
            # TP: price dropped below TP price
            if mark <= self.tp_price:
                pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (False, True, f"⚡ TP HIT (price {mark:.4f} <= TP {self.tp_price:.4f}, PnL={pnl_pct:+.2f}%)")

        return (False, False, "")

    def _compute_trade_size(self, price: float, leverage: int) -> float:
        """
        Compute base-asset quantity based on amount_mode:
        - 'fixed'  : use cfg['amount'] as USDT position size
        - 'percent': use (balance * amount_pct / 100) as USDT position size
        """
        cfg = self.config
        amount_mode = cfg.get("amount_mode", "fixed")

        if amount_mode == "percent":
            try:
                balance = self.engine.trader.get_balance()
            except Exception:
                balance = 0.0
            pct = float(cfg.get("amount_pct", 10))
            notional = balance * pct / 100.0
        else:
            notional = float(cfg.get("amount", 100))

        return self.engine.trader.compute_quantity(notional, price, leverage)

    def _candles_to_list(self, df, n=200):
        """Convert df candles to list of dicts for UI chart."""
        if df is None or len(df) == 0:
            return []
        tail = df.tail(n)
        out = []
        for ts, row in tail.iterrows():
            out.append({
                "time": int(ts.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        return out

    def _emas_to_list(self, df, n=200):
        """Convert EMA columns to dict of lists for UI chart."""
        enriched = self.engine.strategy.indicators.compute(df)
        tail = enriched.tail(n)
        out = {}
        for col, key in [("ema_8", "ema8"), ("ema_13", "ema13"),
                         ("ema_21", "ema21"), ("ema_55", "ema55")]:
            out[key] = [
                {"time": int(ts.timestamp()), "value": float(v)}
                for ts, v in zip(tail.index, tail[col])
                if not (v != v)  # filter NaN
            ]
        return out

    def _log_order(self, result, label):
        if result.get("success"):
            order = result.get("order", {})
            oid = order.get("orderId", "?") if isinstance(order, dict) else "?"
            self.engine._emit("log", {
                "level": "success",
                "msg": f"{label} OK | orderId={oid}"
            })
        else:
            self.engine._emit("log", {
                "level": "error",
                "msg": f"{label} FAILED | {result.get('error')}"
            })


class MonitorThread(threading.Thread):
    """Always-on background thread that fetches live data (balance, mark_price,
    chart, indicators) for the active symbol — even when the bot is STOPPED.

    This means as soon as user saves settings (with API keys), they see:
    - Real WEEX/Binance balance (e.g. 20,000 USDT on WEEX demo)
    - Live mark price for the selected coin
    - Live chart with EMA indicators
    - Open positions (if any)

    The thread polls every 5s for prices/indicators, 10s for balance,
    60s for chart refresh.
    """

    def __init__(self, engine, config: dict):
        super().__init__(daemon=True, name="monitor")
        self.engine = engine
        self.config = config
        self.stop_event = threading.Event()
        self._last_chart_emit = 0

    def run(self):
        exchange = (self.config.get("exchange") or "binance").upper()
        env_label = "DEMO" if exchange == "WEEX" and self.config.get("testnet") else \
                    ("TESTNET" if self.config.get("testnet") else "MAINNET")
        self.engine._emit("log", {
            "level": "info",
            "msg": f"🔌 MONITOR connected to {exchange} ({env_label}) — live data is now flowing"
        })

        first_run = True
        while not self.stop_event.is_set():
            try:
                self._tick(first_run)
                first_run = False
            except Exception as e:
                logger.error(f"Monitor tick error: {e}")
                if first_run:
                    self.engine._emit("log", {
                        "level": "error",
                        "msg": f"❌ MONITOR error: {str(e)[:120]}. Check API keys/Passphrase."
                    })
                    first_run = False
            # Poll every 5s (compromise between responsiveness and rate limits)
            for _ in range(5):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        self.engine._emit("log", {
            "level": "info",
            "msg": "🔌 MONITOR disconnected"
        })

    def _tick(self, first_run=False):
        """One polling iteration. Fetches data for the active symbol only."""
        cfg = self.config
        symbol = self.engine.active_symbol or cfg.get("symbol", "BTCUSDT")
        timeframe = cfg.get("timeframe", "5m")

        if self.engine.monitor_trader is None:
            return

        # 1. Fetch balance (every tick — it's fast and shows real-time state)
        try:
            balance = self.engine.monitor_trader.get_balance()
            self.engine._emit("balance", {
                "balance": float(balance),
                "exchange": cfg.get("exchange", "binance"),
                "testnet": cfg.get("testnet", True),
            })
        except Exception as e:
            if first_run:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"⚠️ Balance fetch failed: {str(e)[:100]}"
                })

        # 2. Fetch klines + indicators + mark price for active symbol
        try:
            df = self.engine.monitor_trader.get_klines(symbol, interval=timeframe, limit=200)
        except Exception as e:
            if first_run:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"⚠️ Chart fetch failed for {symbol}: {str(e)[:100]}"
                })
            return

        if df is None or len(df) == 0:
            return

        # Mark price (prefer mark_price API, fallback to last close)
        try:
            mark_price = self.engine.monitor_trader.get_mark_price(symbol)
            if mark_price is None or mark_price <= 0:
                mark_price = float(df.iloc[-1]["close"])
        except Exception:
            mark_price = float(df.iloc[-1]["close"])

        # Indicators (EMA 8, 13, 21, 55)
        try:
            indicators = self.engine.strategy.latest_indicators(df)
        except Exception:
            indicators = {"ema_8": 0, "ema_13": 0, "ema_21": 0, "ema_55": 0}

        # Emit indicators
        self.engine._emit("indicators", {
            "symbol": symbol,
            **indicators,
            "mark_price": mark_price,
        })

        # Emit chart data (throttle to every 30s — klines don't change fast)
        now = time.time()
        if now - self._last_chart_emit > 30 or first_run:
            candles = self._candles_to_list(df)
            emas = self._emas_to_list(df)
            if candles:
                self.engine._emit("chart_data", {
                    "symbol": symbol,
                    "candles": candles,
                    "emas": emas,
                })
                self._last_chart_emit = now

        # Emit position info for active symbol
        try:
            pos = self.engine.monitor_trader.get_position(symbol)
            self.engine._emit("position", {
                "symbol": symbol,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price if pos.mark_price > 0 else mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": pos.leverage,
            })
        except Exception:
            pass

    def _candles_to_list(self, df, n=200):
        if df is None or len(df) == 0:
            return []
        tail = df.tail(n)
        out = []
        for ts, row in tail.iterrows():
            out.append({
                "time": int(ts.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        return out

    def _emas_to_list(self, df, n=200):
        try:
            enriched = self.engine.strategy.indicators.compute(df)
        except Exception:
            return {}
        tail = enriched.tail(n)
        out = {}
        for col, key in [("ema_8", "ema8"), ("ema_13", "ema13"),
                         ("ema_21", "ema21"), ("ema_55", "ema55")]:
            out[key] = [
                {"time": int(ts.timestamp()), "value": float(v)}
                for ts, v in zip(tail.index, tail[col])
                if not (v != v)  # filter NaN
            ]
        return out


class BotEngine:
    """Background trading engine supporting multi-symbol trading."""

    def __init__(self, socketio, config: dict):
        self.socketio = socketio
        self.config = config
        self.trader: Optional[BinanceFuturesTrader] = None
        self.strategy = EMAQuadStrategy()
        self.notifier = Notifier(config)
        self.workers: dict[str, SymbolWorker] = {}
        self.lock = threading.Lock()
        self.is_running = False
        self.active_symbol = None  # Which coin the UI is currently viewing
        # ===== MONITOR MODE =====
        # Always-on background thread that fetches balance, mark_price, chart
        # for the active symbol. Works even when bot is STOPPED, so user can
        # see live data immediately after saving settings.
        self.monitor_thread: Optional[MonitorThread] = None
        self.monitor_trader = None  # separate trader instance for monitor

    # ---------- Lifecycle ----------

    # ===== MONITOR MODE METHODS =====
    # Monitor = always-on background thread that fetches live data (balance,
    # mark_price, chart) for the active symbol. Works even when bot is STOPPED.
    # Triggered automatically after user saves settings (see /api/config POST).

    def start_monitor(self, config: dict) -> dict:
        """Start (or restart) the monitor with the given config.

        Called automatically by app.py after /api/config POST (Save button).
        Also called when user switches exchange or demo/live toggle.

        If API keys are missing, returns success=False (no monitor started).
        If monitor is already running, stops it first then starts new one.
        """
        # Stop existing monitor if any
        self.stop_monitor()

        # Check API credentials
        api_key = config.get("api_key", "").strip()
        api_secret = config.get("api_secret", "").strip()
        if not api_key or not api_secret:
            return {"success": False, "error": "API keys not set — monitor not started"}
        if config.get("exchange") == "weex":
            if not config.get("api_passphrase", "").strip():
                return {"success": False, "error": "WEEX Passphrase not set — monitor not started"}

        # Create monitor trader (separate from trading trader)
        try:
            self.monitor_trader = get_trader(config)
        except Exception as e:
            logger.error(f"Monitor trader creation failed: {e}")
            self.monitor_trader = None
            return {"success": False, "error": f"Exchange connection failed: {e}"}

        # Start monitor thread
        self.monitor_thread = MonitorThread(self, config)
        self.monitor_thread.start()
        return {"success": True, "message": "Monitor started"}

    def stop_monitor(self):
        """Stop the monitor thread if running."""
        if self.monitor_thread is not None:
            self.monitor_thread.stop_event.set()
            try:
                self.monitor_thread.join(timeout=8)
            except Exception:
                pass
            self.monitor_thread = None
        self.monitor_trader = None

    def start(self, config: dict):
        """Start the bot with the given config."""
        # ZOMBIE STATE CHECK
        if self.is_running:
            alive_workers = [w for w in self.workers.values() if w.is_alive()]
            if not alive_workers:
                logger.warning("Zombie state detected: is_running=True but no alive workers. Auto-resetting.")
                self.is_running = False
                self.workers.clear()
                self._emit("log", {
                    "level": "warn",
                    "msg": "⚠️ Zombie state detected (bot was stuck). Auto-reset done. You can START again."
                })
            else:
                return {"success": False, "error": "Bot already running"}

        self.config = config
        self.notifier.update_config(config)
        try:
            self.trader = get_trader(config)
        except Exception as e:
            logger.error("Failed to connect to exchange: %s", e)
            return {"success": False, "error": f"Exchange connection failed: {e}"}

        # Get symbols and leverage
        symbols = self._symbols_list()
        lev = config.get("leverage", 10)
        if not symbols:
            return {"success": False, "error": "Koi symbol nahi hai. Coins add karein."}

        # Apply leverage in BACKGROUND (non-blocking) - this prevents
        # /api/start from hanging when there are many coins
        import threading as _threading
        def _set_leverage_bg():
            for sym in symbols:
                r = self.trader.set_leverage(sym, lev)
                if r["success"]:
                    actual_lev = r.get("leverage", lev)
                    if r.get("adjusted"):
                        self._emit("log", {
                            "level": "warn",
                            "msg": f"[{sym}] Leverage auto-adjusted: {lev}x → {actual_lev}x (max allowed)"
                        })
                    else:
                        self._emit("log", {
                            "level": "info",
                            "msg": f"[{sym}] Leverage set: {actual_lev}x"
                        })
                else:
                    err = str(r.get("error", ""))
                    if "-2015" in err or "Invalid API-key" in err or "401" in err:
                        self._emit("log", {
                            "level": "error",
                            "msg": f"[{sym}] ❌ API AUTH FAILED: {err[:80]}. Bot stopped."
                        })
                        # Stop the bot
                        self.is_running = False
                        return
                    elif "-4141" in err or "Symbol is closed" in err or "band" in err:
                        self._emit("log", {
                            "level": "warn",
                            "msg": f"[{sym}] ⚠️ Symbol band/closed hai - skip."
                        })
                    else:
                        self._emit("log", {
                            "level": "warn",
                            "msg": f"[{sym}] Leverage set nahi ho saka: {err[:80]}"
                        })

        _bg_thread = _threading.Thread(target=_set_leverage_bg, daemon=True)
        _bg_thread.start()

        self.is_running = True

        # Set active_symbol BEFORE spawning workers (prevents race condition)
        if symbols:
            self.active_symbol = symbols[0]

        # Spawn one worker per symbol (STAGGERED to avoid API rate limits)
        with self.lock:
            for i, sym in enumerate(symbols):
                w = SymbolWorker(self, sym, config)
                self.workers[sym] = w
                # Stagger start: each worker starts 0.5s apart
                stagger_delay = min(i * 0.5, 10)  # max 10s spread
                if stagger_delay > 0:
                    threading.Timer(stagger_delay, w.start).start()
                else:
                    w.start()

        self._emit("status", {"running": True, "message": "Bot started"})
        sl_info = f"SL={config.get('stop_loss_pct', 0)}%" if config.get("stop_loss_pct", 0) else "SL=OFF"
        tp_info = f"TP={config.get('take_profit_pct', 0)}%" if config.get("take_profit_pct", 0) else "TP=opposite-signal"
        exchange = (config.get("exchange") or "binance").upper()
        env_label = "DEMO" if exchange == "WEEX" and config.get("testnet") else \
                    ("TESTNET" if config.get("testnet") else "MAINNET")
        self._emit("log", {
            "level": "info",
            "msg": (f"Bot STARTED | Exchange={exchange} | Symbols={','.join(symbols)} | "
                    f"TF={config['timeframe']} | Lev={config['leverage']}x | "
                    f"Mode={config.get('mode','both')} | Amount={self._amount_desc()} | "
                    f"{sl_info} | {tp_info} | Env={env_label}")
        })
        # Send notification
        try:
            self.notifier.notify_bot_start(config)
        except Exception as e:
            logger.error("Bot start notification failed: %s", e)
        return {"success": True, "message": "Bot started"}

    def stop(self):
        """Stop all workers."""
        if not self.is_running:
            return {"success": False, "error": "Bot not running"}

        with self.lock:
            for sym, w in self.workers.items():
                w.stop_event.set()
            for sym, w in self.workers.items():
                w.join(timeout=10)
            self.workers.clear()

        self.is_running = False
        self._emit("status", {"running": False, "message": "Bot stopped"})
        self._emit("log", {"level": "info", "msg": "Bot STOPPED by user"})
        # Send notification
        try:
            self.notifier.notify_bot_stop()
        except Exception as e:
            logger.error("Bot stop notification failed: %s", e)
        return {"success": True, "message": "Bot stopped"}

    def force_stop(self):
        """Force stop - always resets state, even if workers are dead (zombie recovery)."""
        logger.warning("Force stop requested - resetting all state.")
        with self.lock:
            for sym, w in self.workers.items():
                try:
                    w.stop_event.set()
                    w.join(timeout=5)
                except Exception:
                    pass
            self.workers.clear()
        self.is_running = False
        self.trader = None
        # NOTE: Do NOT stop the monitor or clear active_symbol.
        # Monitor keeps running so user still sees live data after force stop.
        # active_symbol stays so chart stays populated.
        self._emit("status", {"running": False, "message": "Force stopped"})
        self._emit("log", {
            "level": "warn",
            "msg": "⚠️ FORCE STOP done. Trading state reset. Monitor still running (live data active)."
        })
        return {"success": True, "message": "Force stop done - trading state reset"}

    def set_active_symbol(self, symbol: str):
        """Set which coin the UI is currently viewing. Only this coin's
        chart data will be sent via WebSocket (prevents flooding).

        Also tells the monitor thread to switch to this symbol — so the chart
        updates immediately even when the bot is STOPPED.
        """
        self.active_symbol = symbol
        logger.info(f"Active symbol set to: {symbol}")
        # If bot is running and this symbol has a worker, trigger an immediate
        # chart_data emit so the chart populates instantly (not after 3-5s wait)
        if self.is_running and symbol in self.workers:
            try:
                worker = self.workers[symbol]
                if hasattr(worker, '_last_df') and worker._last_df is not None:
                    df = worker._last_df
                    candles = worker._candles_to_list(df)
                    emas = worker._emas_to_list(df)
                    indicators = self.strategy.latest_indicators(df)
                    try:
                        mark_price = self.trader.get_mark_price(symbol)
                    except Exception:
                        mark_price = float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0
                    self._emit("chart_data", {
                        "symbol": symbol,
                        "candles": candles,
                        "emas": emas,
                    })
                    self._emit("indicators", {
                        "symbol": symbol,
                        **indicators,
                        "mark_price": mark_price,
                    })
                    logger.info(f"Sent chart data for {symbol} ({len(candles)} candles)")
            except Exception as e:
                logger.warning(f"Could not send immediate chart data for {symbol}: {e}")
        return {"success": True}

    # ---------- Helpers ----------

    def _symbols_list(self) -> list:
        """Get list of symbols to trade (supports multi-symbol).

        CRITICAL FIX: Previously this read `config['symbol']` which is always
        just the FIRST symbol from symbols_list. This meant only ONE worker
        was spawned even when user added 10 coins. Multi-coin was broken!

        Now: reads `config['symbols_list']` (the full list) first,
        falls back to `config['symbol']` (legacy single-string) only if
        symbols_list is missing or empty.
        """
        # Preferred: symbols_list (the full multi-coin list)
        sl = self.config.get("symbols_list")
        if isinstance(sl, list):
            parts = [str(x).strip().upper() for x in sl if x and str(x).strip()]
            if parts:
                return parts
        elif isinstance(sl, str) and sl.strip():
            parts = [x.strip().upper() for x in sl.split(",") if x.strip()]
            if parts:
                return parts
        # Legacy fallback: single symbol string
        s = self.config.get("symbol", "BTCUSDT")
        if isinstance(s, list):
            return [x.strip().upper() for x in s if x and x.strip()]
        if isinstance(s, str):
            parts = [x.strip().upper() for x in s.split(",") if x and x.strip()]
            return parts if parts else ["BTCUSDT"]
        return ["BTCUSDT"]

    def _amount_desc(self) -> str:
        m = self.config.get("amount_mode", "fixed")
        if m == "percent":
            return f"{self.config.get('amount_pct', 10)}% of wallet"
        return f"${self.config.get('amount', 100)}"

    def _emit(self, event: str, data: dict):
        """Emit a socketio event AND log to terminal (dual output for debugging)."""
        try:
            # Also log to terminal so we can see what's happening
            if event == "log":
                level = (data.get("level") or "info").upper()
                msg = data.get("msg", "")
                if level == "ERROR":
                    logger.error(msg)
                elif level == "WARN" or level == "WARNING":
                    logger.warning(msg)
                elif level == "SUCCESS":
                    logger.info(f"[SUCCESS] {msg}")
                else:
                    logger.info(msg)
            # Emit to browser via Socket.IO
            if self.socketio:
                self.socketio.emit(event, data, namespace="/")
        except Exception as e:
            logger.error("Socket emit failed: %s", e)

    @staticmethod
    def _poll_seconds(timeframe: str) -> int:
        """How often to re-check the strategy and SL/TP.
        Faster polling = SL/TP triggers faster."""
        mapping = {
            "1m": 3, "3m": 3, "5m": 3, "15m": 5,
            "30m": 5, "1h": 10, "2h": 15, "4h": 30,
            "1d": 60, "1w": 120,
        }
        return mapping.get(timeframe, 3)

    def status(self) -> dict:
        symbols = self._symbols_list() if self.is_running else []
        # ZOMBIE CHECK: if is_running but no alive workers, report as NOT running
        alive_count = sum(1 for w in self.workers.values() if w.is_alive())
        if self.is_running and alive_count == 0 and self.workers:
            # Workers all dead but flag still True - report as not running
            # and auto-reset so user can start again
            self.is_running = False
            self.workers.clear()
        return {
            "running": self.is_running,
            "exchange": self.config.get("exchange", "binance"),
            "symbols": symbols,
            "timeframe": self.config.get("timeframe"),
            "leverage": self.config.get("leverage"),
            "amount_mode": self.config.get("amount_mode", "fixed"),
            "amount": self.config.get("amount"),
            "amount_pct": self.config.get("amount_pct", 10),
            "stop_loss_pct": self.config.get("stop_loss_pct", 2),
            "take_profit_pct": self.config.get("take_profit_pct", 6),
            "mode": self.config.get("mode", "both"),
            "testnet": self.config.get("testnet", True),
            "workers": {
                sym: {
                    "candles_processed": w.candles_processed,
                    "trades_today": w.trades_today,
                    "last_signal": w.last_signal.value,
                    "last_trade_side": getattr(w, "last_trade_side", None),
                    "last_check": w.last_check,
                    "alive": w.is_alive(),
                }
                for sym, w in self.workers.items()
            },
        }
