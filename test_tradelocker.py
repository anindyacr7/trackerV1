from tradelocker import TLAPI
import pandas as pd
from datetime import datetime, timezone

tl = TLAPI(
    environment="https://demo.tradelocker.com",
    username="avilashmohante@gmail.com",
    password='"B3ZRDwdBTu{',
    server="FTRM"
)

# Fetch recent 5m bars for US100 (tradableInstrumentId 4858)
# resolution: '5' (5 minutes)
now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
from_ms = now_ms - (3 * 3600 * 1000) # last 3 hours

bars = tl.get_price_history(
    tradable_instrument_id=4858,
    resolution='5m',
    from_timestamp=from_ms,
    to_timestamp=now_ms
)
print("=== US100 5m Bars ===")
print(bars.tail(10))
