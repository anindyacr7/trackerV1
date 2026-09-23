import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
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
    Candle, Session, Trade
)

log = logging.getLogger("ProprLive")

IST = ZoneInfo("Asia/Kolkata")
RISK_USDT = 25.0       # $25 risk per trade (0.5% on $5,000 prop firm challenge)
TARGET_ACCOUNT_ID = os.getenv("PROPR_ACCOUNT_ID", "urn:prp-account:CRPYZs8zyarB")

# ─────────────────────────────────────────────
#  PROPR ORDER EXECUTOR (LIMIT ORDER EXECUTION)
# ─────────────────────────────────────────────

class ProprOrderExecutor:
    """
    Handles Propr (Hyperliquid) Limit Order breakout execution:
      - Trigger limit buy at range.upper (86500+10) or limit sell at range.lower (86000-10)
      - Once limit order fills, immediately attach native stop_market SL and take_profit_market TP
      - Trailing SL amendment as trade advances
      - Position closing and order cleanup on cutoff or exit
    """

    def __init__(self, client: ProprClient):
        self.client = client
        # Active filled orders: { trade_id: { 'sl': order_id, 'tp': order_id, 'qty': str, 'pos_side': str, 'close_side': str } }
        self.active_orders: dict = {}
        # Pending limit entry order: { 'trade': Trade, 'order_id': str, 'qty_str': str, 'pos_side': str, 'close_side': str, 'limit_price': str, 'placed_time': float }
        self.pending_entry: Optional[dict] = None

    def open_position(self, trade: Trade, btc_price: float):
        sl_pts = abs(trade.entry_boundary - trade.sl_price)
        if sl_pts <= 0:
            log.error(f"Cannot open position: sl_pts <= 0 ({sl_pts})")
            return

        raw_qty = RISK_USDT / sl_pts
        # Cap notional size at 10x leverage max buffer ($45,000 for $5k balance)
        max_notional = 45000.0
        max_qty = max_notional / max(btc_price, 10000.0)
        qty = round(max(0.001, min(raw_qty, max_qty)), 4)
        qty_str = str(qty)

        is_long = (trade.side == Side.LONG)
        side = "buy" if is_long else "sell"
        pos_side = "long" if is_long else "short"
        close_side = "sell" if is_long else "buy"
        limit_price = str(round(trade.entry_boundary, 1))

        log.info(
            f"TR{trade.trade_num} BREAKOUT {trade.side.value.upper()} | "
            f"Triggering LIMIT {side.upper()} order at {limit_price} | "
            f"SL={trade.sl_price:.1f} TP={trade.tp_price:.1f} | qty={qty_str} BTC"
        )

        try:
            # 1. Place Limit Entry order at exact breakout boundary
            entry_res = self.client.create_order(
                side=side,
                position_side=pos_side,
                order_type="limit",
                asset="BTC",
                base="BTC",
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
                    self._place_sl_tp(trade, qty_str, pos_side, close_side)
                else:
                    log.info(f"  Limit order {order_id} resting on book at {limit_price} (status={status}). Awaiting fill to attach SL/TP...")
                    self.pending_entry = {
                        'trade': trade,
                        'order_id': order_id,
                        'qty_str': qty_str,
                        'pos_side': pos_side,
                        'close_side': close_side,
                        'limit_price': limit_price,
                        'placed_time': time.time(),
                    }
        except Exception as e:
            log.error(f"open_position exception: {e}", exc_info=True)

    def _place_sl_tp(self, trade: Trade, qty_str: str, pos_side: str, close_side: str):
        """Place native Stop Loss and Take Profit orders once position is confirmed open."""
        sl_res = None
        try:
            sl_res = self.client.create_order(
                side=close_side,
                position_side=pos_side,
                order_type="stop_market",
                asset="BTC",
                base="BTC",
                quote="USDC",
                quantity=qty_str,
                trigger_price=str(round(trade.sl_price, 1)),
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
                asset="BTC",
                base="BTC",
                quote="USDC",
                quantity=qty_str,
                trigger_price=str(round(trade.tp_price, 1)),
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

        try:
            orders = self.client.get_orders(order_id=order_id)
            if orders:
                status = orders[0].get("status")
                if status == "filled":
                    log.info(f"  Pending limit order {order_id} FILLED at {limit_price}! Placing SL and TP orders...")
                    self.pending_entry = None
                    self._place_sl_tp(trade, qty_str, pos_side, close_side)
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
        if not info:
            return

        # Check if position is still open on exchange
        try:
            positions = self.client.get_open_positions(base="BTC")
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
                asset="BTC",
                base="BTC",
                quote="USDC",
                quantity=info['qty'],
                trigger_price=str(round(new_sl_price, 1)),
                reduce_only=True
            )
            if new_sl_res:
                info['sl'] = new_sl_res[0]['orderId']
                log.info(f"  SL trailed → {new_sl_price:.1f} (Order {info['sl']})")
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

        if reason not in ("SL", "TP_5R", "TRAIL_SL"):
            try:
                positions = self.client.get_open_positions(base="BTC")
                if positions:
                    res = self.client.close_position(base="BTC", quote="USDC")
                    log.info(f"Closed open BTC position on Propr: {res}")
            except Exception as e:
                log.error(f"Failed to close BTC position on Propr: {e}")


# ─────────────────────────────────────────────
#  LIVE RUNNER
# ─────────────────────────────────────────────

class ProprLiveRunner:

    def __init__(self):
        self.engine = StrategyEngine()
        self.scheduler = _SessionScheduler(self.engine)
        self.is_bootstrapping = False

        api_key = os.getenv("PROPR_API_KEY")
        if not api_key:
            raise ValueError("PROPR_API_KEY not configured in environment")

        self.client = ProprClient(api_key=api_key)
        self.account_id = self.client.setup(account_id=TARGET_ACCOUNT_ID)
        self.executor = ProprOrderExecutor(self.client)

        # Public Binance Futures client for accurate 5m market candles & real-time ticker
        self.market_client = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

        self.symbol = "BTC/USDT:USDT"
        self._last_candle_ts: Optional[datetime] = None
        self._last_sl_sent: dict[int, float] = {}

    def start(self):
        log.info(f"=== Propr Live Runner starting for Account: {self.account_id} ===")
        # Verify account details
        try:
            acc = self.client.get_account()
            log.info(f"Account Balance: {acc.get('balance')} {acc.get('currency', 'USDC')} | Type: {acc.get('type')}")
        except Exception as e:
            log.warning(f"Could not fetch account details: {e}")

        # Ensure BTC leverage is 10x
        try:
            self.client.set_leverage(asset="BTC", leverage=10)
            log.info("Verified BTC leverage set to 10x")
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
                ticker_price = self._get_current_price() or entry
                self.executor.open_position(trade, ticker_price)
                try:
                    asyncio.run(post_telemetry_trade("Propr", trade))
                except Exception as e:
                    log.warning(f"Telemetry open trade error: {e}")
            return trade

        def patched_close(trade, exit_price, now, reason):
            original_close(trade, exit_price, now, reason)
            if not self.is_bootstrapping:
                self.executor.close_trade_orders(trade.id, reason)
                try:
                    asyncio.run(post_telemetry_trade("Propr", trade))
                except Exception as e:
                    log.warning(f"Telemetry close trade error: {e}")

        def patched_update(trade, price):
            action = original_update(trade, price)
            if not self.is_bootstrapping:
                last_sl = self._last_sl_sent.get(trade.id, 0)
                if abs(trade.sl_price - last_sl) > 0.5:
                    self.executor.amend_sl(trade.id, trade.sl_price)
                    self._last_sl_sent[trade.id] = trade.sl_price
            return action

        self.engine._open_trade = patched_open
        self.engine._close_trade = patched_close
        self.engine._update_trail = patched_update

    def _get_current_price(self) -> float:
        try:
            ticker = self.market_client.fetch_ticker("BTC/USDT")
            return float(ticker.get("last", 0.0))
        except Exception:
            return 0.0

    def _fetch_candles(self, limit: int = 5) -> list[Candle]:
        try:
            raw = self.market_client.fetch_ohlcv("BTC/USDT", Config.TIMEFRAME, limit=limit)
            return [Candle(
                timestamp=datetime.fromtimestamp(r[0]/1000, tz=timezone.utc),
                open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4]), volume=float(r[5])
            ) for r in raw]
        except Exception as e:
            log.error(f"fetch_candles error: {e}")
            return []

    def _bootstrap_active_session(self):
        """
        If runner is started mid-session (e.g. during S1 08:00-17:30 IST or S2 20:00-05:30 IST),
        bootstrap the session and replay historical candles so range and trades are active immediately.
        """
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
                # Skip the currently open candle
                if (now_utc - c.timestamp).total_seconds() < 290:
                    continue

                self.engine.candle_idx += 1
                sess.candle_buffer.append(c)

                just_locked = False
                if sess.range is None and len(sess.candle_buffer) >= 2:
                    found = self.engine.find_range(sess.candle_buffer, sess.start_time)
                    if found:
                        sess.range = found
                        just_locked = True
                        log.info(f"Range locked | upper={found.upper:.1f} lower={found.lower:.1f} width={found.width:.1f}pts")
                        try:
                            asyncio.run(post_telemetry_range("Propr", sess))
                        except Exception as e:
                            log.warning(f"Telemetry range error: {e}")

                if not just_locked:
                    self.engine.process_candle(c, sess)

            log.info(f"Bootstrap complete. Session candles: {len(sess.candle_buffer)}, Range locked: {sess.range is not None}, Completed trades: {len(sess.trades)}")
        finally:
            self.is_bootstrapping = False

    def _main_loop(self):
        log.info("Main loop running. Monitoring market and executing strategy...")
        while True:
            try:
                now_ist = datetime.now(tz=IST)
                self.scheduler.check(now_ist)

                # 1. Check if a pending limit entry order just got filled
                filled_trade = self.executor.check_pending_entry()
                if filled_trade:
                    try:
                        asyncio.run(post_telemetry_trade("Propr", filled_trade))
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
                                found = self.engine.find_range(sess.candle_buffer, sess.start_time)
                                if found:
                                    sess.range = found
                                    just_locked = True
                                    log.info(
                                        f"Range locked | upper={found.upper:.1f} "
                                        f"lower={found.lower:.1f} width={found.width:.1f}pts"
                                    )
                                    try:
                                        asyncio.run(post_telemetry_range("Propr", sess))
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
                            log.info(f"Real-time breakout detected: price {current_price:.1f} >= upper {sess.range.upper:.1f}! Triggering Limit Buy...")
                            self.engine._open_trade(sess, Side.LONG, sess.range.upper, sess.range, now_ist)
                        elif current_price <= sess.range.lower:
                            log.info(f"Real-time breakout detected: price {current_price:.1f} <= lower {sess.range.lower:.1f}! Triggering Limit Sell...")
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler("propr_live.log", maxBytes=5*1024*1024, backupCount=3),
        ]
    )
    runner = ProprLiveRunner()
    runner.start()

if __name__ == "__main__":
    main()
