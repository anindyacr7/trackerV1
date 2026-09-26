#!/usr/bin/env python3
"""
FoxAlgo — TradeLocker US100 Live Automated Runner
Executes 5m Session Range Breakout strategy on NASDAQ 100 Index CFD (US100):
  - Sessions: S1 Morning (08:00 - 17:30 IST) & S2 Evening (20:00 - 05:30 IST)
  - Max trades: 2 trades per session (Trade 1 + 1 re-trade if SL hit; Trade 3 eliminated; max daily loss capped at -4R)
  - Buffer: 0.01% of CMP (~2.5-3.0 pts on US100)
  - Bodyless filter: 0.005% of CMP (~1.2-1.5 pts)
  - Risk per trade: $10.00 USD (fixed)
  - Entry: Resting Limit Order placed upon range breakout
  - Once filled: Native Stop Loss & Take Profit (5R) managed on TradeLocker
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
import subprocess
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from tradelocker import TLAPI
from telemetry import post_telemetry_range, post_telemetry_trade, post_telemetry_heartbeat
from btc_strategy_v2 import (
    StrategyEngine, _SessionScheduler, Config, Side, SessionID,
    Candle, Session, Trade, TradeState, Range
)

log = logging.getLogger("TradeLockerLive")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        RotatingFileHandler(
            os.path.expanduser("~/foxAlgo/tradelocker_live.log"),
            maxBytes=10*1024*1024,
            backupCount=5
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("tradelocker").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

IST = ZoneInfo("Asia/Kolkata")
RISK_USD = 10.0            # $10 fixed risk per trade
SYMBOL = "US100"
INSTRUMENT_ID = 4858       # US100 tradableInstrumentId in FTRM TradeLocker
MAX_TRADES_PER_SESSION = 2 # Max trades allowed per session (Trade 1 + 1 re-trade; max daily loss capped at -4R)

# Configure strategy engine session limit for US100
Config.MAX_TRADES = MAX_TRADES_PER_SESSION


# ─────────────────────────────────────────────
#  RANGE CALCULATION (DYNAMIC FOR US100)
# ─────────────────────────────────────────────

def find_us100_range(candles: List[Candle], start_time: Optional[datetime] = None) -> Optional[Range]:
    """Find initial 2-candle breakout range with US100 0.01% buffer and 0.005% bodyless filter."""
    if start_time:
        candles = [c for c in candles if c.timestamp >= start_time]

    for i in range(len(candles) - 1):
        c1, c2 = candles[i], candles[i + 1]
        cmp = (c1.close + c2.close) / 2.0

        buffer = round(cmp * 0.0001, 2)
        bodyless_thresh = round(cmp * 0.00005, 2)

        b1 = abs(c1.close - c1.open)
        b2 = abs(c2.close - c2.open)
        if b1 < bodyless_thresh or b2 < bodyless_thresh:
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
#  TRADELOCKER ORDER EXECUTOR
# ─────────────────────────────────────────────

class TradeLockerOrderExecutor:
    """
    Manages US100 Limit Order breakout execution on TradeLocker:
      - Places limit buy/sell order at range boundary with attached SL and TP
      - Monitors fill status
      - Trails SL on open positions
      - Guaranteed market close on position exit
    """

    def __init__(self, tl_client: TLAPI, instrument_id: int = INSTRUMENT_ID):
        self.tl = tl_client
        self.instrument_id = instrument_id
        self.lot_size = 20.0       # 1 standard lot = 20 contracts
        self.min_lot = 0.01
        self.lot_step = 0.01
        self.emergency_buffer = 5.0
        self.pending_order: Optional[Dict[str, Any]] = None
        self.active_position_id: Optional[int] = None
        self.active_trade: Optional[Trade] = None

    def calculate_lots(self, risk_pts: float) -> float:
        """Calculate lots for fixed $10 risk."""
        if risk_pts <= 0:
            return self.min_lot
        lots = RISK_USD / (risk_pts * self.lot_size)
        steps = int(lots / self.lot_step)
        final_lots = round(steps * self.lot_step, 2)
        return max(self.min_lot, final_lots)

    def place_breakout_limit(self, trade: Trade, boundary: float):
        """Submit a resting limit order at range boundary with attached SL and TP."""
        side = "buy" if trade.side == Side.LONG else "sell"
        lots = self.calculate_lots(trade.risk_pts)
        entry_price = round(boundary, 2)
        sl_price = round(trade.sl_price, 2)
        tp_price = round(trade.tp_price, 2)

        log.info(
            f"TR{trade.trade_num} {side.upper()} LIMIT @ {entry_price:.2f} | "
            f"SL={sl_price:.2f} TP={tp_price:.2f} (1R={trade.risk_pts:.2f}pts, lots={lots})"
        )

        try:
            order_id = self.tl.create_order(
                instrument_id=self.instrument_id,
                quantity=lots,
                side=side,
                price=entry_price,
                type_="limit",
                validity="GTC",
                stop_loss=sl_price,
                stop_loss_type="absolute",
                take_profit=tp_price,
                take_profit_type="absolute",
            )
            log.info(f"  TradeLocker Limit Order placed successfully | Order ID: {order_id}")
            self.pending_order = {
                "order_id": order_id,
                "trade": trade,
                "lots": lots,
                "side": side,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
            }
            self.active_trade = trade
        except Exception as e:
            log.error(f"  Failed to place TradeLocker limit order: {e}", exc_info=True)

    def check_orders_and_positions(self) -> Optional[Trade]:
        """Poll TradeLocker to detect if limit order has filled into a position."""
        try:
            positions = self.tl.get_all_positions()
            if hasattr(positions, 'to_dict'):
                pos_list = positions.to_dict('records')
            elif isinstance(positions, list):
                pos_list = positions
            else:
                pos_list = []

            us100_positions = [
                p for p in pos_list
                if int(p.get('tradableInstrumentId', 0)) == self.instrument_id
            ]

            if us100_positions:
                pos = us100_positions[0]
                pos_id = int(pos.get('id', 0))
                if self.active_position_id != pos_id:
                    self.active_position_id = pos_id
                    log.info(f"  US100 Position active! Position ID: {pos_id} | Side: {pos.get('side')} | Open: {pos.get('avgPrice')}")
                    self.pending_order = None
                    return self.active_trade

            if self.pending_order:
                orders = self.tl.get_all_orders()
                if hasattr(orders, 'to_dict'):
                    ord_list = orders.to_dict('records')
                elif isinstance(orders, list):
                    ord_list = orders
                else:
                    ord_list = []

                oid = self.pending_order["order_id"]
                still_open = any(int(o.get('id', 0)) == oid for o in ord_list)
                if not still_open and not us100_positions:
                    log.warning(f"  Limit order {oid} no longer open and no position found.")
                    self.pending_order = None

        except Exception as e:
            log.warning(f"check_orders_and_positions error: {e}")

        return None

    def amend_sl(self, new_sl_price: float):
        """Update Stop Loss on the active TradeLocker position."""
        if not self.active_position_id:
            return
        try:
            new_sl = round(new_sl_price, 2)
            self.tl.modify_position(
                position_id=self.active_position_id,
                stop_loss=new_sl,
                stop_loss_type="absolute"
            )
            log.info(f"  SL Trailed → {new_sl:.2f} on Position {self.active_position_id}")
        except Exception as e:
            log.error(f"  Failed to trail SL on TradeLocker: {e}")

    def cancel_pending(self, reason: str = ""):
        """Cancel any pending limit order."""
        if not self.pending_order:
            return
        oid = self.pending_order["order_id"]
        try:
            self.tl.delete_order(oid)
            log.info(f"Cancelled pending limit order {oid} ({reason})")
        except Exception as e:
            log.warning(f"Failed to cancel order {oid}: {e}")
        self.pending_order = None

    def close_trade_orders(self, reason: str = ""):
        """Cancels pending order AND guarantees the active TradeLocker position is closed."""
        self.cancel_pending(reason=f"trade closed ({reason})")
        try:
            positions = self.tl.get_all_positions()
            if hasattr(positions, 'to_dict'):
                pos_list = positions.to_dict('records')
            elif isinstance(positions, list):
                pos_list = positions
            else:
                pos_list = []

            us100_positions = [
                p for p in pos_list
                if int(p.get('tradableInstrumentId', 0)) == self.instrument_id
            ]

            if us100_positions:
                for p in us100_positions:
                    pid = int(p.get('id', 0))
                    log.info(f"Closing active TradeLocker position {pid} ({reason})...")
                    self.tl.close_position(pid)
                    log.info(f"Position {pid} closed successfully.")
            self.active_position_id = None
        except Exception as e:
            log.error(f"close_trade_orders error on TradeLocker: {e}")

    def sync_active_trade(self, trade: Trade, current_price: float, now_ist: datetime) -> Optional[str]:
        """
        Reconciles the open trade with real TradeLocker positions:
        - If position is closed: detects exit and returns exit event.
        - If position is open: trails SL or enforces cutoff/emergency exits.
        """
        try:
            positions = self.tl.get_all_positions()
            if hasattr(positions, 'to_dict'):
                pos_list = positions.to_dict('records')
            elif isinstance(positions, list):
                pos_list = positions
            else:
                pos_list = []

            us100_positions = [
                p for p in pos_list
                if int(p.get('tradableInstrumentId', 0)) == self.instrument_id
            ]
        except Exception as e:
            log.warning(f"sync_active_trade get_all_positions error: {e}")
            return None

        # ── 1. POSITION IS FLAT ON TRADELOCKER ──
        if not us100_positions:
            log.info("Position for US100 is confirmed FLAT on TradeLocker.")
            self.active_position_id = None
            self.cancel_pending(reason="position flat")

            is_long = (trade.side == Side.LONG)
            tp_touched = (current_price >= trade.tp_price) if is_long else (current_price <= trade.tp_price)
            if tp_touched:
                log.info(f"TradeLocker Take Profit reached @ {trade.tp_price:.2f} (5R)!")
                return "CLOSED_TP"

            is_trail = trade.sl_at_entry
            return "CLOSED_TRAIL_SL" if is_trail else "CLOSED_SL"

        # ── 2. POSITION IS ACTIVE ON TRADELOCKER ──
        pos = us100_positions[0]
        self.active_position_id = int(pos.get('id', 0))

        # Trailing SL update based on CMP
        if current_price > 0:
            old_sl = trade.sl_price
            if abs(trade.sl_price - old_sl) > 0.5:
                self.amend_sl(trade.sl_price)

        # Emergency SL safety check: if market blown past SL by > emergency buffer
        is_long = (trade.side == Side.LONG)
        breached = (current_price <= trade.sl_price - self.emergency_buffer) if is_long else (current_price >= trade.sl_price + self.emergency_buffer)
        if breached and current_price > 0:
            log.warning(
                f"EMERGENCY: Price {current_price:.2f} breached SL {trade.sl_price:.2f} "
                f"without exchange trigger! Executing position close on TradeLocker..."
            )
            self.close_trade_orders(reason="EMERGENCY_SL")
            return "CLOSED_EMERGENCY"

        return None


# ─────────────────────────────────────────────
#  LIVE RUNNER
# ─────────────────────────────────────────────

class TradeLockerLiveRunner:

    def __init__(self):
        Config.MAX_TRADES = MAX_TRADES_PER_SESSION
        self.engine = StrategyEngine()
        self.scheduler = _SessionScheduler(self.engine)
        self.is_bootstrapping = False

        email = os.getenv("TRADELOCKER_EMAIL", "avilashmohante@gmail.com")
        password = os.getenv("TRADELOCKER_PASSWORD", '"B3ZRDwdBTu{')
        server = os.getenv("TRADELOCKER_SERVER", "FTRM")
        environment = os.getenv("TRADELOCKER_ENV", "https://demo.tradelocker.com")

        log.info(f"Connecting to TradeLocker ({environment}, Server: {server}, User: {email})...")
        self.tl = TLAPI(
            environment=environment,
            username=email,
            password=password,
            server=server
        )

        state = self.tl.get_account_state()
        balance = state.get('balance', 0.0)
        log.info(f"Connected to TradeLocker! Account Balance: ${balance:,.2f} USD")

        self.executor = TradeLockerOrderExecutor(self.tl, INSTRUMENT_ID)
        self._last_candle_ts: Optional[datetime] = None
        log.info(f"Max trades per session: {Config.MAX_TRADES} (Trade 1 + 1 re-trade max, max daily loss -4R)")

    def start(self):
        log.info("=== TradeLocker US100 Live Runner Started ===")
        self._patch_engine()
        self._bootstrap_active_session()
        self._main_loop()

    def _patch_engine(self):
        original_open = self.engine._open_trade
        original_close = self.engine._close_trade

        def patched_open(session, side, entry, rng, now):
            trade = original_open(session, side, entry, rng, now)
            if not self.is_bootstrapping:
                self.executor.place_breakout_limit(trade, boundary=entry)
                try:
                    asyncio.run(post_telemetry_trade("TradeLocker", trade, symbol=SYMBOL))
                except Exception as e:
                    log.warning(f"Telemetry open trade error: {e}")
            return trade

        def patched_close(trade, exit_price, now, reason):
            original_close(trade, exit_price, now, reason)
            if not self.is_bootstrapping:
                self.executor.close_trade_orders(reason=reason)
                try:
                    asyncio.run(post_telemetry_trade("TradeLocker", trade, symbol=SYMBOL))
                except Exception as e:
                    log.warning(f"Telemetry close trade error: {e}")

        self.engine._open_trade = patched_open
        self.engine._close_trade = patched_close

    def _fetch_candles(self, limit: int = 15) -> List[Candle]:
        """Fetch 5m bars for US100 via TradeLocker get_price_history."""
        try:
            now_ms = int(time.time() * 1000)
            from_ms = now_ms - (limit * 5 * 60 * 1000 + 600_000)
            df = self.tl.get_price_history(
                instrument_id=INSTRUMENT_ID,
                resolution="5m",
                start_timestamp=from_ms,
                end_timestamp=now_ms
            )
            if df is None or len(df) == 0:
                return []

            candles = []
            for _, r in df.tail(limit).iterrows():
                candles.append(Candle(
                    timestamp=datetime.fromtimestamp(r['t'] / 1000, tz=timezone.utc),
                    open=float(r['o']),
                    high=float(r['h']),
                    low=float(r['l']),
                    close=float(r['c']),
                    volume=float(r.get('v', 0.0))
                ))
            return candles
        except Exception as e:
            log.error(f"fetch_candles error: {e}")
            return []

    def _get_current_price(self) -> float:
        """Fetch latest mid/bid price for US100."""
        try:
            bid = self.tl.get_latest_bid_price(INSTRUMENT_ID)
            ask = self.tl.get_latest_asking_price(INSTRUMENT_ID)
            if bid and ask:
                return (bid + ask) / 2.0
            return bid or ask or 0.0
        except Exception:
            return 0.0

    def _bootstrap_active_session(self):
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
                log.info("Currently outside active session windows.")
                return

            log.info(f"Bootstrapping active session {target_sid.value} from {session_start_ist.strftime('%Y-%m-%d %H:%M:%S IST')}...")
            self.engine.start_session(target_sid, session_start_ist)
            sess = self.engine.current_session
            if not sess:
                return

            # Fetch session candles to find and lock range
            minutes_elapsed = int((now_ist - session_start_ist).total_seconds() / 60)
            candle_count = min(150, max(5, int(minutes_elapsed / 5) + 3))
            candles = self._fetch_candles(limit=candle_count)

            session_start_utc = session_start_ist.astimezone(timezone.utc)
            session_candles = [c for c in candles if c.timestamp >= session_start_utc]
            sess.candle_buffer = session_candles

            if len(sess.candle_buffer) >= 2:
                found = find_us100_range(sess.candle_buffer, sess.start_time)
                if found:
                    sess.range = found
                    log.info(f"Range locked | upper={found.upper:.2f} lower={found.lower:.2f} width={found.width:.2f}pts")
                    try:
                        asyncio.run(post_telemetry_range("TradeLocker", sess, symbol=SYMBOL))
                    except Exception as e:
                        log.warning(f"Telemetry range error: {e}")

            # RECONCILE WITH TRADELOCKER ON STARTUP (NO SIMULATED TRADES)
            try:
                positions = self.tl.get_all_positions()
                if hasattr(positions, 'to_dict'):
                    pos_list = positions.to_dict('records')
                elif isinstance(positions, list):
                    pos_list = positions
                else:
                    pos_list = []

                us100_positions = [
                    p for p in pos_list
                    if int(p.get('tradableInstrumentId', 0)) == INSTRUMENT_ID
                ]
                if us100_positions:
                    pos = us100_positions[0]
                    self.executor.active_position_id = int(pos.get('id', 0))
                    pos_side = Side.LONG if pos.get('side', '').lower() == 'buy' else Side.SHORT
                    log.info(f"Found active US100 position on TradeLocker during bootstrap: {pos}")
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
                            risk_usd=RISK_USD,
                            entry_time=now_ist,
                            entry_candle_idx=0,
                        )
                        sess.trades.append(trade)
                        sess.active_trade = trade
                        self.executor.active_trade = trade
            except Exception as e:
                log.warning(f"TradeLocker bootstrap position check warning: {e}")

            log.info(f"Bootstrap complete. Range locked: {sess.range is not None}, Active trade: {sess.active_trade is not None}")
        finally:
            self.is_bootstrapping = False

    def _main_loop(self):
        log.info("Main loop running. Monitoring US100 and executing strategy...")
        while True:
            try:
                now_ist = datetime.now(tz=IST)
                self.scheduler.check(now_ist)
                sess = self.engine.current_session
                current_price = self._get_current_price()

                # 1. Check limit order fills
                filled_trade = self.executor.check_orders_and_positions()
                if filled_trade:
                    try:
                        asyncio.run(post_telemetry_trade("TradeLocker", filled_trade, symbol=SYMBOL))
                    except Exception as e:
                        log.warning(f"Telemetry trade update error: {e}")

                # 2. Check 5m closed candles FOR RANGE DETECTION AND HEARTBEAT ONLY
                candles = self._fetch_candles(limit=4)
                if len(candles) >= 2:
                    last_closed = candles[-2]
                    if self._last_candle_ts != last_closed.timestamp:
                        self._last_candle_ts = last_closed.timestamp
                        self.engine.candle_idx += 1

                        try:
                            asyncio.run(post_telemetry_heartbeat(
                                "TradeLocker", last_closed.high, last_closed.low, last_closed.close
                            ))
                        except Exception:
                            pass

                        if sess and sess.range is None:
                            sess.candle_buffer.append(last_closed)
                            if len(sess.candle_buffer) >= 2:
                                found = find_us100_range(sess.candle_buffer, sess.start_time)
                                if found:
                                    sess.range = found
                                    log.info(
                                        f"Range locked | upper={found.upper:.2f} "
                                        f"lower={found.lower:.2f} width={found.width:.2f}pts"
                                    )
                                    try:
                                        asyncio.run(post_telemetry_range("TradeLocker", sess, symbol=SYMBOL))
                                    except Exception as e:
                                        log.error(f"Telemetry range error: {e}")

                # 3. If an active trade is open: SYNC WITH REAL TRADELOCKER!
                if sess and sess.active_trade and self.executor.pending_order is None:
                    # Enforce Cutoff
                    if self.engine._past_cutoff(sess, now_ist):
                        log.info(f"Session cutoff reached at {now_ist.strftime('%H:%M:%S IST')}. Closing open position...")
                        trade = sess.active_trade
                        self.executor.close_trade_orders(reason="CUTOFF")
                        self.engine._close_trade(trade, current_price, now_ist, "CUTOFF")
                        sess.active_trade = None
                        try:
                            asyncio.run(post_telemetry_trade("TradeLocker", trade, symbol=SYMBOL))
                        except Exception:
                            pass
                        continue

                    # Update trailing in memory first
                    if current_price > 0:
                        old_sl = sess.active_trade.sl_price
                        self.engine._update_trail(sess.active_trade, current_price)
                        if abs(sess.active_trade.sl_price - old_sl) > 0.5:
                            self.executor.amend_sl(sess.active_trade.sl_price)

                    # Reconcile with TradeLocker position
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
                            asyncio.run(post_telemetry_trade("TradeLocker", trade, symbol=SYMBOL))
                        except Exception as e:
                            log.warning(f"Telemetry close trade error: {e}")

                        # Determine if session target reached or if we retrade
                        if exit_event in ("CLOSED_TP", "CLOSED_TRAIL_SL") or trade.sl_at_entry:
                            sess.target_hit = True
                            log.info(f"Session target achieved with profit/breakeven exit ({reason}). Done for session.")
                        elif exit_event in ("CLOSED_SL", "CLOSED_EMERGENCY"):
                            # Raw SL hit (loss): Check Retrade eligibility
                            log.info(f"Trade {trade.trade_num} hit SL. Checking retrade (trades taken: {sess.trade_count}/{MAX_TRADES_PER_SESSION})...")
                            if sess.can_take_new_trade and not self.engine._past_cutoff(sess, now_ist):
                                next_side = sess.next_side()
                                if next_side:
                                    entry_price = sess.range.upper if next_side == Side.LONG else sess.range.lower
                                    log.info(f"RETRADE TRIGGERED: Placing opposite {next_side.value.upper()} limit order at {entry_price:.2f}...")
                                    self.engine._open_trade(sess, next_side, entry_price, sess.range, now_ist)
                            elif sess.trade_count >= MAX_TRADES_PER_SESSION:
                                log.info(f"Session trade limit reached ({sess.trade_count}/{MAX_TRADES_PER_SESSION}). No re-trade (Done for session).")

                # 4. If a pending limit entry order is waiting:
                if self.executor.pending_order:
                    pending_trade = self.executor.pending_order['trade']
                    is_long = (pending_trade.side == Side.LONG)
                    rr_1_7_target = pending_trade.price_at_r(1.7)

                    # Check if past session cutoff
                    if sess and self.engine._past_cutoff(sess, now_ist):
                        log.info(f"Session cutoff reached at {now_ist.strftime('%H:%M:%S IST')} while limit order pending. Cancelling order.")
                        self.executor.cancel_pending(reason="CUTOFF")
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
                            self.executor.cancel_pending(reason="1:1.7 R:R reached without fill")
                            sess.active_trade = None
                            sess.target_hit = True
                            if pending_trade in sess.trades:
                                pending_trade.state = TradeState.CLOSED
                                pending_trade.exit_price = current_price
                                pending_trade.exit_reason = "CANCELLED_1.7R"
                                pending_trade.exit_time = now_ist
                                try:
                                    asyncio.run(post_telemetry_trade("TradeLocker", pending_trade, symbol=SYMBOL))
                                except Exception as e:
                                    log.warning(f"Telemetry trade update error: {e}")

                        elif is_long and sess and sess.range and current_price <= sess.range.lower:
                            log.info("Price reversed through lower boundary while Long limit order was pending. Cancelling order.")
                            self.executor.cancel_pending(reason="Reversed through opposite boundary")
                            sess.active_trade = None
                            if pending_trade in sess.trades:
                                sess.trades.remove(pending_trade)

                        elif not is_long and sess and sess.range and current_price >= sess.range.upper:
                            log.info("Price reversed through upper boundary while Short limit order was pending. Cancelling order.")
                            self.executor.cancel_pending(reason="Reversed through opposite boundary")
                            sess.active_trade = None
                            if pending_trade in sess.trades:
                                sess.trades.remove(pending_trade)

                # 5. If hunting for breakout:
                elif sess and sess.range and not self.engine._past_cutoff(sess, now_ist):
                    if sess.active_trade is None and sess.can_take_new_trade:
                        rng = sess.range
                        if current_price >= rng.upper:
                            side = sess.next_side()
                            if side in (None, Side.LONG):
                                log.info(f"Real-time breakout: price {current_price:.2f} >= upper {rng.upper:.2f}! Placing Limit Buy...")
                                self.engine._open_trade(sess, Side.LONG, rng.upper, rng, now_ist)
                        elif current_price <= rng.lower:
                            side = sess.next_side()
                            if side in (None, Side.SHORT):
                                log.info(f"Real-time breakout: price {current_price:.2f} <= lower {rng.lower:.2f}! Placing Limit Sell...")
                                self.engine._open_trade(sess, Side.SHORT, rng.lower, rng, now_ist)

                # 6. Check if Friday trading is completed and bot should stop for the weekend
                if self._is_weekend_completed(sess, now_ist):
                    self._stop_for_weekend()
                    break

            except Exception as e:
                log.error(f"Main loop error: {e}", exc_info=True)

            time.sleep(3)

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

        if self.executor.pending_order is not None:
            return False

        if sess and sess.active_trade is not None:
            return False

        # US100 CFD does not trade on the weekend
        if w in (5, 6) or (w == 0 and (h < 7 or (h == 7 and m < 55))):
            return True

        if w == 4 and sess:
            if sess.target_hit or sess.trade_count >= Config.MAX_TRADES:
                return True
            if self.engine._past_cutoff(sess, now_ist):
                return True

        return False

    def _stop_for_weekend(self):
        app_name = "foxalgo-tradelocker-us100"
        log.info(f"[WEEKEND_STOP] Friday trades completed and flat for {SYMBOL}. Stopping PM2 process {app_name} for the weekend.")
        try:
            state_dir = os.path.expanduser("~/foxAlgo/.weekend_state")
            os.makedirs(state_dir, exist_ok=True)
            with open(os.path.join(state_dir, f"{app_name}.json"), "w") as f:
                json.dump({
                    "app": app_name,
                    "symbol": SYMBOL,
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


if __name__ == "__main__":
    runner = TradeLockerLiveRunner()
    runner.start()
