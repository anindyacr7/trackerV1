#!/usr/bin/env python3
"""
FoxAlgo — Propr Live Automated Runner (BTC & ETH)
Executes 5m Session Range Breakout strategy on Propr (Hyperliquid prop firm challenge):
  - Sessions: S1 Morning (08:00 - 17:30 IST) & S2 Evening (20:00 - 05:30 IST)
  - BTC: Buffer = 10.0 pts, Bodyless = 5.0 pts, Account = urn:prp-account:CRPYZs8zyarB
  - ETH: Buffer = 0.01% of CMP (~0.25-0.30 pts), Bodyless = 0.005% of CMP, Account = urn:prp-account:hFgq2yc8X9ou
  - Risk per trade: $25.00 USDT (0.5% on $5,000 challenge)
  - Entry: Resting Limit Order placed upon range breakout
  - Once filled: Native Stop Loss & Take Profit (5R) managed on Propr
  - Trailing SL: 1.7R -> 1R, 2.8R -> 2R, 3.8R -> 3R, 4.8R -> 4R
  - Telemetry: Real-time ranges, trades, and heartbeats to FoxLedger dashboard
"""

import os
import sys
import time
import asyncio
import logging
import requests
import argparse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
load_dotenv()

# Add directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

import ccxt
from propr_sdk import ProprClient
from telemetry import post_telemetry_range, post_telemetry_trade, post_telemetry_heartbeat
from btc_strategy_v2 import (
    StrategyEngine, _SessionScheduler, Config, Side, SessionID,
    Candle, Session, Trade, Range
)

log = logging.getLogger("ProprLive")

IST = ZoneInfo("Asia/Kolkata")
RISK_USDT = 25.0       # $25 risk per trade (0.5% on $5,000 prop firm challenge)

DEFAULT_BTC_ACCOUNT = "urn:prp-account:CRPYZs8zyarB"
DEFAULT_ETH_ACCOUNT = "urn:prp-account:hFgq2yc8X9ou"


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
#  PROPR ORDER EXECUTOR (LIMIT ORDER EXECUTION)
# ─────────────────────────────────────────────

class ProprOrderExecutor:
    """
    Handles Propr (Hyperliquid) Limit Order breakout execution:
      - Trigger limit buy at range.upper or limit sell at range.lower
      - Once limit order fills, immediately attach native stop_market SL and take_profit_market TP
      - Trailing SL amendment as trade advances
      - Position closing and order cleanup on cutoff or exit
    """

    def __init__(self, client: ProprClient, asset: str = "BTC"):
        self.client = client
        self.asset = asset.upper()
        # Active filled orders: { trade_id: { 'sl': order_id, 'tp': order_id, 'qty': str, 'pos_side': str, 'close_side': str, 'price_prec': int } }
        self.active_orders: Dict[int, Dict[str, Any]] = {}
        # Pending limit entry order: { 'trade': Trade, 'order_id': str, 'qty_str': str, 'pos_side': str, 'close_side': str, 'limit_price': str, 'price_prec': int, 'placed_time': float }
        self.pending_entry: Optional[Dict[str, Any]] = None

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
        sl_res = None
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
            log.info(f"  SL order placed: {sl_res}")
        except Exception as e:
            log.error(f"  Failed to place SL order: {e}")

        tp_res = None
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
            log.info(f"  TP order placed: {tp_res}")
        except Exception as e:
            log.error(f"  Failed to place TP order: {e}")

        self.active_orders[trade.id] = {
            'sl': sl_res[0]['orderId'] if sl_res else None,
            'tp': tp_res[0]['orderId'] if tp_res else None,
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
        info = self.active_orders.get(trade_id)
        price_prec = info.get('price_prec', 1 if self.asset == 'BTC' else 2) if info else (1 if self.asset == 'BTC' else 2)

        if not info:
            # Attempt auto-recovery from exchange positions & pending orders
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

        # Check if position is still open on exchange
        try:
            positions = self.client.get_open_positions(base=self.asset)
            if not positions:
                log.info("amend_sl: position already closed on exchange. Removing active order tracking.")
                self.active_orders.pop(trade_id, None)
                return
        except Exception:
            pass

        old_sl = info.get('sl')
        if old_sl:
            try:
                self.client.cancel_order(old_sl)
            except Exception as e:
                log.warning(f"amend_sl cancel old order {old_sl} warning: {e}")

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
                    if o.get('type') in ('stop_market', 'take_profit_market'):
                        self.client.cancel_order(o['orderId'])
            except Exception:
                pass

        if reason not in ("SL", "TP_5R", "TRAIL_SL"):
            try:
                positions = self.client.get_open_positions(base=self.asset)
                if positions:
                    res = self.client.close_position(base=self.asset, quote="USDC")
                    log.info(f"Closed open {self.asset} position on Propr: {res}")
            except Exception as e:
                log.error(f"Failed to close {self.asset} position on Propr: {e}")


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
        self._last_sl_sent: Dict[int, float] = {}

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
        original_update = self.engine._update_trail

        def patched_open(session, side, entry, rng, now):
            trade = original_open(session, side, entry, rng, now)
            if not self.is_bootstrapping:
                self._last_sl_sent[trade.id] = trade.sl_price
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

        def patched_update(trade, price):
            action = original_update(trade, price)
            if not self.is_bootstrapping:
                last_sl = self._last_sl_sent.get(trade.id, 0)
                diff_thresh = 0.5 if self.symbol == "BTC" else 0.1
                if abs(trade.sl_price - last_sl) > diff_thresh:
                    self.executor.amend_sl(trade.id, trade.sl_price)
                    self._last_sl_sent[trade.id] = trade.sl_price
            return action

        self.engine._open_trade = patched_open
        self.engine._close_trade = patched_close
        self.engine._update_trail = patched_update

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
        """Bootstrap the active session on startup."""
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

            minutes_elapsed = int((now_ist - session_start_ist).total_seconds() / 60)
            candle_count = min(150, max(5, int(minutes_elapsed / 5) + 3))
            candles = self._fetch_candles(limit=candle_count)

            session_start_utc = session_start_ist.astimezone(timezone.utc)
            now_utc = datetime.now(timezone.utc)

            for c in candles:
                if c.timestamp < session_start_utc:
                    continue
                if (now_utc - c.timestamp).total_seconds() < 290:
                    continue

                self.engine.candle_idx += 1
                sess.candle_buffer.append(c)

                just_locked = False
                if sess.range is None and len(sess.candle_buffer) >= 2:
                    found = find_symbol_range(self.symbol, sess.candle_buffer, sess.start_time)
                    if found:
                        sess.range = found
                        just_locked = True
                        log.info(f"Range locked | upper={found.upper:.2f} lower={found.lower:.2f} width={found.width:.2f}pts")
                        try:
                            asyncio.run(post_telemetry_range("Propr", sess, symbol=self.symbol))
                        except Exception as e:
                            log.warning(f"Telemetry range error: {e}")

                if not just_locked:
                    self.engine.process_candle(c, sess)

            log.info(f"Bootstrap complete. Session candles: {len(sess.candle_buffer)}, Range locked: {sess.range is not None}, Completed trades: {len(sess.trades)}")
        finally:
            self.is_bootstrapping = False

    def _main_loop(self):
        log.info(f"Main loop running for {self.symbol}. Monitoring market and executing strategy...")
        while True:
            try:
                now_ist = datetime.now(tz=IST)
                self.scheduler.check(now_ist)

                # 1. Check if a pending limit entry order just got filled
                filled_trade = self.executor.check_pending_entry()
                if filled_trade:
                    try:
                        asyncio.run(post_telemetry_trade("Propr", filled_trade, symbol=self.symbol))
                    except Exception as e:
                        log.warning(f"Telemetry trade update error: {e}")

                # 2. Check 5m closed candles
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

                        sess = self.engine.current_session
                        if sess:
                            sess.candle_buffer.append(last_closed)
                            just_locked = False
                            if sess.range is None and len(sess.candle_buffer) >= 2:
                                found = find_symbol_range(self.symbol, sess.candle_buffer, sess.start_time)
                                if found:
                                    sess.range = found
                                    just_locked = True
                                    log.info(
                                        f"Range locked | upper={found.upper:.2f} "
                                        f"lower={found.lower:.2f} width={found.width:.2f}pts"
                                    )
                                    try:
                                        asyncio.run(post_telemetry_range("Propr", sess, symbol=self.symbol))
                                    except Exception as e:
                                        log.error(f"Telemetry range error: {e}")

                            if not just_locked:
                                self.engine.process_candle(last_closed, sess)

                # 3. Real-time Breakout Check: Trigger limit order instantly when price hits boundary
                sess = self.engine.current_session
                if sess and sess.range and not self.engine._past_cutoff(sess, now_ist):
                    current_price = self._get_current_price()

                    # If hunting for breakout:
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
                            self.executor.cancel_pending_entry(reason="Reversed through opposite boundary")
                            sess.active_trade = None
                        elif pending_trade.side == Side.SHORT and current_price >= sess.range.upper:
                            log.info("Price reversed through upper boundary while Short limit order was pending. Cancelling order.")
                            self.executor.cancel_pending_entry(reason="Reversed through opposite boundary")
                            sess.active_trade = None

                    # If active trade is open and filled, tick trail monitor
                    elif sess.active_trade and self.executor.pending_entry is None:
                        if current_price > 0:
                            self.engine._update_trail(sess.active_trade, current_price)

                time.sleep(3)
            except KeyboardInterrupt:
                log.info("Runner stopped by user.")
                break
            except Exception as e:
                log.error(f"Unexpected loop exception: {e}", exc_info=True)
                time.sleep(10)


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
