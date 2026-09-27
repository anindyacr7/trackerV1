#!/usr/bin/env python3
"""
FoxAlgo — Propr Live Automated Runner (BTC & ETH)
Executes 5m Session Range Breakout strategy on Propr (Hyperliquid prop firm challenge):
  - Sessions: S1 Morning (08:00 - 17:30 IST) & S2 Evening (20:00 - 05:30 IST)
  - BTC: Buffer = 10.0 pts, Bodyless = 5.0 pts, Account = urn:prp-account:CRPYZs8zyarB
  - ETH: Buffer = 0.01% of CMP (~0.25-0.30 pts), Bodyless = 0.005% of CMP, Account = urn:prp-account:hFgq2yc8X9ou
  - Risk per trade: $25.00 USDT (0.5% on $5,000 challenge)
  - Entry: Resting Limit Order placed upon range breakout
  - Once filled: Native Stop Loss & Take Profit (5R) placed on Propr
  - Trailing SL: 1.7R -> 1R, 2.8R -> 2R, 3.8R -> 3R, 4.8R -> 4R
  - Telemetry: Real-time ranges, trades, and heartbeats to FoxLedger dashboard
  - PURE LIVE ENGINE: Exchange position is the single source of truth. No simulated candle replay.
"""

import os
import sys
import time
import json
import asyncio
import logging
import requests
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()

# Add directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

import ccxt
from propr_sdk import ProprClient
from telemetry import post_telemetry_range, post_telemetry_trade, post_telemetry_heartbeat
from btc_strategy_v2 import (
    StrategyEngine, _SessionScheduler, Config, Side, SessionID,
    Candle, Session, Trade, Range, TradeState
)

log = logging.getLogger("ProprLive")

IST = ZoneInfo("Asia/Kolkata")
RISK_USDT = 10.0       # $10 risk per trade (0.2% on $5,000 prop firm challenge)

DEFAULT_BTC_ACCOUNT = "urn:prp-account:NgyCFTUnJ9gd"
DEFAULT_ETH_ACCOUNT = "urn:prp-account:NgyCFTUnJ9gd"


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
#  PROPR ORDER EXECUTOR (LIVE RESTING LIMIT + SL/TP)
# ─────────────────────────────────────────────

class ProprOrderExecutor:
    """
    Handles Propr (Hyperliquid) Limit Order breakout execution:
      - Trigger limit buy at range.upper or limit sell at range.lower
      - Once limit order fills, immediately attach native stop_market SL and take_profit_market TP
      - Trailing SL amendment as trade advances
      - Position closing and order cleanup on cutoff or exit
      - Guaranteed position closure safety: Never leaves a naked position
    """

    def __init__(self, client: ProprClient, asset: str = "BTC"):
        self.client = client
        self.asset = asset.upper()
        # Active filled orders: { trade_id: { 'sl': order_id, 'tp': order_id, 'qty': str, 'pos_side': str, 'close_side': str, 'price_prec': int } }
        self.active_orders: Dict[int, Dict[str, Any]] = {}
        # Pending limit entry order: { 'trade': Trade, 'order_id': str, 'qty_str': str, 'pos_side': str, 'close_side': str, 'limit_price': str, 'price_prec': int, 'placed_time': float }
        self.pending_entry: Optional[Dict[str, Any]] = None

    def get_position_signed(self) -> float:
        try:
            positions = self.client.get_open_positions(base=self.asset)
            if positions and float(positions[0].get("quantity", 0)) > 0:
                pos = positions[0]
                qty = float(pos.get("quantity", 0))
                side = pos.get("positionSide", "").lower()
                return qty if side in ("long", "buy") else -qty
            return 0.0
        except Exception as e:
            log.warning(f"get_position_signed error: {e}")
            return 0.0

    def open_position(self, trade: Trade, current_price: float):
        sl_pts = abs(trade.entry_boundary - trade.sl_price)
        if sl_pts <= 0:
            log.error(f"Cannot open position: sl_pts <= 0 ({sl_pts})")
            return

        raw_qty = RISK_USDT / sl_pts
        # Cap notional size at 10x leverage max buffer ($45,000 for $5k balance)
        max_notional = 45000.0
        max_qty = max_notional / max(current_price, 10.0)

        if self.asset == "BTC":
            qty = round(max(0.001, min(raw_qty, max_qty)), 4)
            price_prec = 1
        else: # ETH
            qty = round(max(0.01, min(raw_qty, max_qty)), 3)
            price_prec = 2

        qty_str = str(qty)
        is_long = (trade.side == Side.LONG)
        side = "buy" if is_long else "sell"
        pos_side = "long" if is_long else "short"
        close_side = "sell" if is_long else "buy"
        limit_price = str(round(trade.entry_boundary, price_prec))

        log.info(
            f"TR{trade.trade_num} BREAKOUT {trade.side.value.upper()} | "
            f"Triggering LIMIT {side.upper()} order at {limit_price} | "
            f"SL={trade.sl_price:.2f} TP={trade.tp_price:.2f} | qty={qty_str} {self.asset}"
        )

        try:
            # 1. Place Limit Entry order at exact breakout boundary
            entry_res = self.client.create_order(
                side=side,
                position_side=pos_side,
                order_type="limit",
                asset=self.asset,
                base=self.asset,
                quote="USDC",
                quantity=qty_str,
                price=limit_price,
                time_in_force="GTC"
            )
            log.info(f"  Limit entry order placed: {entry_res}")

            if entry_res:
                order = entry_res[0]
                order_id = order.get("orderId")
                status = order.get("status")

                if status == "filled":
                    log.info(f"  Limit order {order_id} filled immediately at {limit_price}!")
                    self._place_sl_tp(trade, qty_str, pos_side, close_side, price_prec)
                else:
                    log.info(f"  Limit order {order_id} resting on book at {limit_price} (status={status}). Awaiting fill to attach SL/TP...")
                    self.pending_entry = {
                        'trade': trade,
                        'order_id': order_id,
                        'qty_str': qty_str,
                        'pos_side': pos_side,
                        'close_side': close_side,
                        'limit_price': limit_price,
                        'price_prec': price_prec,
                        'placed_time': time.time(),
                    }
        except Exception as e:
            log.error(f"open_position exception: {e}", exc_info=True)

    def _place_sl_tp(self, trade: Trade, qty_str: str, pos_side: str, close_side: str, price_prec: int):
        """Place native Stop Loss and Take Profit orders once position is confirmed open."""
        sl_order_id = None
        tp_order_id = None

        # Place SL order with retry
        for attempt in range(3):
            try:
                sl_res = self.client.create_order(
                    side=close_side,
                    position_side=pos_side,
                    order_type="stop_market",
                    asset=self.asset,
                    base=self.asset,
                    quote="USDC",
                    quantity=qty_str,
                    trigger_price=str(round(trade.sl_price, price_prec)),
                    reduce_only=True
                )
                if sl_res:
                    sl_order_id = sl_res[0].get('orderId')
                    log.info(f"  SL order placed: {sl_order_id} @ trigger={trade.sl_price:.2f}")
                    break
            except Exception as e:
                log.error(f"  Attempt {attempt+1} to place SL failed: {e}")
                time.sleep(1)

        # If SL could not be placed, EMERGENCY: close the position immediately to avoid naked risk!
        if not sl_order_id:
            log.critical(f"FATAL: Could not place SL for {self.asset} position! Closing position immediately for safety!")
            try:
                self.client.close_position(base=self.asset, quote="USDC")
            except Exception as e:
                log.critical(f"Emergency close failed: {e}")
            return

        # Place TP order
        try:
            tp_res = self.client.create_order(
                side=close_side,
                position_side=pos_side,
                order_type="take_profit_market",
                asset=self.asset,
                base=self.asset,
                quote="USDC",
                quantity=qty_str,
                trigger_price=str(round(trade.tp_price, price_prec)),
                reduce_only=True
            )
            if tp_res:
                tp_order_id = tp_res[0].get('orderId')
                log.info(f"  TP order placed: {tp_order_id} @ trigger={trade.tp_price:.2f}")
        except Exception as e:
            log.warning(f"  Failed to place TP order: {e}")

        self.active_orders[trade.id] = {
            'sl': sl_order_id,
            'tp': tp_order_id,
            'qty': qty_str,
            'pos_side': pos_side,
            'close_side': close_side,
            'price_prec': price_prec,
        }

    def check_pending_entry(self) -> Optional[Trade]:
        """Poll the pending limit order. If filled, attaches SL and TP and returns trade."""
        if not self.pending_entry:
            return None

        order_id = self.pending_entry['order_id']
        trade = self.pending_entry['trade']
        qty_str = self.pending_entry['qty_str']
        pos_side = self.pending_entry['pos_side']
        close_side = self.pending_entry['close_side']
        limit_price = self.pending_entry['limit_price']
        price_prec = self.pending_entry.get('price_prec', 1 if self.asset == 'BTC' else 2)

        try:
            orders = self.client.get_orders(order_id=order_id)
            if orders:
                status = orders[0].get("status")
                if status == "filled":
                    log.info(f"  Pending limit order {order_id} FILLED at {limit_price}! Placing SL and TP orders...")
                    self.pending_entry = None
                    self._place_sl_tp(trade, qty_str, pos_side, close_side, price_prec)
                    return trade
                elif status in ("cancelled", "rejected", "expired"):
                    log.warning(f"  Pending limit order {order_id} was {status}.")
                    self.pending_entry = None
                    return None
        except Exception as e:
            log.warning(f"check_pending_entry error: {e}")

        return None

    def cancel_pending_entry(self, reason: str = "cancelled"):
        """Cancel pending limit entry order if still open."""
        if not self.pending_entry:
            return
        order_id = self.pending_entry['order_id']
        try:
            res = self.client.cancel_order(order_id)
            log.info(f"Cancelled pending limit entry order {order_id} (reason: {reason}): {res}")
        except Exception as e:
            log.warning(f"Failed to cancel pending limit order {order_id}: {e}")
        self.pending_entry = None

    def amend_sl(self, trade_id: int, new_sl_price: float):
        """Update trailing stop loss order on the exchange."""
        info = self.active_orders.get(trade_id)
        price_prec = info.get('price_prec', 1 if self.asset == 'BTC' else 2) if info else (1 if self.asset == 'BTC' else 2)

        if not info:
            # Recover active orders from exchange
            try:
                positions = self.client.get_open_positions(base=self.asset)
                if not positions:
                    return
                pos = positions[0]
                pos_side = pos.get('positionSide', 'long')
                close_side = 'sell' if pos_side == 'long' else 'buy'
                qty_str = str(pos.get('quantity', '0.01'))

                orders = self.client.get_orders(status='pending')
                sl_id = None
                tp_id = None
                for o in orders:
                    if o.get('type') == 'stop_market':
                        sl_id = o.get('orderId')
                    elif o.get('type') == 'take_profit_market':
                        tp_id = o.get('orderId')

                info = {
                    'sl': sl_id,
                    'tp': tp_id,
                    'qty': qty_str,
                    'pos_side': pos_side,
                    'close_side': close_side,
                    'price_prec': price_prec,
                }
                self.active_orders[trade_id] = info
                log.info(f"Recovered active orders from exchange for trade {trade_id}: {info}")
            except Exception as e:
                log.warning(f"Failed to auto-recover active orders: {e}")
                return

        # Verify position is still open on exchange before touching SL
        try:
            positions = self.client.get_open_positions(base=self.asset)
            if not positions or float(positions[0].get('quantity', 0)) <= 0:
                log.info("amend_sl: position already closed on exchange. Removing active order tracking.")
                self.active_orders.pop(trade_id, None)
                return
        except Exception:
            pass

        old_sl = info.get('sl')

        # Cancel old SL order
        if old_sl:
            try:
                self.client.cancel_order(old_sl)
            except Exception as e:
                log.warning(f"amend_sl cancel old order {old_sl} warning: {e}")

        # Place new SL order
        try:
            new_sl_res = self.client.create_order(
                side=info['close_side'],
                position_side=info['pos_side'],
                order_type="stop_market",
                asset=self.asset,
                base=self.asset,
                quote="USDC",
                quantity=info['qty'],
                trigger_price=str(round(new_sl_price, price_prec)),
                reduce_only=True
            )
            if new_sl_res:
                info['sl'] = new_sl_res[0]['orderId']
                log.info(f"  SL trailed → {new_sl_price:.2f} (Order {info['sl']})")
        except Exception as e:
            log.error(f"amend_sl placing new SL exception: {e}", exc_info=True)

    def close_trade_orders(self, trade_id: int, reason: str):
        """
        Safely cancels all orders AND guarantees that any open position is closed on the exchange.
        """
        self.cancel_pending_entry(reason=f"trade closed ({reason})")
        info = self.active_orders.pop(trade_id, None)
        if info:
            for k in ['sl', 'tp']:
                oid = info.get(k)
                if oid:
                    try:
                        self.client.cancel_order(oid)
                    except Exception as e:
                        log.warning(f"Cancel {k} order {oid} warning: {e}")
        else:
            try:
                orders = self.client.get_orders(status='pending')
                for o in orders:
                    if o.get('type') in ('stop_market', 'take_profit_market', 'limit'):
                        self.client.cancel_order(o['orderId'])
            except Exception:
                pass

        # CRITICAL SAFETY INVARIANT: Check if position is still open on exchange!
        # An open position MUST NEVER remain naked after close_trade_orders is called!
        try:
            positions = self.client.get_open_positions(base=self.asset)
            if positions and float(positions[0].get("quantity", 0)) > 0:
                log.info(f"Position still open on exchange during close ({reason}). Executing market close...")
                res = self.client.close_position(base=self.asset, quote="USDC")
                log.info(f"Market close executed: {res}")
        except Exception as e:
            log.error(f"FATAL: Failed to close open position on exchange: {e}", exc_info=True)

    def sync_active_trade(self, trade: Trade, current_price: float, now_ist: datetime) -> Optional[str]:
        """
        Real-time reconciliation with the exchange:
        - If position is closed on exchange: detects fill of SL/TP, cancels orphan order, returns exit event.
        - If position is open: trails SL or enforces cutoff/emergency exits.
        Returns:
            None if trade is still active and open on exchange.
            'CLOSED_TP' if TP triggered on exchange.
            'CLOSED_TRAIL_SL' if trailing SL triggered on exchange.
            'CLOSED_SL' if initial raw SL triggered on exchange.
            'CLOSED_CUTOFF' if trade closed due to session cutoff.
            'CLOSED_EMERGENCY' if trade closed due to emergency threshold.
            'CLOSED_EXTERNAL' if position was closed externally.
        """
        try:
            positions = self.client.get_open_positions(base=self.asset)
        except Exception as e:
            log.warning(f"sync_active_trade get_open_positions error: {e}")
            return None

        # ── 1. POSITION IS FLAT ON EXCHANGE ──
        if not positions or float(positions[0].get("quantity", 0)) <= 0:
            log.info(f"Position for {self.asset} is confirmed FLAT on Propr. Reconciling orders...")
            info = self.active_orders.pop(trade.id, None)
            sl_id = info.get('sl') if info else None
            tp_id = info.get('tp') if info else None

            tp_filled = False
            if tp_id:
                try:
                    tp_orders = self.client.get_orders(order_id=tp_id)
                    if tp_orders and tp_orders[0].get('status') == 'filled':
                        tp_filled = True
                except Exception:
                    pass

            sl_filled = False
            if sl_id:
                try:
                    sl_orders = self.client.get_orders(order_id=sl_id)
                    if sl_orders and sl_orders[0].get('status') == 'filled':
                        sl_filled = True
                except Exception:
                    pass

            # Cancel remaining orphan orders on exchange
            if tp_id and not tp_filled:
                try:
                    self.client.cancel_order(tp_id)
                except Exception:
                    pass
            if sl_id and not sl_filled:
                try:
                    self.client.cancel_order(sl_id)
                except Exception:
                    pass

            if tp_filled:
                log.info(f"Exchange Take Profit order {tp_id} FILLED at {trade.tp_price:.2f} (5R)!")
                return "CLOSED_TP"
            elif sl_filled:
                is_trail = trade.sl_at_entry
                log.info(f"Exchange Stop Loss order {sl_id} FILLED at {trade.sl_price:.2f} ({'TRAIL_SL' if is_trail else 'SL'})!")
                return "CLOSED_TRAIL_SL" if is_trail else "CLOSED_SL"
            else:
                log.info(f"Exchange position closed externally or at CMP {current_price:.2f}.")
                return "CLOSED_EXTERNAL"

        # ── 2. POSITION IS ACTIVE ON EXCHANGE ──
        # Trailing SL update based on current CMP
        if current_price > 0:
            old_sl = trade.sl_price
            diff_thresh = 0.5 if self.asset == "BTC" else 0.1
            if abs(trade.sl_price - old_sl) > diff_thresh:
                self.amend_sl(trade.id, trade.sl_price)

        # Emergency SL safety check: if price blew past SL by > buffer and stop didn't trigger
        is_long = (trade.side == Side.LONG)
        emergency_buffer = 5.0 if self.asset == "BTC" else 0.5
        breached = (current_price <= trade.sl_price - emergency_buffer) if is_long else (current_price >= trade.sl_price + emergency_buffer)
        if breached and current_price > 0:
            log.warning(
                f"EMERGENCY: Price {current_price:.2f} breached SL {trade.sl_price:.2f} "
                f"without exchange trigger! Executing emergency market close..."
            )
            self.close_trade_orders(trade.id, reason="EMERGENCY_SL")
            return "CLOSED_EMERGENCY"

        return None


# ─────────────────────────────────────────────
#  LIVE RUNNER
# ─────────────────────────────────────────────

class ProprLiveRunner:

    def __init__(self, symbol: str = "BTC", account_id: Optional[str] = None):
        self.symbol = symbol.upper()
        self.engine = StrategyEngine()
        self.scheduler = _SessionScheduler(self.engine)
        self.is_bootstrapping = False

        api_key = os.getenv("PROPR_API_KEY")
        if not api_key:
            raise ValueError("PROPR_API_KEY not configured in environment")

        target_acc = account_id or (DEFAULT_BTC_ACCOUNT if self.symbol == "BTC" else DEFAULT_ETH_ACCOUNT)
        self.client = ProprClient(api_key=api_key)
        self.account_id = self.client.setup(account_id=target_acc)
        self.executor = ProprOrderExecutor(self.client, asset=self.symbol)

        # Public Binance Futures client for candle fallback
        self.market_client = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

        self.ccxt_symbol = f"{self.symbol}/USDT"
        self._last_candle_ts: Optional[datetime] = None

    def start(self):
        log.info(f"=== Propr Live Runner starting for {self.symbol} on Account: {self.account_id} ===")
        # Verify account details
        try:
            acc = self.client.get_account()
            log.info(f"Account Balance: {acc.get('balance')} {acc.get('currency', 'USDC')} | Type: {acc.get('type')}")
        except Exception as e:
            log.warning(f"Could not fetch account details: {e}")

        # Ensure leverage is 10x
        try:
            self.client.set_leverage(asset=self.symbol, leverage=10)
            log.info(f"Verified {self.symbol} leverage set to 10x")
        except Exception as e:
            log.warning(f"Set leverage warning: {e}")

        self._patch_engine()
        self._bootstrap_active_session()
        self._main_loop()

    def _patch_engine(self):
        original_open = self.engine._open_trade
        original_close = self.engine._close_trade

        def patched_open(session, side, entry, rng, now):
            trade = original_open(session, side, entry, rng, now)
            trade.risk_usd = RISK_USDT
            if not self.is_bootstrapping:
                ticker_price = self._get_current_price() or entry
                self.executor.open_position(trade, ticker_price)
                try:
                    asyncio.run(post_telemetry_trade("Propr", trade, symbol=self.symbol))
                except Exception as e:
                    log.warning(f"Telemetry open trade error: {e}")
            return trade

        def patched_close(trade, exit_price, now, reason):
            original_close(trade, exit_price, now, reason)
            if not self.is_bootstrapping:
                self.executor.close_trade_orders(trade.id, reason)
                try:
                    asyncio.run(post_telemetry_trade("Propr", trade, symbol=self.symbol))
                except Exception as e:
                    log.warning(f"Telemetry close trade error: {e}")

        self.engine._open_trade = patched_open
        self.engine._close_trade = patched_close

    def _get_current_price(self) -> float:
        # 1. Primary: Native Hyperliquid mid price
        try:
            r = requests.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"}, timeout=3)
            mids = r.json()
            if isinstance(mids, dict) and self.symbol in mids:
                return float(mids[self.symbol])
        except Exception:
            pass

        # 2. Fallback: Binance Futures
        try:
            ticker = self.market_client.fetch_ticker(self.ccxt_symbol)
            return float(ticker.get("last", 0.0))
        except Exception:
            return 0.0

    def _fetch_candles(self, limit: int = 5) -> List[Candle]:
        # 1. Primary: Native Hyperliquid 5m candleSnapshot
        try:
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - (limit * 300_000 + 600_000)
            r = requests.post("https://api.hyperliquid.xyz/info", json={
                "type": "candleSnapshot",
                "req": {
                    "coin": self.symbol,
                    "interval": "5m",
                    "startTime": start_ms,
                    "endTime": now_ms
                }
            }, timeout=5)
            data = r.json()
            if data and isinstance(data, list):
                candles = []
                for c in data[-limit:]:
                    candles.append(Candle(
                        timestamp=datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc),
                        open=float(c["o"]),
                        high=float(c["h"]),
                        low=float(c["l"]),
                        close=float(c["c"]),
                        volume=float(c.get("v", 0.0))
                    ))
                return candles
        except Exception as e:
            log.warning(f"Hyperliquid candleSnapshot failed ({e}), falling back to Binance")

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

    def _bootstrap_active_session(self):
        """Bootstrap the active session on startup without fake backtest simulation."""
        self.is_bootstrapping = True
        try:
            now_ist = datetime.now(tz=IST)
            target_sid = None
            session_start_ist = None

            if now_ist.weekday() >= 5:
                # On weekend, check if there is an active position carried over from Friday
                try:
                    pos_sign = self.executor.get_position_signed()
                    if abs(pos_sign) < 0.00001:
                        log.info("Weekend — no active session or position to bootstrap.")
                        return
                    log.info(f"Weekend bootstrap: Found active {self.symbol} position ({pos_sign}) carried from Friday! Bootstrapping Friday S2 session...")
                    days_back = now_ist.weekday() - 4  # 1 for Sat, 2 for Sun
                    target_sid = SessionID.S2
                    session_start_ist = (now_ist - timedelta(days=days_back)).replace(hour=20, minute=0, second=0, microsecond=0)
                except Exception as e:
                    log.warning(f"Weekend position check error: {e}")
                    return
            else:
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

            # Fetch candles to find and lock range
            minutes_elapsed = int((now_ist - session_start_ist).total_seconds() / 60)
            candle_count = min(150, max(5, int(minutes_elapsed / 5) + 3))
            candles = self._fetch_candles(limit=candle_count)

            session_start_utc = session_start_ist.astimezone(timezone.utc)
            session_candles = [c for c in candles if c.timestamp >= session_start_utc]
            sess.candle_buffer = session_candles

            if len(sess.candle_buffer) >= 2:
                found = find_symbol_range(self.symbol, sess.candle_buffer, sess.start_time)
                if found:
                    sess.range = found
                    log.info(f"Range locked | upper={found.upper:.2f} lower={found.lower:.2f} width={found.width:.2f}pts")
                    try:
                        asyncio.run(post_telemetry_range("Propr", sess, symbol=self.symbol))
                    except Exception as e:
                        log.warning(f"Telemetry range error: {e}")

            # RECONCILE WITH EXCHANGE ON STARTUP (NO SIMULATED BACKTEST TRADES)
            try:
                positions = self.client.get_open_positions(base=self.symbol)
                if positions and float(positions[0].get("quantity", 0)) > 0:
                    pos = positions[0]
                    pos_side = Side.LONG if pos.get("positionSide") == "long" else Side.SHORT
                    entry_px = float(pos.get("averagePrice", 0.0))
                    log.info(f"Found active {self.symbol} position on Propr during bootstrap: {pos}")
                    if sess.range:
                        trade = Trade(
                            id=1,
                            session_id=sess.id,
                            trade_num=1,
                            side=pos_side,
                            entry_price=entry_px or (sess.range.upper if pos_side == Side.LONG else sess.range.lower),
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

                        # Recover active order IDs from exchange
                        orders = self.client.get_orders(status='pending')
                        sl_id = None
                        tp_id = None
                        for o in orders:
                            if o.get('type') == 'stop_market':
                                sl_id = o.get('orderId')
                            elif o.get('type') == 'take_profit_market':
                                tp_id = o.get('orderId')
                        self.executor.active_orders[trade.id] = {
                            'sl': sl_id,
                            'tp': tp_id,
                            'qty': str(pos.get("quantity")),
                            'pos_side': pos.get("positionSide"),
                            'close_side': "sell" if pos_side == Side.LONG else "buy",
                            'price_prec': 1 if self.symbol == "BTC" else 2,
                        }
                        log.info(f"Successfully recovered active orders: {self.executor.active_orders[trade.id]}")
            except Exception as e:
                log.warning(f"Exchange bootstrap position check warning: {e}")

            log.info(f"Bootstrap complete. Range locked: {sess.range is not None}, Active trade: {sess.active_trade is not None}")
        finally:
            self.is_bootstrapping = False

    def _main_loop(self):
        log.info(f"Main loop running for {self.symbol}. Monitoring market and executing strategy...")
        while True:
            try:
                now_ist = datetime.now(tz=IST)
                self.scheduler.check(now_ist)
                sess = self.engine.current_session
                current_price = self._get_current_price()

                # 1. Check if a pending limit entry order just got filled
                filled_trade = self.executor.check_pending_entry()
                if filled_trade:
                    try:
                        asyncio.run(post_telemetry_trade("Propr", filled_trade, symbol=self.symbol))
                    except Exception as e:
                        log.warning(f"Telemetry trade update error: {e}")

                # 2. Check 5m closed candles FOR RANGE DETECTION AND HEARTBEAT ONLY
                candles = self._fetch_candles(limit=4)
                if candles and len(candles) >= 2:
                    last_closed = candles[-2]
                    if last_closed.timestamp != self._last_candle_ts:
                        self._last_candle_ts = last_closed.timestamp
                        self.engine.candle_idx += 1

                        # Heartbeat telemetry
                        try:
                            asyncio.run(post_telemetry_heartbeat(
                                "Propr", last_closed.high, last_closed.low, last_closed.close
                            ))
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
                                        asyncio.run(post_telemetry_range("Propr", sess, symbol=self.symbol))
                                    except Exception as e:
                                        log.error(f"Telemetry range error: {e}")

                # 3. If an active trade is open: SYNC WITH REAL EXCHANGE!
                if sess and sess.active_trade and self.executor.pending_entry is None:
                    # Check Friday carry-forward
                    is_carry = self.engine._friday_carry_active(sess.active_trade, now_ist)
                    if is_carry:
                        if not getattr(sess.active_trade, '_friday_carry_applied', False):
                            sess.active_trade.tp_price = sess.active_trade.price_at_r(Config.FRIDAY_CARRY_TP)
                            sess.active_trade.sl_price = sess.active_trade.entry_price
                            sess.active_trade.sl_at_entry = True
                            sess.active_trade._friday_carry_applied = True
                            log.info(
                                f"[FRIDAY CARRY] Friday trade {sess.active_trade.trade_num} carried into weekend! "
                                f"TP adjusted to 3.0R ({sess.active_trade.tp_price:.2f}), "
                                f"SL moved to Breakeven ({sess.active_trade.sl_price:.2f})."
                            )
                            try:
                                self.executor.amend_sl(sess.active_trade.id, sess.active_trade.sl_price)
                            except Exception as e:
                                log.warning(f"Error amending SL for Friday carry: {e}")
                    elif self.engine._past_cutoff(sess, now_ist):
                        log.info(f"Session cutoff reached at {now_ist.strftime('%H:%M:%S IST')}. Closing open position...")
                        trade = sess.active_trade
                        self.executor.close_trade_orders(trade.id, reason="CUTOFF")
                        self.engine._close_trade(trade, current_price, now_ist, "CUTOFF")
                        sess.active_trade = None
                        try:
                            asyncio.run(post_telemetry_trade("Propr", trade, symbol=self.symbol))
                        except Exception:
                            pass
                        continue

                    # Update trailing in memory first
                    if current_price > 0:
                        old_sl = sess.active_trade.sl_price
                        self.engine._update_trail(sess.active_trade, current_price)
                        diff_thresh = 0.5 if self.symbol == "BTC" else 0.1
                        if abs(sess.active_trade.sl_price - old_sl) > diff_thresh:
                            self.executor.amend_sl(sess.active_trade.id, sess.active_trade.sl_price)

                    # Reconcile with exchange position
                    exit_event = self.executor.sync_active_trade(sess.active_trade, current_price, now_ist)
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
                            asyncio.run(post_telemetry_trade("Propr", trade, symbol=self.symbol))
                        except Exception as e:
                            log.warning(f"Telemetry close trade error: {e}")

                        # Determine if session target reached or if we retrade
                        if exit_event in ("CLOSED_TP", "CLOSED_TRAIL_SL") or trade.sl_at_entry:
                            sess.target_hit = True
                            log.info(f"Session target achieved with profit/breakeven exit ({reason}). Done for session.")
                        elif exit_event in ("CLOSED_SL", "CLOSED_EMERGENCY"):
                            # Raw SL hit (loss): Check Retrade eligibility
                            log.info(f"Trade {trade.trade_num} hit SL. Checking retrade (trades taken: {sess.trade_count}/{Config.MAX_TRADES})...")
                            if sess.can_take_new_trade and not self.engine._past_cutoff(sess, now_ist) and now_ist.weekday() < 5:
                                next_side = sess.next_side()
                                if next_side:
                                    entry_price = sess.range.upper if next_side == Side.LONG else sess.range.lower
                                    log.info(f"RETRADE TRIGGERED: Placing opposite {next_side.value.upper()} limit order at {entry_price:.2f}...")
                                    self.engine._open_trade(sess, next_side, entry_price, sess.range, now_ist)

                # 4. If a pending limit entry order is waiting:
                if self.executor.pending_entry:
                    pending_trade = self.executor.pending_entry['trade']
                    is_long = (pending_trade.side == Side.LONG)
                    rr_1_7_target = pending_trade.price_at_r(1.7)

                    # Check if past session cutoff
                    if sess and self.engine._past_cutoff(sess, now_ist):
                        log.info(f"Session cutoff reached at {now_ist.strftime('%H:%M:%S IST')} while limit order pending. Cancelling order.")
                        self.executor.cancel_pending_entry(reason="CUTOFF")
                        sess.active_trade = None
                        if pending_trade in sess.trades:
                            sess.trades.remove(pending_trade)

                    else:
                        latest_high = current_price
                        latest_low = current_price
                        if candles:
                            latest_high = max(latest_high, candles[-1].high)
                            latest_low = min(latest_low, candles[-1].low)

                        hit_1_7 = (latest_high >= rr_1_7_target) if is_long else (latest_low <= rr_1_7_target)

                        if hit_1_7:
                            log.info(
                                f"1:1.7 R:R CANCEL TRIGGERED: Price reached 1:1.7 R:R target ({rr_1_7_target:.2f}) "
                                f"without filling {pending_trade.side.value.upper()} limit entry at {pending_trade.entry_boundary:.2f}! "
                                f"(Current={current_price:.2f}, High={latest_high:.2f}, Low={latest_low:.2f}). Cancelling order."
                            )
                            self.executor.cancel_pending_entry(reason="1:1.7 R:R reached without fill")
                            sess.active_trade = None
                            sess.target_hit = True
                            if pending_trade in sess.trades:
                                pending_trade.state = TradeState.CLOSED
                                pending_trade.exit_price = current_price
                                pending_trade.exit_reason = "CANCELLED_1.7R"
                                pending_trade.exit_time = now_ist
                                try:
                                    asyncio.run(post_telemetry_trade("Propr", pending_trade, symbol=self.symbol))
                                except Exception as e:
                                    log.warning(f"Telemetry trade update error: {e}")

                        elif is_long and sess and sess.range and current_price <= sess.range.lower:
                            log.info("Price reversed through lower boundary while Long limit order was pending. Cancelling order.")
                            self.executor.cancel_pending_entry(reason="Reversed through opposite boundary")
                            sess.active_trade = None
                            if pending_trade in sess.trades:
                                sess.trades.remove(pending_trade)

                        elif not is_long and sess and sess.range and current_price >= sess.range.upper:
                            log.info("Price reversed through upper boundary while Short limit order was pending. Cancelling order.")
                            self.executor.cancel_pending_entry(reason="Reversed through opposite boundary")
                            sess.active_trade = None
                            if pending_trade in sess.trades:
                                sess.trades.remove(pending_trade)

                # 5. If hunting for breakout (weekdays only):
                elif sess and sess.range and not self.engine._past_cutoff(sess, now_ist) and now_ist.weekday() < 5:
                    if sess.active_trade is None and sess.can_take_new_trade:
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

                # 6. Check if Friday trading is completed and bot should stop for the weekend
                if self._is_weekend_completed(sess, now_ist):
                    self._stop_for_weekend()
                    break

                time.sleep(3)
            except KeyboardInterrupt:
                log.info("Runner stopped by user.")
                break
            except Exception as e:
                log.error(f"Unexpected loop exception: {e}", exc_info=True)
                time.sleep(10)

    def _is_weekend_completed(self, sess: Optional[Session], now_ist: datetime) -> bool:
        w = now_ist.weekday()
        h = now_ist.hour
        m = now_ist.minute

        in_weekend_window = (
            (w == 4 and h >= 20) or
            (w in (5, 6)) or
            (w == 0 and (h < 7 or (h == 7 and m < 55)))
        )
        if not in_weekend_window:
            return False

        if self.executor.pending_entry is not None:
            return False

        if sess and sess.active_trade is not None:
            return False

        # On Saturday, Sunday, or Monday pre-market with no active trade and no pending entry
        if w in (5, 6) or (w == 0 and (h < 7 or (h == 7 and m < 55))):
            return True

        # On Friday night: done if session target reached, max trades taken, or past cutoff
        if w == 4 and sess:
            if sess.target_hit or sess.trade_count >= Config.MAX_TRADES:
                return True
            if self.engine._past_cutoff(sess, now_ist):
                return True

        return False

    def _stop_for_weekend(self):
        app_name = f"foxalgo-propr-{self.symbol.lower()}"
        log.info(f"[WEEKEND_STOP] Friday trades completed and flat for {self.symbol}. Stopping PM2 process {app_name} for the weekend.")
        try:
            state_dir = os.path.expanduser("~/foxAlgo/.weekend_state")
            os.makedirs(state_dir, exist_ok=True)
            with open(os.path.join(state_dir, f"{app_name}.json"), "w") as f:
                json.dump({
                    "app": app_name,
                    "symbol": self.symbol,
                    "status": "STOPPED",
                    "time": datetime.now(tz=IST).isoformat(),
                    "reason": "FRIDAY_TRADES_CLOSED"
                }, f, indent=2)
        except Exception as e:
            log.warning(f"Error saving weekend state: {e}")

        try:
            subprocess.Popen(["pm2", "stop", app_name])
        except Exception as e:
            log.warning(f"Error invoking pm2 stop {app_name}: {e}")

        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="FoxAlgo Propr Live Automated Runner")
    parser.add_argument("--symbol", type=str, default="BTC", choices=["BTC", "ETH"], help="Trading symbol (BTC or ETH)")
    parser.add_argument("--account", type=str, default=None, help="Propr Account ID URN")
    args = parser.parse_args()

    sym = args.symbol.upper()
    log_filename = os.path.expanduser(f"~/foxAlgo/propr_live_{sym.lower()}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(log_filename, maxBytes=10*1024*1024, backupCount=5),
        ]
    )

    runner = ProprLiveRunner(symbol=sym, account_id=args.account)
    runner.start()

if __name__ == "__main__":
    main()
