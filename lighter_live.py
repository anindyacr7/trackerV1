#!/usr/bin/env python3
"""
FoxAlgo — Lighter DEX Live Automated Runner (BTC & ETH)
Executes 5m Session Range Breakout strategy on Lighter DEX:
  - Sessions: S1 Morning (08:00 - 17:30 IST) & S2 Evening (20:00 - 05:30 IST)
  - BTC: Buffer = 10.0 pts, Bodyless = 5.0 pts, Market ID = 4096 (Testnet) / 1 (Mainnet)
  - ETH: Buffer = 0.01% of CMP (~0.25-0.30 pts), Bodyless = 0.005% of CMP, Market ID = 4095 (Testnet) / 0 (Mainnet)
  - Risk per trade: $25.00 USDT
  - Entry: Resting Limit Order placed upon range breakout
  - Once filled: Native Stop Loss & Take Profit (5R) placed on Lighter
  - Trailing SL: 1.7R -> 1R, 2.8R -> 2R, 3.8R -> 3R, 4.8R -> 4R
  - Telemetry: Real-time ranges, trades, and heartbeats to FoxLedger dashboard
  - PURE LIVE ENGINE: Exchange position is the single source of truth. No simulated candle replay.
"""

import os
import sys
import time
import asyncio
import logging
import argparse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
load_dotenv()

# Add directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

import lighter
import ccxt
from telemetry import post_telemetry_range, post_telemetry_trade, post_telemetry_heartbeat
from btc_strategy_v2 import (
    StrategyEngine, _SessionScheduler, Config, Side, SessionID,
    Candle, Session, Trade, Range
)

log = logging.getLogger("LighterLive")

IST = ZoneInfo("Asia/Kolkata")
RISK_USDT = 25.0

BASE_URL    = "https://testnet.zklighter.elliot.ai"
MAINNET_URL = "https://mainnet.zklighter.elliot.ai"

# Market configuration per symbol
MARKET_CONFIG = {
    "BTC": {
        "testnet_market_id": 4096,
        "mainnet_market_id": 1,
        "price_decimals": 1,
        "size_decimals": 5,
        "min_qty": 0.0001,
        "slippage_room": 50.0,
        "emergency_buffer": 5.0,
    },
    "ETH": {
        "testnet_market_id": 4095,
        "mainnet_market_id": 0,
        "price_decimals": 2,
        "size_decimals": 4,
        "min_qty": 0.001,
        "slippage_room": 2.0,
        "emergency_buffer": 0.5,
    }
}


# ─────────────────────────────────────────────
#  RANGE CALCULATION (DYNAMIC FOR BTC & ETH)
# ─────────────────────────────────────────────

def find_symbol_range(symbol: str, candles: List[Candle], start_time: Optional[datetime] = None) -> Optional[Range]:
    """Find initial 2-candle breakout range with asset-specific buffer & bodyless filter."""
    if start_time:
        candles = [c for c in candles if c.timestamp >= start_time]

    for i in range(len(candles) - 1):
        c1, c2 = candles[i], candles[i + 1]
        cmp = (c1.close + c2.close) / 2.0

        if symbol.upper() == "BTC":
            buffer = 10.0
            bodyless_thresh = 5.0
        else: # ETH
            buffer = round(cmp * 0.0001, 2)
            bodyless_thresh = round(cmp * 0.00005, 2)

        b1 = abs(c1.close - c1.open)
        b2 = abs(c2.close - c2.open)
        if b1 <= bodyless_thresh or b2 <= bodyless_thresh:
            continue

        c1_red = c1.close < c1.open
        c2_red = c2.close < c2.open
        if (c1_red and not c2_red) or (not c1_red and c2_red):
            return Range(
                upper=max(c1.high, c2.high) + buffer,
                lower=min(c1.low, c2.low) - buffer,
                candle1=c1,
                candle2=c2,
            )
    return None


# ─────────────────────────────────────────────
#  ORDER INDEX MANAGER
# ─────────────────────────────────────────────

class OrderIndexManager:
    """Generates unique client_order_index values for Lighter (uint48)."""
    def __init__(self):
        self._counter = 0

    def next(self) -> int:
        ts = int(time.time() * 1000) % (2**38)
        self._counter = (self._counter + 1) % 1000
        return ts * 1000 + self._counter


# ─────────────────────────────────────────────
#  LIGHTER ORDER EXECUTOR (RESTING LIMIT APPROACH)
# ─────────────────────────────────────────────

class LighterOrderExecutor:
    """
    Handles Lighter DEX Limit Order breakout execution:
      - Places resting limit order at range boundary
      - Polls fill status
      - Once filled, immediately places native SL & TP orders
      - Trails SL using modify_order
      - Guaranteed market close on position exit
    """

    def __init__(self, signer_client: lighter.SignerClient, api_client: lighter.ApiClient,
                 market_api_client: lighter.ApiClient, account_index: int, symbol: str = "BTC"):
        self.signer = signer_client
        self.api = api_client
        self.market_api = market_api_client
        self.account_index = account_index
        self.symbol = symbol.upper()
        self.config = MARKET_CONFIG[self.symbol]
        self.market_id = self.config["testnet_market_id"]
        self.price_decimals = self.config["price_decimals"]
        self.size_decimals = self.config["size_decimals"]
        self.slippage_room = self.config["slippage_room"]
        self.emergency_buffer = self.config["emergency_buffer"]

        self.idx_manager = OrderIndexManager()
        self.active_orders: Dict[int, Dict[str, Any]] = {}
        self.pending_entry: Optional[Dict[str, Any]] = None
        self._initial_pos_size: float = 0.0

    def to_lighter_price(self, price: float) -> int:
        return int(round(price * (10 ** self.price_decimals)))

    def to_lighter_size(self, qty: float) -> int:
        return int(round(qty * (10 ** self.size_decimals)))

    async def get_current_position(self) -> float:
        """Fetch current open position size on this market."""
        try:
            acc_api = lighter.AccountApi(self.api)
            acc = await acc_api.account(by="index", value=str(self.account_index))
            if acc and acc.accounts:
                for p in acc.accounts[0].positions:
                    if int(p.market_id) == self.market_id:
                        return abs(float(p.position))
        except Exception as e:
            log.warning(f"get_current_position error: {e}")
        return 0.0

    async def get_position_signed(self) -> float:
        """Fetch signed position size: positive for Long, negative for Short, 0.0 for flat."""
        try:
            acc_api = lighter.AccountApi(self.api)
            acc = await acc_api.account(by="index", value=str(self.account_index))
            if acc and acc.accounts:
                for p in acc.accounts[0].positions:
                    if int(p.market_id) == self.market_id:
                        return float(p.position)
        except Exception as e:
            log.warning(f"get_position_signed error: {e}")
        return 0.0

    async def place_breakout_limit(self, trade: Trade, boundary: float):
        sl_pts = abs(trade.entry_boundary - trade.sl_price)
        if sl_pts <= 0:
            log.error(f"Cannot open position: sl_pts <= 0 ({sl_pts})")
            return

        raw_qty = RISK_USDT / sl_pts
        qty_int = self.to_lighter_size(raw_qty)
        if qty_int == 0:
            log.error("Qty rounds to 0 on Lighter — risk too small for range width")
            return

        is_long = (trade.side == Side.LONG)
        is_ask = not is_long   # Buy = is_ask: False, Sell = is_ask: True
        entry_idx = self.idx_manager.next()
        entry_price_int = self.to_lighter_price(boundary)

        log.info(
            f"TR{trade.trade_num} BREAKOUT {trade.side.value.upper()} | "
            f"Placing LIMIT {'BUY' if is_long else 'SELL'} @ {boundary:.2f} | "
            f"SL={trade.sl_price:.2f} TP={trade.tp_price:.2f} | "
            f"qty={raw_qty:.4f} {self.symbol} (index={entry_idx})"
        )

        try:
            self._initial_pos_size = await self.get_current_position()
            _, resp, err = await self.signer.create_order(
                market_index=self.market_id,
                client_order_index=entry_idx,
                base_amount=qty_int,
                price=entry_price_int,
                is_ask=is_ask,
                order_type=self.signer.ORDER_TYPE_LIMIT,
                time_in_force=self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                reduce_only=False,
                order_expiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY,
            )
            if err:
                log.error(f"Error placing Lighter limit entry: {err}")
                return

            log.info(f"  Lighter resting limit order {entry_idx} placed on book successfully!")
            self.pending_entry = {
                "trade": trade,
                "entry_idx": entry_idx,
                "qty_int": qty_int,
                "is_ask": is_ask,
                "boundary": boundary,
                "placed_time": time.time(),
            }
        except Exception as e:
            log.error(f"place_breakout_limit exception: {e}", exc_info=True)

    async def _place_sl_tp(self, trade: Trade, qty_int: int, is_ask: bool):
        """Place native Stop Loss and Take Profit orders once position is confirmed open."""
        sl_idx = self.idx_manager.next()
        tp_idx = self.idx_manager.next()
        close_is_ask = not is_ask   # opposite side to close

        is_long = (trade.side == Side.LONG)
        sl_trigger = self.to_lighter_price(trade.sl_price)
        sl_exec = (self.to_lighter_price(trade.sl_price - self.slippage_room) if is_long
                   else self.to_lighter_price(trade.sl_price + self.slippage_room))

        tp_trigger = self.to_lighter_price(trade.tp_price)
        tp_exec = (self.to_lighter_price(trade.tp_price - self.slippage_room) if is_long
                   else self.to_lighter_price(trade.tp_price + self.slippage_room))

        sl_placed = False
        try:
            # 1. Stop Loss Limit (reduce-only) with retry
            for attempt in range(3):
                _, _, err_sl = await self.signer.create_order(
                    market_index=self.market_id,
                    client_order_index=sl_idx,
                    base_amount=qty_int,
                    price=sl_exec,
                    is_ask=close_is_ask,
                    order_type=self.signer.ORDER_TYPE_STOP_LOSS_LIMIT,
                    time_in_force=self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                    reduce_only=True,
                    order_expiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY,
                    trigger_price=sl_trigger,
                )
                if not err_sl:
                    log.info(f"  Lighter SL placed @ trigger={trade.sl_price:.2f} (idx={sl_idx})")
                    sl_placed = True
                    break
                log.error(f"Failed attempt {attempt+1} to place Lighter SL: {err_sl}")
                await asyncio.sleep(1)

            # Safety: If SL could not be placed, emergency market close
            if not sl_placed:
                log.critical(f"FATAL: Could not place SL on Lighter! Emergency market closing position now!")
                await self.market_close_position()
                return

            # 2. Take Profit Limit (reduce-only)
            _, _, err_tp = await self.signer.create_order(
                market_index=self.market_id,
                client_order_index=tp_idx,
                base_amount=qty_int,
                price=tp_exec,
                is_ask=close_is_ask,
                order_type=self.signer.ORDER_TYPE_TAKE_PROFIT_LIMIT,
                time_in_force=self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                reduce_only=True,
                order_expiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY,
                trigger_price=tp_trigger,
            )
            if err_tp:
                log.warning(f"Failed to place Lighter TP: {err_tp}")
            else:
                log.info(f"  Lighter TP placed @ trigger={trade.tp_price:.2f} (idx={tp_idx})")

            self.active_orders[trade.id] = {
                "sl": sl_idx,
                "tp": tp_idx,
                "qty": qty_int,
                "close_is_ask": close_is_ask,
            }
        except Exception as e:
            log.error(f"_place_sl_tp exception: {e}", exc_info=True)

    async def check_pending_entry(self) -> Optional[Trade]:
        """Poll Lighter to check if pending limit order has filled."""
        if not self.pending_entry:
            return None

        trade = self.pending_entry["trade"]
        entry_idx = self.pending_entry["entry_idx"]
        qty_int = self.pending_entry["qty_int"]
        is_ask = self.pending_entry["is_ask"]
        boundary = self.pending_entry["boundary"]

        try:
            curr_pos = await self.get_current_position()
            if curr_pos > self._initial_pos_size + 0.00001:
                log.info(f"  Pending Lighter limit order {entry_idx} FILLED at boundary {boundary:.2f}! Attaching SL & TP...")
                self.pending_entry = None
                await self._place_sl_tp(trade, qty_int, is_ask)
                return trade
        except Exception as e:
            log.warning(f"check_pending_entry error: {e}")

        return None

    async def cancel_pending_entry(self, reason: str = "cancelled"):
        if not self.pending_entry:
            return
        entry_idx = self.pending_entry["entry_idx"]
        try:
            _, _, err = await self.signer.cancel_order(
                market_index=self.market_id,
                order_index=entry_idx
            )
            log.info(f"Cancelled pending Lighter limit order {entry_idx} (reason: {reason}) | err: {err}")
        except Exception as e:
            log.warning(f"Failed to cancel Lighter order {entry_idx}: {e}")
        self.pending_entry = None

    async def amend_sl(self, trade_id: int, new_sl_price: float, side: Side):
        orders = self.active_orders.get(trade_id)
        if not orders:
            return

        sl_idx = orders["sl"]
        qty_int = orders["qty"]
        is_long = (side == Side.LONG)
        new_trigger = self.to_lighter_price(new_sl_price)
        new_exec = (self.to_lighter_price(new_sl_price - self.slippage_room) if is_long
                    else self.to_lighter_price(new_sl_price + self.slippage_room))

        try:
            _, _, err = await self.signer.modify_order(
                market_index=self.market_id,
                order_index=sl_idx,
                base_amount=qty_int,
                price=new_exec,
                trigger_price=new_trigger,
            )
            if err:
                log.warning(f"Lighter amend_sl warning: {err}")
            else:
                log.info(f"  Lighter SL trailed → {new_sl_price:.2f} (order={sl_idx})")
        except Exception as e:
            log.error(f"amend_sl exception: {e}")

    async def market_close_position(self):
        """Immediately close any open position on this market via aggressive IOC order."""
        try:
            pos_sign = await self.get_position_signed()
            if abs(pos_sign) <= 0.00001:
                return

            is_long = pos_sign > 0
            close_is_ask = is_long
            qty_int = self.to_lighter_size(abs(pos_sign))
            close_idx = self.idx_manager.next()

            order_api = lighter.OrderApi(self.market_api)
            depth = await order_api.order_book_orders(market_id=self.config["mainnet_market_id"], limit=1)
            if close_is_ask:
                best_bid = float(depth.bids[0].price) if depth.bids else 0.0
                price_int = self.to_lighter_price(best_bid - self.slippage_room * 2)
            else:
                best_ask = float(depth.asks[0].price) if depth.asks else 999999.0
                price_int = self.to_lighter_price(best_ask + self.slippage_room * 2)

            log.info(f"Executing emergency market close on Lighter for {abs(pos_sign)} {self.symbol}...")
            _, _, err = await self.signer.create_order(
                market_index=self.market_id,
                client_order_index=close_idx,
                base_amount=qty_int,
                price=price_int,
                is_ask=close_is_ask,
                order_type=self.signer.ORDER_TYPE_LIMIT,
                time_in_force=self.signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only=True,
                order_expiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY,
            )
            if err:
                log.error(f"Market close on Lighter error: {err}")
            else:
                log.info(f"Market close on Lighter executed successfully.")
        except Exception as e:
            log.error(f"market_close_position exception: {e}")

    async def close_trade_orders(self, trade_id: int, reason: str):
        """Cancels resting orders AND verifies that the position on Lighter is actually flat."""
        await self.cancel_pending_entry(reason=f"trade closed ({reason})")
        orders = self.active_orders.pop(trade_id, None)
        if orders:
            for k in ["sl", "tp"]:
                oid = orders.get(k)
                if oid:
                    try:
                        await self.signer.cancel_order(
                            market_index=self.market_id,
                            order_index=oid
                        )
                    except Exception as e:
                        log.warning(f"Cancel {k} error {oid}: {e}")

        # CRITICAL SAFETY INVARIANT: Check if position is still open on Lighter!
        try:
            curr_pos = await self.get_current_position()
            if curr_pos > 0.00001:
                log.info(f"Position ({curr_pos} {self.symbol}) still open on Lighter during close ({reason}). Closing now...")
                await self.market_close_position()
        except Exception as e:
            log.error(f"Failed to ensure position flat on Lighter: {e}")

    async def sync_active_trade(self, trade: Trade, current_price: float, now_ist: datetime) -> Optional[str]:
        """
        Real-time reconciliation with Lighter:
        - If position is closed on exchange: detects fill of SL/TP, cancels orphan order, returns exit event.
        - If position is open: trails SL or enforces cutoff/emergency exits.
        """
        try:
            curr_pos = await self.get_current_position()
        except Exception as e:
            log.warning(f"sync_active_trade get_current_position error: {e}")
            return None

        # ── 1. POSITION IS FLAT ON LIGHTER ──
        if curr_pos <= 0.00001:
            log.info(f"Position for {self.symbol} is confirmed FLAT on Lighter. Reconciling orders...")
            orders = self.active_orders.pop(trade.id, None)
            sl_idx = orders.get("sl") if orders else None
            tp_idx = orders.get("tp") if orders else None

            # Cancel remaining orphan orders
            if orders:
                for k in ["sl", "tp"]:
                    oid = orders.get(k)
                    if oid:
                        try:
                            await self.signer.cancel_order(
                                market_index=self.market_id,
                                order_index=oid
                            )
                        except Exception:
                            pass

            # Detect whether TP or SL was touched
            is_long = (trade.side == Side.LONG)
            tp_touched = (current_price >= trade.tp_price) if is_long else (current_price <= trade.tp_price)
            if tp_touched:
                log.info(f"Lighter Take Profit reached @ {trade.tp_price:.2f} (5R)!")
                return "CLOSED_TP"

            is_trail = trade.sl_at_entry
            return "CLOSED_TRAIL_SL" if is_trail else "CLOSED_SL"

        # ── 2. POSITION IS ACTIVE ON LIGHTER ──
        # Trailing SL update based on CMP
        if current_price > 0:
            old_sl = trade.sl_price
            diff_thresh = 0.5 if self.symbol == "BTC" else 0.1
            if abs(trade.sl_price - old_sl) > diff_thresh:
                await self.amend_sl(trade.id, trade.sl_price, trade.side)

        # Emergency SL safety check: if price blew past SL by > emergency buffer
        is_long = (trade.side == Side.LONG)
        breached = (current_price <= trade.sl_price - self.emergency_buffer) if is_long else (current_price >= trade.sl_price + self.emergency_buffer)
        if breached and current_price > 0:
            log.warning(
                f"EMERGENCY: Price {current_price:.2f} breached SL {trade.sl_price:.2f} "
                f"without exchange trigger! Executing market close on Lighter..."
            )
            await self.close_trade_orders(trade.id, reason="EMERGENCY_SL")
            return "CLOSED_EMERGENCY"

        return None


# ─────────────────────────────────────────────
#  LIVE RUNNER
# ─────────────────────────────────────────────

class LighterLiveRunner:

    def __init__(self, symbol: str = "BTC"):
        self.symbol = symbol.upper()
        self.config = MARKET_CONFIG[self.symbol]
        self.engine = StrategyEngine()
        self.scheduler = _SessionScheduler(self.engine)
        self.is_bootstrapping = False

        self.api_key_index = int(os.environ["LIGHTER_API_KEY_INDEX"])
        self.api_priv_key = os.environ["LIGHTER_API_PRIVATE_KEY"]
        self.account_index = int(os.environ["LIGHTER_ACCOUNT_INDEX"])

        self.signer_client = lighter.SignerClient(
            url=BASE_URL,
            api_private_keys={self.api_key_index: self.api_priv_key},
            account_index=self.account_index,
        )
        self.api_client = lighter.ApiClient(lighter.Configuration(host=BASE_URL))
        self.market_api_client = lighter.ApiClient(lighter.Configuration(host=MAINNET_URL))

        self.executor = LighterOrderExecutor(
            self.signer_client, self.api_client, self.market_api_client,
            self.account_index, symbol=self.symbol
        )

        self.market_client = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        self.ccxt_symbol = f"{self.symbol}/USDT"

        self._last_candle_ts: Optional[datetime] = None

    async def start(self):
        log.info(f"=== Lighter Live Runner starting for {self.symbol} (Account: {self.account_index}) ===")
        try:
            acc_api = lighter.AccountApi(self.api_client)
            acc = await acc_api.account(by="index", value=str(self.account_index))
            if acc and acc.accounts:
                log.info(f"Lighter Collateral: ${float(acc.accounts[0].collateral):,.2f}")
        except Exception as e:
            log.warning(f"Could not fetch Lighter account collateral: {e}")

        self._patch_engine()
        await self._bootstrap_active_session()
        await self._main_loop()

    def _patch_engine(self):
        original_open = self.engine._open_trade
        original_close = self.engine._close_trade

        def patched_open(session, side, entry, rng, now):
            trade = original_open(session, side, entry, rng, now)
            if not self.is_bootstrapping:
                asyncio.create_task(self.executor.place_breakout_limit(trade, boundary=entry))
                try:
                    asyncio.create_task(post_telemetry_trade("Lighter", trade, symbol=self.symbol))
                except Exception as e:
                    log.warning(f"Telemetry open trade error: {e}")
            return trade

        def patched_close(trade, exit_price, now, reason):
            original_close(trade, exit_price, now, reason)
            if not self.is_bootstrapping:
                asyncio.create_task(self.executor.close_trade_orders(trade.id, reason))
                try:
                    asyncio.create_task(post_telemetry_trade("Lighter", trade, symbol=self.symbol))
                except Exception as e:
                    log.warning(f"Telemetry close trade error: {e}")

        self.engine._open_trade = patched_open
        self.engine._close_trade = patched_close

    async def _get_current_price(self) -> float:
        # 1. Primary: Lighter mainnet order book mid price
        try:
            order_api = lighter.OrderApi(self.market_api_client)
            depth = await order_api.order_book_orders(market_id=self.config["mainnet_market_id"], limit=1)
            if depth.bids and depth.asks:
                return (float(depth.bids[0].price) + float(depth.asks[0].price)) / 2.0
        except Exception:
            pass

        # 2. Fallback: Binance Futures
        try:
            ticker = self.market_client.fetch_ticker(self.ccxt_symbol)
            return float(ticker.get("last", 0.0))
        except Exception:
            return 0.0

    async def _fetch_candles(self, limit: int = 5) -> List[Candle]:
        # 1. Primary: Lighter mainnet CandlestickApi
        try:
            from lighter.api.candlestick_api import CandlestickApi
            api = CandlestickApi(self.market_api_client)
            res = await api.candles(
                market_id=self.config["mainnet_market_id"],
                resolution="5m",
                start_timestamp=0,
                end_timestamp=int(time.time() * 1000),
                count_back=limit
            )
            c_list = getattr(res, 'c', [])
            if c_list:
                candles = []
                for c in c_list[-limit:]:
                    candles.append(Candle(
                        timestamp=datetime.fromtimestamp(c.t / 1000.0, tz=timezone.utc),
                        open=float(c.o),
                        high=float(c.h),
                        low=float(c.l),
                        close=float(c.c),
                        volume=float(c.v),
                    ))
                return candles
        except Exception as e:
            log.warning(f"Lighter candles fetch failed ({e}), falling back to Binance")

        # 2. Fallback: Binance Futures
        try:
            raw = self.market_client.fetch_ohlcv(self.ccxt_symbol, Config.TIMEFRAME, limit=limit)
            return [Candle(
                timestamp=datetime.fromtimestamp(r[0]/1000, tz=timezone.utc),
                open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4]), volume=float(r[5])
            ) for r in raw]
        except Exception as e:
            log.error(f"fetch_candles error: {e}")
            return []

    async def _bootstrap_active_session(self):
        """Bootstrap the active session on startup without fake backtest simulation."""
        self.is_bootstrapping = True
        try:
            now_ist = datetime.now(tz=IST)
            if now_ist.weekday() >= 5:
                log.info("Weekend — no active session to bootstrap.")
                return

            target_sid = None
            session_start_ist = None

            s1_start = now_ist.replace(hour=8, minute=0, second=0, microsecond=0)
            s1_cutoff = now_ist.replace(hour=17, minute=30, second=0, microsecond=0)

            s2_start = now_ist.replace(hour=20, minute=0, second=0, microsecond=0)
            s2_cutoff = (now_ist + timedelta(days=1)).replace(hour=5, minute=30, second=0, microsecond=0)
            s2_early_start = (now_ist - timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
            s2_early_cutoff = now_ist.replace(hour=5, minute=30, second=0, microsecond=0)

            if s1_start <= now_ist < s1_cutoff:
                target_sid = SessionID.S1
                session_start_ist = s1_start
            elif now_ist >= s2_start:
                target_sid = SessionID.S2
                session_start_ist = s2_start
            elif now_ist < s2_early_cutoff:
                target_sid = SessionID.S2
                session_start_ist = s2_early_start

            if not target_sid:
                log.info("Currently outside active session windows. Scheduler will start next session.")
                return

            log.info(f"Bootstrapping active session {target_sid.value} from {session_start_ist.strftime('%Y-%m-%d %H:%M:%S IST')}...")
            self.engine.start_session(target_sid, session_start_ist)
            sess = self.engine.current_session
            if not sess:
                return

            # Fetch session candles to lock range
            minutes_elapsed = int((now_ist - session_start_ist).total_seconds() / 60)
            candle_count = min(150, max(5, int(minutes_elapsed / 5) + 3))
            candles = await self._fetch_candles(limit=candle_count)

            session_start_utc = session_start_ist.astimezone(timezone.utc)
            session_candles = [c for c in candles if c.timestamp >= session_start_utc]
            sess.candle_buffer = session_candles

            if len(sess.candle_buffer) >= 2:
                found = find_symbol_range(self.symbol, sess.candle_buffer, sess.start_time)
                if found:
                    sess.range = found
                    log.info(f"Range locked | upper={found.upper:.2f} lower={found.lower:.2f} width={found.width:.2f}pts")
                    try:
                        await post_telemetry_range("Lighter", sess, symbol=self.symbol)
                    except Exception as e:
                        log.warning(f"Telemetry range error: {e}")

            # RECONCILE WITH EXCHANGE ON STARTUP (NO SIMULATED TRADES)
            try:
                pos_sign = await self.executor.get_position_signed()
                if abs(pos_sign) > 0.00001:
                    log.info(f"Found active {self.symbol} position on Lighter during bootstrap: {pos_sign}")
                    pos_side = Side.LONG if pos_sign > 0 else Side.SHORT
                    if sess.range:
                        trade = Trade(
                            id=1,
                            session_id=sess.id,
                            trade_num=1,
                            side=pos_side,
                            entry_price=sess.range.upper if pos_side == Side.LONG else sess.range.lower,
                            entry_boundary=sess.range.upper if pos_side == Side.LONG else sess.range.lower,
                            sl_price=sess.range.lower if pos_side == Side.LONG else sess.range.upper,
                            tp_price=(sess.range.upper + 5.0 * sess.range.width if pos_side == Side.LONG
                                      else sess.range.lower - 5.0 * sess.range.width),
                            risk_pts=sess.range.width,
                            risk_usd=RISK_USDT,
                            entry_time=now_ist,
                            entry_candle_idx=0,
                        )
                        sess.trades.append(trade)
                        sess.active_trade = trade
            except Exception as e:
                log.warning(f"Lighter bootstrap position check warning: {e}")

            log.info(f"Bootstrap complete. Range locked: {sess.range is not None}, Active trade: {sess.active_trade is not None}")
        finally:
            self.is_bootstrapping = False

    async def _main_loop(self):
        log.info(f"Main loop running for {self.symbol}. Monitoring market and executing strategy...")
        while True:
            try:
                now_ist = datetime.now(tz=IST)
                self.scheduler.check(now_ist)
                sess = self.engine.current_session
                current_price = await self._get_current_price()

                # 1. Check if a pending limit entry order just got filled
                filled_trade = await self.executor.check_pending_entry()
                if filled_trade:
                    try:
                        await post_telemetry_trade("Lighter", filled_trade, symbol=self.symbol)
                    except Exception as e:
                        log.warning(f"Telemetry trade update error: {e}")

                # 2. Check 5m closed candles FOR RANGE DETECTION AND HEARTBEAT ONLY
                candles = await self._fetch_candles(limit=4)
                if candles and len(candles) >= 2:
                    last_closed = candles[-2]
                    if last_closed.timestamp != self._last_candle_ts:
                        self._last_candle_ts = last_closed.timestamp
                        self.engine.candle_idx += 1

                        # Heartbeat telemetry
                        try:
                            await post_telemetry_heartbeat(
                                "Lighter", last_closed.high, last_closed.low, last_closed.close
                            )
                        except Exception:
                            pass

                        if sess and sess.range is None:
                            sess.candle_buffer.append(last_closed)
                            if len(sess.candle_buffer) >= 2:
                                found = find_symbol_range(self.symbol, sess.candle_buffer, sess.start_time)
                                if found:
                                    sess.range = found
                                    log.info(
                                        f"Range locked | upper={found.upper:.2f} "
                                        f"lower={found.lower:.2f} width={found.width:.2f}pts"
                                    )
                                    try:
                                        await post_telemetry_range("Lighter", sess, symbol=self.symbol)
                                    except Exception as e:
                                        log.error(f"Telemetry range error: {e}")

                # 3. If an active trade is open: SYNC WITH REAL EXCHANGE!
                if sess and sess.active_trade and self.executor.pending_entry is None:
                    # Enforce Cutoff
                    if self.engine._past_cutoff(sess, now_ist):
                        log.info(f"Session cutoff reached at {now_ist.strftime('%H:%M:%S IST')}. Closing open position...")
                        trade = sess.active_trade
                        await self.executor.close_trade_orders(trade.id, reason="CUTOFF")
                        self.engine._close_trade(trade, current_price, now_ist, "CUTOFF")
                        sess.active_trade = None
                        try:
                            await post_telemetry_trade("Lighter", trade, symbol=self.symbol)
                        except Exception:
                            pass
                        continue

                    # Update trailing in memory first
                    if current_price > 0:
                        old_sl = sess.active_trade.sl_price
                        self.engine._update_trail(sess.active_trade, current_price)
                        diff_thresh = 0.5 if self.symbol == "BTC" else 0.1
                        if abs(sess.active_trade.sl_price - old_sl) > diff_thresh:
                            await self.executor.amend_sl(sess.active_trade.id, sess.active_trade.sl_price, sess.active_trade.side)

                    # Reconcile with exchange position
                    exit_event = await self.executor.sync_active_trade(sess.active_trade, current_price, now_ist)
                    if exit_event:
                        trade = sess.active_trade
                        exit_price = current_price
                        reason = exit_event.replace("CLOSED_", "")

                        if exit_event == "CLOSED_TP":
                            exit_price = trade.tp_price
                        elif exit_event in ("CLOSED_SL", "CLOSED_TRAIL_SL"):
                            exit_price = trade.sl_price

                        self.engine._close_trade(trade, exit_price, now_ist, reason)
                        sess.active_trade = None

                        try:
                            await post_telemetry_trade("Lighter", trade, symbol=self.symbol)
                        except Exception as e:
                            log.warning(f"Telemetry close trade error: {e}")

                        # Determine if session target reached or if we retrade
                        if exit_event in ("CLOSED_TP", "CLOSED_TRAIL_SL") or trade.sl_at_entry:
                            sess.target_hit = True
                            log.info(f"Session target achieved with profit/breakeven exit ({reason}). Done for session.")
                        elif exit_event in ("CLOSED_SL", "CLOSED_EMERGENCY"):
                            # Raw SL hit (loss): Check Retrade eligibility
                            log.info(f"Trade {trade.trade_num} hit SL. Checking retrade (trades taken: {sess.trade_count}/{Config.MAX_TRADES})...")
                            if sess.can_take_new_trade and not self.engine._past_cutoff(sess, now_ist):
                                next_side = sess.next_side()
                                if next_side:
                                    entry_price = sess.range.upper if next_side == Side.LONG else sess.range.lower
                                    log.info(f"RETRADE TRIGGERED: Placing opposite {next_side.value.upper()} limit order at {entry_price:.2f}...")
                                    self.engine._open_trade(sess, next_side, entry_price, sess.range, now_ist)

                # 4. If hunting for breakout:
                elif sess and sess.range and not self.engine._past_cutoff(sess, now_ist):
                    if sess.active_trade is None and self.executor.pending_entry is None and sess.can_take_new_trade:
                        if current_price >= sess.range.upper:
                            side = sess.next_side()
                            if side in (None, Side.LONG):
                                log.info(f"Real-time breakout detected: price {current_price:.2f} >= upper {sess.range.upper:.2f}! Triggering Limit Buy...")
                                self.engine._open_trade(sess, Side.LONG, sess.range.upper, sess.range, now_ist)
                        elif current_price <= sess.range.lower:
                            side = sess.next_side()
                            if side in (None, Side.SHORT):
                                log.info(f"Real-time breakout detected: price {current_price:.2f} <= lower {sess.range.lower:.2f}! Triggering Limit Sell...")
                                self.engine._open_trade(sess, Side.SHORT, sess.range.lower, sess.range, now_ist)

                    # If pending limit order is waiting, check if market reversed across the range
                    elif self.executor.pending_entry:
                        pending_trade = self.executor.pending_entry['trade']
                        if pending_trade.side == Side.LONG and current_price <= sess.range.lower:
                            log.info("Price reversed through lower boundary while Long limit order was pending. Cancelling order.")
                            await self.executor.cancel_pending_entry(reason="Reversed through opposite boundary")
                            sess.active_trade = None
                        elif pending_trade.side == Side.SHORT and current_price >= sess.range.upper:
                            log.info("Price reversed through upper boundary while Short limit order was pending. Cancelling order.")
                            await self.executor.cancel_pending_entry(reason="Reversed through opposite boundary")
                            sess.active_trade = None

                await asyncio.sleep(3)
            except KeyboardInterrupt:
                log.info("Runner stopped by user.")
                break
            except Exception as e:
                log.error(f"Unexpected loop exception: {e}", exc_info=True)
                await asyncio.sleep(10)


async def main():
    parser = argparse.ArgumentParser(description="FoxAlgo Lighter DEX Live Automated Runner")
    parser.add_argument("--symbol", type=str, default="BTC", choices=["BTC", "ETH"], help="Trading symbol (BTC or ETH)")
    args = parser.parse_args()

    sym = args.symbol.upper()
    log_filename = os.path.expanduser(f"~/foxAlgo/lighter_live_{sym.lower()}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(log_filename, maxBytes=10*1024*1024, backupCount=5),
        ]
    )

    runner = LighterLiveRunner(symbol=sym)
    await runner.start()

if __name__ == "__main__":
    asyncio.run(main())
