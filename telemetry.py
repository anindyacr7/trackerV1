import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("Telemetry")

API_URL = "https://tracker-worker.foxledger.workers.dev/api/live"

async def _post(endpoint: str, payload: dict):
    # Fire and forget with short timeout
    import aiohttp
    try:
        url = f"{API_URL}/{endpoint}"
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status >= 400:
                    text = await r.text()
                    log.warning(f"Telemetry {endpoint} failed: {r.status} {text}")
    except Exception as e:
        log.warning(f"Telemetry {endpoint} network error: {e}")

async def post_telemetry_range(exchange: str, session, symbol: Optional[str] = None):
    if not session or not session.range:
        return
    rng = session.range
    sym = symbol or getattr(session, 'symbol', None)
    payload = {
        "exchange": exchange,
        "symbol": sym,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "session_type": session.id.value,
        "range_start": rng.candle1.timestamp.isoformat(),
        "range_high": rng.upper,
        "range_low": rng.lower
    }
    await _post("range", payload)

async def post_telemetry_trade(exchange: str, trade, symbol: Optional[str] = None):
    entry_time = getattr(trade, 'entry_time', None) or getattr(trade, 'open_time', None) or datetime.now(timezone.utc)
    close_time = getattr(trade, 'close_time', None) or getattr(trade, 'exit_time', None)
    sess_id = getattr(trade, 'session_id', None)
    session_type = getattr(sess_id, 'value', str(sess_id)) if sess_id else None
    sym = symbol or getattr(trade, 'symbol', None)
    pnl = getattr(trade, 'r_multiple', None)
    if pnl is None:
        pnl = getattr(trade, 'pnl_r', None)
    payload = {
        "exchange": exchange,
        "symbol": sym,
        "trade_num": trade.trade_num,
        "session_type": session_type,
        "side": "LONG" if (getattr(trade.side, 'name', str(trade.side)).upper() == "LONG") else "SHORT",
        "entry_price": trade.entry_price,
        "tp_price": trade.tp_price,
        "sl_price": getattr(trade, 'sl_price', None) or getattr(trade, '_last_sl_price', None),
        "exit_price": getattr(trade, 'exit_price', None),
        "pnl": pnl,
        "status": "OPEN" if getattr(trade, 'exit_price', None) is None else "CLOSED",
        "open_time": entry_time.isoformat() if hasattr(entry_time, 'isoformat') else str(entry_time),
        "close_time": close_time.isoformat() if close_time and hasattr(close_time, 'isoformat') else None
    }
    await _post("trade", payload)

async def post_telemetry_heartbeat(exchange: str, high: float, low: float, close: float):
    payload = {
        "exchange": exchange,
        "high": high,
        "low": low,
        "close": close,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    await _post("heartbeat", payload)
