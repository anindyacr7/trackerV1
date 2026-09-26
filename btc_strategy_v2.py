"""
BTC Breakout Range Strategy — Base Algo v3 (Overlap Control + No Range Filters)
Instrument : BTCUSDT
Timeframe  : 5-minute candles
Timezone   : IST (Asia/Kolkata, UTC+5:30)

Updates in v3:
  1. Overlap control: instantly cuts past session trades when a new session triggers.
  2. Cross-session trade management: tracks active trades across session rollovers.
  3. Removed all range % filters (retrades strictly governed by max trade count).
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

class Config:
    MODE = "backtest"          # "backtest" | "live"

    EXCHANGE_ID        = "binance"
    SYMBOL             = "BTC/USDT"
    TIMEFRAME          = "5m"

    S1_START           = (8, 0)
    S2_START           = (20, 0)
    S1_CUTOFF          = (17, 30)
    S2_CUTOFF          = (5, 30)

    BOUNDARY_BUFFER    = 10
    BODYLESS_THRESHOLD = 5
    MAX_TRADES         = 3

    TRAIL_1_TRIGGER    = 1.7
    TRAIL_2_TRIGGER    = 2.8
    TRAIL_3_TRIGGER    = 3.8
    TRAIL_4_TRIGGER    = 4.8          # 4.8R hit → SL to 4R
    FIXED_TP           = 5.0

    FRIDAY_CARRY_CUTOFF = (5, 30)
    FRIDAY_CARRY_TP    = 3.0

    RISK_PER_TRADE_USDT = 25.0

    IST = ZoneInfo("Asia/Kolkata")


# ─────────────────────────────────────────────
#  ENUMS & DATA CLASSES
# ─────────────────────────────────────────────

class Side(Enum):
    LONG  = "long"
    SHORT = "short"

class SessionID(Enum):
    S1 = "S1_morning"
    S2 = "S2_evening"

class TradeState(Enum):
    OPEN   = "open"
    CLOSED = "closed"


@dataclass
class Candle:
    timestamp : datetime
    open      : float
    high      : float
    low       : float
    close     : float
    volume    : float

    @property
    def is_green(self)    -> bool:  return self.close > self.open
    @property
    def is_red(self)      -> bool:  return self.close < self.open
    @property
    def body_size(self)   -> float: return abs(self.close - self.open)
    @property
    def is_bodyless(self) -> bool:  return self.body_size <= Config.BODYLESS_THRESHOLD

    def sim_prices(self, side: Optional['Side']) -> list:
        """
        Direction-aware intra-candle price simulation.
        Long  → O → H → L → C  (check upside first, then downside)
        Short → O → L → H → C  (check downside first, then upside)
        No trade / unknown → O → H → L → C (breakout from top first)
        """
        if side == Side.SHORT:
            return [self.open, self.low, self.high, self.close]
        else:
            return [self.open, self.high, self.low, self.close]


@dataclass
class Range:
    upper   : float
    lower   : float
    candle1 : Candle
    candle2 : Candle

    @property
    def width(self) -> float:
        return self.upper - self.lower


@dataclass
class Trade:
    id           : int
    session_id   : SessionID
    trade_num    : int
    side         : Side
    entry_price  : float
    sl_price     : float
    tp_price     : float
    risk_pts     : float
    risk_usd     : float
    entry_time       : datetime
    entry_candle_idx : int          # track which candle opened this trade
    entry_boundary   : float = 0.0  # boundary price — R:R base (not fill)
    state        : TradeState = TradeState.OPEN
    exit_price   : Optional[float] = None
    exit_time    : Optional[datetime] = None
    r_multiple   : float = 0.0
    pnl_usd      : float = 0.0
    exit_reason  : str = ""

    sl_at_entry  : bool = False
    sl_at_2r     : bool = False
    sl_at_3r     : bool = False
    sl_at_4r     : bool = False

    def price_at_r(self, r: float) -> float:
        if self.side == Side.LONG:
            return self.entry_boundary + r * self.risk_pts
        return self.entry_boundary - r * self.risk_pts

    def current_r(self, price: float) -> float:
        if self.side == Side.LONG:
            return (price - self.entry_boundary) / self.risk_pts
        return (self.entry_boundary - price) / self.risk_pts


@dataclass
class Session:
    id               : SessionID
    start_time       : datetime
    range            : Optional[Range] = None
    trades           : list = field(default_factory=list)
    active_trade     : Optional[Trade] = None
    candle_buffer    : list = field(default_factory=list)
    target_hit       : bool = False   # True once any trailing-SL or TP exit occurs

    @property
    def trade_count(self) -> int: return len(self.trades)

    @property
    def can_take_new_trade(self) -> bool:
        return self.trade_count < Config.MAX_TRADES and not self.target_hit

    def next_side(self) -> Optional[Side]:
        if not self.trades:
            return None
        return Side.SHORT if self.trades[-1].side == Side.LONG else Side.LONG


# ─────────────────────────────────────────────
#  CORE STRATEGY ENGINE
# ─────────────────────────────────────────────

class StrategyEngine:

    def __init__(self):
        self.current_session : Optional[Session] = None
        self.all_sessions    : list[Session] = []
        self.trade_counter   : int = 0
        self.candle_idx      : int = 0          # global candle counter
        self.log = logging.getLogger("Strategy")
        self.bt_trades : list[Trade] = []

    # ── RANGE DETECTION ──────────────────────

    def _valid_pair(self, c1: Candle, c2: Candle) -> bool:
        if c1.is_bodyless or c2.is_bodyless:
            return False
        return (c1.is_red and c2.is_green) or (c1.is_green and c2.is_red)

    def find_range(self, candles: list[Candle], start_time: datetime = None) -> Optional[Range]:
        if start_time:
            candles = [c for c in candles if c.timestamp >= start_time]
        for i in range(len(candles) - 1):
            c1, c2 = candles[i], candles[i + 1]
            if self._valid_pair(c1, c2):
                return Range(
                    upper   = max(c1.high, c2.high) + Config.BOUNDARY_BUFFER,
                    lower   = min(c1.low,  c2.low)  - Config.BOUNDARY_BUFFER,
                    candle1 = c1,
                    candle2 = c2,
                )
        return None

    # ── SESSION & TRADE MANAGEMENT ────────────

    def start_session(self, session_id: SessionID, now: datetime):
        self.current_session = Session(id=session_id, start_time=now)
        self.all_sessions.append(self.current_session)
        self.log.debug(f"── {session_id.value} started {now.strftime('%Y-%m-%d %H:%M')} ──")

    def _past_cutoff(self, session: Session, now: datetime) -> bool:
        ist = now.astimezone(Config.IST)
        h, m = ist.hour, ist.minute
        if session.id == SessionID.S1:
            ch, cm = Config.S1_CUTOFF
            return (h > ch) or (h == ch and m >= cm)
        else:
            ch, cm = Config.S2_CUTOFF
            return (h < 8) and ((h > ch) or (h == ch and m >= cm))

    def _friday_carry_active(self, trade: Trade, now: datetime) -> bool:
        ist_now   = now.astimezone(Config.IST)
        ist_entry = trade.entry_time.astimezone(Config.IST)
        if ist_entry.weekday() != 4:
            return False
        ch, cm = Config.FRIDAY_CARRY_CUTOFF
        w = ist_now.weekday()
        if w == 5: # Saturday
            return (ist_now.hour > ch or (ist_now.hour == ch and ist_now.minute >= cm))
        elif w == 6: # Sunday
            return True
        elif w == 0 and ist_now.hour < 8: # Monday pre-market
            return True
        return False

    def get_open_trade_and_session(self) -> tuple[Optional[Trade], Optional[Session]]:
        """Returns the currently active trade and its parent session globally."""
        for s in reversed(self.all_sessions):
            if s.active_trade and s.active_trade.state == TradeState.OPEN:
                return s.active_trade, s
        return None, None

    def _open_trade(self, session: Session, side: Side,
                    entry: float, rng: Range, now: datetime) -> Trade:
        self.trade_counter += 1
        risk_pts = rng.width
        sl = rng.lower if side == Side.LONG else rng.upper
        boundary = rng.upper if side == Side.LONG else rng.lower
        tp = (boundary + Config.FIXED_TP * risk_pts if side == Side.LONG
              else boundary - Config.FIXED_TP * risk_pts)

        trade = Trade(
            id               = self.trade_counter,
            session_id       = session.id,
            trade_num        = session.trade_count + 1,
            side             = side,
            entry_price      = entry,
            entry_boundary   = boundary,
            sl_price         = sl,
            tp_price         = tp,
            risk_pts         = risk_pts,
            risk_usd         = Config.RISK_PER_TRADE_USDT,
            entry_time       = now,
            entry_candle_idx = self.candle_idx,
        )
        session.trades.append(trade)
        session.active_trade = trade
        self.bt_trades.append(trade)
        self.log.debug(
            f"  TR{trade.trade_num} OPEN {side.value.upper()} @ {entry:.1f} "
            f"SL={sl:.1f} TP={tp:.1f} 1R={risk_pts:.1f}pts"
        )
        return trade

    def _close_trade(self, trade: Trade, exit_price: float,
                     now: datetime, reason: str):
        trade.exit_price  = exit_price
        trade.exit_time   = now
        trade.r_multiple  = trade.current_r(exit_price)
        trade.pnl_usd     = trade.r_multiple * trade.risk_usd
        trade.state       = TradeState.CLOSED
        trade.exit_reason = reason
        self.log.debug(
            f"  TR{trade.trade_num} CLOSE {reason:10} @ {exit_price:.1f} "
            f"R={trade.r_multiple:+.2f}"
        )

    # ── TRAILING SL ───────────────────────────

    def _update_trail(self, trade: Trade, price: float) -> Optional[str]:
        r = trade.current_r(price)
        if r >= Config.FIXED_TP:
            return "CLOSE_5R"
        
        if not trade.sl_at_entry and r >= Config.TRAIL_1_TRIGGER:
            trade.sl_price    = trade.entry_price
            trade.sl_at_entry = True
        if not trade.sl_at_2r and r >= Config.TRAIL_2_TRIGGER:
            trade.sl_price = trade.price_at_r(2.0)
            trade.sl_at_2r = True
        if not trade.sl_at_3r and r >= Config.TRAIL_3_TRIGGER:
            trade.sl_price = trade.price_at_r(3.0)
            trade.sl_at_3r = True
        if not trade.sl_at_4r and r >= Config.TRAIL_4_TRIGGER:
            trade.sl_price = trade.price_at_r(4.0)
            trade.sl_at_4r = True
        return None

    def _sl_hit(self, trade: Trade, price: float) -> bool:
        return (price <= trade.sl_price if trade.side == Side.LONG
                else price >= trade.sl_price)

    # ── PROCESS ONE CANDLE ────────────────────

    def process_candle(self, candle: Candle, current_session: Session):
        now = candle.timestamp

        # Apply Friday carry-forward to the global active trade before checking prices
        active, active_session = self.get_open_trade_and_session()
        if active and self._friday_carry_active(active, now):
            active.tp_price = active.price_at_r(Config.FRIDAY_CARRY_TP)
            active.sl_price = active.entry_price
            active.sl_at_entry = True

        # Determine price sequence (Direction-aware based on active trade)
        prices = candle.sim_prices(active.side if active else None)

        for price in prices:
            active, active_session = self.get_open_trade_and_session()

            # ── 1. Manage Active Trade ──
            if active:
                # Check TP
                tp_hit = (active.side == Side.LONG and price >= active.tp_price) or \
                         (active.side == Side.SHORT and price <= active.tp_price)
                if tp_hit:
                    self._close_trade(active, active.tp_price, now, "TP_5R")
                    active_session.active_trade = None
                    active_session.target_hit = True
                    continue 

                # Check Trail
                action = self._update_trail(active, price)
                if action == "CLOSE_5R":
                    self._close_trade(active, price, now, "TP_5R")
                    active_session.active_trade = None
                    active_session.target_hit = True
                    continue

                # Check SL (skip if entry candle)
                if active.entry_candle_idx != self.candle_idx:
                    if self._sl_hit(active, price):
                        trailing_exit = active.sl_at_entry
                        reason = "TRAIL_SL" if trailing_exit else "SL"
                        self._close_trade(active, active.sl_price, now, reason)
                        active_session.active_trade = None

                        if trailing_exit:
                            active_session.target_hit = True
                        else:
                            # Raw SL hit -> Retrade logic
                            # ONLY retrade if the SL belonged to the CURRENT session.
                            # If an S1 trade hits SL during S2, S1 is over, do NOT retrade for S1.
                            if (active_session == current_session and 
                                current_session.can_take_new_trade and 
                                not self._past_cutoff(current_session, now)):
                                
                                next_side = current_session.next_side()
                                if next_side:
                                    entry_price = (current_session.range.upper if next_side == Side.LONG 
                                                   else current_session.range.lower)
                                    self._open_trade(current_session, next_side, entry_price, current_session.range, now)
                        continue

            # ── 2. Look for Breakout ──
            # Only hunt if current session hasn't taken a trade yet
            if (current_session.range and current_session.trade_count == 0 and 
                current_session.can_take_new_trade and not self._past_cutoff(current_session, now)):
                
                trigger_long  = price >= current_session.range.upper
                trigger_short = price <= current_session.range.lower

                if trigger_long or trigger_short:
                    # Breakout confirmed!
                    # Cut previous trade if it still exists (Overlap protocol)
                    active, active_session = self.get_open_trade_and_session()
                    if active:
                        self._close_trade(active, price, now, "OVERLAP_CUT")
                        active_session.active_trade = None

                    # Enter new trade
                    side = Side.LONG if trigger_long else Side.SHORT
                    entry = current_session.range.upper if side == Side.LONG else current_session.range.lower
                    self._open_trade(current_session, side, entry, current_session.range, now)


# ─────────────────────────────────────────────
#  SESSION SCHEDULER
# ─────────────────────────────────────────────

class _SessionScheduler:
    def __init__(self, engine: StrategyEngine):
        self.engine  = engine
        self.last_s1 = None
        self.last_s2 = None

    def check(self, ist: datetime):
        if ist.weekday() >= 5:
            return
        date_key = ist.date()
        s1h, s1m = Config.S1_START
        s2h, s2m = Config.S2_START
        if ist.hour == s1h and ist.minute == s1m and self.last_s1 != date_key:
            self.last_s1 = date_key
            self.engine.start_session(SessionID.S1, ist.replace(second=0, microsecond=0))
        if ist.hour == s2h and ist.minute == s2m and self.last_s2 != date_key:
            self.last_s2 = date_key
            self.engine.start_session(SessionID.S2, ist.replace(second=0, microsecond=0))


# ─────────────────────────────────────────────
#  BACKTESTING ENGINE
# ─────────────────────────────────────────────

class Backtester:
    def __init__(self, engine: StrategyEngine):
        self.engine    = engine
        self.scheduler = _SessionScheduler(engine)
        self.log       = logging.getLogger("Backtest")

    def run_csv(self, filepath: str):
        import csv
        self.log.info(f"Loading {filepath}")
        candles = []
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = datetime.fromisoformat(row["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                candles.append(Candle(
                    timestamp = ts,
                    open      = float(row["open"]),
                    high      = float(row["high"]),
                    low       = float(row["low"]),
                    close     = float(row["close"]),
                    volume    = float(row["volume"]),
                ))
        self.log.info(f"Loaded {len(candles):,} candles")
        self._replay(candles)
        self._print_summary()

    def _replay(self, candles: list[Candle]):
        for candle in candles:
            ist_time = candle.timestamp.astimezone(Config.IST)

            if ist_time.weekday() >= 5:
                continue

            self.engine.candle_idx += 1
            self.scheduler.check(ist_time)

            session = self.engine.current_session
            if session is None:
                continue

            session.candle_buffer.append(candle)

            if session.range is None and len(session.candle_buffer) >= 2:
                found = self.engine.find_range(session.candle_buffer, session.start_time)
                if found:
                    session.range = found
                    try:
                        import asyncio, telemetry
                        asyncio.get_event_loop().run_until_complete(telemetry.post_telemetry_range("Binance", session))
                    except: pass
                    self.log.debug(
                        f"  Range: upper={found.upper:.1f} "
                        f"lower={found.lower:.1f} width={found.width:.1f}"
                    )

            self.engine.process_candle(candle, session)

    def _print_summary(self):
        trades = self.engine.bt_trades
        if not trades:
            print("\nNo trades taken.")
            return

        closed = [t for t in trades if t.state == TradeState.CLOSED]
        if not closed:
            print("\nNo closed trades.")
            return

        total_r   = sum(t.r_multiple for t in closed)
        total_pnl = sum(t.pnl_usd for t in closed)
        wins      = [t for t in closed if t.r_multiple > 0]
        losses    = [t for t in closed if t.r_multiple <= 0]
        win_rate  = len(wins) / len(closed) * 100

        from collections import Counter
        reasons = Counter(t.exit_reason for t in closed)

        r_dist = {"5R": 0, "4R": 0, "3R": 0, "2R": 0, "0R": 0, "-1R": 0, "other": 0}
        for t in closed:
            r = round(t.r_multiple, 1)
            if r >= 4.9:    r_dist["5R"]  += 1
            elif r >= 3.9:  r_dist["4R"]  += 1
            elif r >= 2.9:  r_dist["3R"]  += 1
            elif r >= 1.9:  r_dist["2R"]  += 1
            elif r >= -0.1: r_dist["0R"]  += 1
            elif r >= -1.1: r_dist["-1R"] += 1
            else:           r_dist["other"] += 1

        print("\n" + "═"*57)
        print("  BACKTEST RESULTS  (v3 — Overlap Control)")
        print("═"*57)
        print(f"  Total trades    : {len(closed)}")
        print(f"  Win rate        : {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
        print(f"  Total R         : {total_r:+.2f}R")
        print(f"  Total PnL       : ${total_pnl:+.2f}  (at $100/R)")
        print(f"  Avg R/trade     : {total_r/len(closed):+.2f}R")
        print(f"  Best trade      : {max(t.r_multiple for t in closed):+.2f}R")
        print(f"  Worst trade     : {min(t.r_multiple for t in closed):+.2f}R")
        print("─"*57)
        print(f"  Exit breakdown  : {dict(reasons)}")
        print(f"  R distribution  : {r_dist}")
        print("═"*57)

        for sid in SessionID:
            s_trades = [t for t in closed if t.session_id == sid]
            if not s_trades:
                continue
            r  = sum(t.r_multiple for t in s_trades)
            wr = sum(1 for t in s_trades if t.r_multiple > 0) / len(s_trades) * 100
            print(f"  {sid.value:<20}  n={len(s_trades):>4}  "
                  f"R={r:+7.2f}  WR={wr:.0f}%")
        print("═"*57 + "\n")


# ─────────────────────────────────────────────
#  MONTHLY BREAKDOWN
# ─────────────────────────────────────────────

def print_monthly_breakdown(bt_trades):
    from collections import defaultdict
    import itertools

    closed = [t for t in bt_trades if t.state == TradeState.CLOSED]
    if not closed:
        return

    monthly = defaultdict(list)
    for t in closed:
        ist = t.entry_time.astimezone(Config.IST)
        key = ist.strftime("%Y-%m")
        monthly[key].append(t)

    months_order = sorted(monthly.keys())

    print("\n" + "═"*75)
    print("  MONTHLY BREAKDOWN")
    print("═"*75)
    print(f"  {'Month':<10} {'Trades':>6} {'WR%':>5} {'Total R':>8} "
          f"{'Avg R':>7} {'MaxDD':>6} {'S1 R':>7} {'S2 R':>7} {'BadDays':>8}")
    print("─"*75)

    all_monthly_r   = []
    all_monthly_tot = []

    for key in months_order:
        trades = monthly[key]
        label  = datetime.strptime(key, "%Y-%m").strftime("%b %Y")

        total_r = sum(t.r_multiple for t in trades)
        wins    = sum(1 for t in trades if t.r_multiple > 0)
        wr      = wins / len(trades) * 100

        s1_r = sum(t.r_multiple for t in trades if t.session_id == SessionID.S1)
        s2_r = sum(t.r_multiple for t in trades if t.session_id == SessionID.S2)

        cum = list(itertools.accumulate(t.r_multiple for t in trades))
        peak = cum[0]; mdd = 0
        for c in cum:
            if c > peak: peak = c
            if peak - c > mdd: mdd = peak - c

        day_pnl = defaultdict(float)
        for t in trades:
            day = t.entry_time.astimezone(Config.IST).date()
            day_pnl[day] += t.r_multiple
        bad_days = sum(1 for v in day_pnl.values() if v <= -3)

        all_monthly_r.append(total_r)
        all_monthly_tot.append(len(trades))

        print(f"  {label:<10} {len(trades):>6} {wr:>4.0f}% {total_r:>+8.2f}R "
              f"{total_r/len(trades):>+6.2f}R {mdd:>5.1f}R "
              f"{s1_r:>+6.2f}R {s2_r:>+6.2f}R {bad_days:>8}")

    print("─"*75)
    grand_total = sum(all_monthly_r)
    grand_n     = sum(all_monthly_tot)
    print(f"  {'TOTAL':<10} {grand_n:>6} {'':>5} {grand_total:>+8.2f}R "
          f"{grand_total/grand_n:>+6.2f}R")
    print("═"*75)


# ─────────────────────────────────────────────
#  LIVE RUNNER (Placeholder)
# ─────────────────────────────────────────────

class LiveRunner:
    def __init__(self, engine: StrategyEngine):
        import ccxt
        import os
        self.engine    = engine
        self.scheduler = _SessionScheduler(engine)
        self.log       = logging.getLogger("Live")
        # Production client for accurate live market candles
        self.market_client = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        # Demo trading client for order execution
        self.client = ccxt.binance({
            "apiKey": os.environ.get("BINANCE_API_KEY") or os.environ.get("EXCHANGE_API_KEY", ""),
            "secret": os.environ.get("BINANCE_API_SECRET") or os.environ.get("EXCHANGE_SECRET", ""),
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        self.client.enable_demo_trading(True)
        self.symbol = "BTC/USDT:USDT"

        self.active_orders = {}

    def run(self):
        import time
        self.log.info("Starting Binance Testnet CCXT Runner...")
        self._patch_engine()

        last_candle_ts = None
        while True:
            try:
                now   = datetime.now(tz=Config.IST)
                self.scheduler.check(now)
                candles = self._fetch_candles(3)
                if candles:
                    last_closed = candles[-2]
                    if last_closed.timestamp != last_candle_ts:
                        last_candle_ts = last_closed.timestamp
                        self.engine.candle_idx += 1
                        try:
                            import asyncio, telemetry
                            asyncio.get_event_loop().run_until_complete(telemetry.post_telemetry_heartbeat("Binance", last_closed.high, last_closed.low, last_closed.close))
                        except Exception as e:
                            pass
                        session = self.engine.current_session
                        if session:
                            session.candle_buffer.append(last_closed)
                            if session.range is None and len(session.candle_buffer) >= 2:
                                found = self.engine.find_range(session.candle_buffer, session.start_time)
                                if found:
                                    session.range = found
                                    try:
                                        import asyncio, telemetry
                                        asyncio.get_event_loop().run_until_complete(telemetry.post_telemetry_range("Binance", session))
                                    except: pass
                            self.engine.process_candle(last_closed, session)

                time.sleep(5)
            except KeyboardInterrupt:
                self.log.info("Stopped"); break
            except Exception as e:
                self.log.error(f"{e}", exc_info=True); time.sleep(10)

    def _patch_engine(self):
        original_open = self.engine._open_trade
        original_close = self.engine._close_trade
        original_update = self.engine._update_trail

        def patched_open(session, side, entry, rng, now):
            trade = original_open(session, side, entry, rng, now)
            self._execute_entry(trade)
            return trade

        def patched_close(trade, exit_price, now, reason):
            original_close(trade, exit_price, now, reason)
            self._execute_close(trade, reason)

        def patched_update(trade, price):
            action = original_update(trade, price)
            if hasattr(trade, '_last_sl_price') and trade.sl_price != trade._last_sl_price:
                self._amend_sl(trade)
            trade._last_sl_price = trade.sl_price
            return action

        self.engine._open_trade = patched_open
        self.engine._close_trade = patched_close
        self.engine._update_trail = patched_update

    def _execute_entry(self, trade: Trade):
        try:
            sl_pts = abs(trade.entry_boundary - trade.sl_price)
            if sl_pts <= 0: return
            qty = round(Config.RISK_PER_TRADE_USDT / sl_pts, 3)
            if qty < 0.001: qty = 0.001

            is_long = trade.side == Side.LONG
            ccxt_side = 'buy' if is_long else 'sell'
            close_side = 'sell' if is_long else 'buy'
            
            self.log.info(f"TR{trade.trade_num} EXECUTING ENTRY: {ccxt_side.upper()} {qty} BTC")
            
            entry_order = self.client.create_order(self.symbol, 'market', ccxt_side, qty)
            sl_params = {'stopPrice': round(trade.sl_price, 1), 'reduceOnly': True}
            sl_order = self.client.create_order(self.symbol, 'STOP_MARKET', close_side, qty, params=sl_params)
            tp_params = {'stopPrice': round(trade.tp_price, 1), 'reduceOnly': True}
            tp_order = self.client.create_order(self.symbol, 'TAKE_PROFIT_MARKET', close_side, qty, params=tp_params)

            self.active_orders[trade.id] = {
                'sl': sl_order['id'],
                'tp': tp_order['id'],
                'qty': qty,
                'close_side': close_side
            }
            trade._last_sl_price = trade.sl_price

        except Exception as e:
            self.log.error(f"Entry execution failed: {e}")

    def _execute_close(self, trade: Trade, reason: str):
        try:
            orders = self.active_orders.get(trade.id)
            if not orders: return
            
            for k in ['sl', 'tp']:
                if orders[k]:
                    try:
                        self.client.cancel_order(orders[k], self.symbol)
                    except Exception:
                        pass 

            if reason not in ("SL", "TP_5R", "TRAIL_SL"):
                self.client.create_order(self.symbol, 'market', orders['close_side'], orders['qty'], params={'reduceOnly': True})

            self.active_orders.pop(trade.id, None)
        except Exception as e:
            self.log.error(f"Close execution failed: {e}")

    def _amend_sl(self, trade: Trade):
        try:
            orders = self.active_orders.get(trade.id)
            if not orders or not orders['sl']: return

            try:
                self.client.cancel_order(orders['sl'], self.symbol)
            except Exception:
                pass
            
            sl_params = {'stopPrice': round(trade.sl_price, 1), 'reduceOnly': True}
            new_sl = self.client.create_order(self.symbol, 'STOP_MARKET', orders['close_side'], orders['qty'], params=sl_params)
            orders['sl'] = new_sl['id']
            self.log.info(f"TR{trade.trade_num} TRAILED SL TO {trade.sl_price}")
        except Exception as e:
            self.log.error(f"SL amend failed: {e}")

    def _fetch_candles(self, limit=3) -> list[Candle]:
        try:
            raw = self.market_client.fetch_ohlcv(self.symbol, Config.TIMEFRAME, limit=limit)
        except Exception:
            self.symbol = "BTC/USDT"
            raw = self.market_client.fetch_ohlcv(self.symbol, Config.TIMEFRAME, limit=limit)

        return [Candle(
            timestamp=datetime.fromtimestamp(r[0]/1000, tz=timezone.utc),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]
        ) for r in raw]


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

def main():
    logging.basicConfig(
        level   = logging.WARNING,   
        format  = "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt = "%H:%M:%S"
    )

    engine = StrategyEngine()

    if Config.MODE == "backtest":
        bt = Backtester(engine)
        bt.run_csv("btcusdt_5m.csv")
        print_monthly_breakdown(engine.bt_trades)
    elif Config.MODE == "live":
        runner = LiveRunner(engine)
        runner.run()


if __name__ == "__main__":
    main()
