import os

def patch_file(path, replacements):
    with open(path, "r") as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            print(f"WARNING: target not found in {path}:\n{old[:60]}...")
        else:
            content = content.replace(old, new, 1)
            print(f"Replaced in {path}: {old[:40]}...")
    with open(path, "w") as f:
        f.write(content)

# Patch foxAlgo/lighter_live.py
lighter_replacements = [
    (
        'BTC_MARKET_ID = 4096       # BTC perp on Lighter Testnet (verify at /api/v1/orderBooks)\n',
        'BTC_MARKET_ID = 4096       # BTC perp on Lighter Testnet (verify at /api/v1/orderBooks)\nMAINNET_URL           = "https://mainnet.zklighter.elliot.ai"\nMAINNET_BTC_MARKET_ID = 1  # BTC perp on Lighter Mainnet (for real candles & price feed)\n'
    ),
    (
        '''        try:
            tx_types = []
            tx_infos = []

            # 1. Market entry
            tx_type, tx_info, tx_hash, err = self.client.sign_create_order(
                market_index     = BTC_MARKET_ID,
                client_order_index = entry_idx,
                base_amount      = qty_int,
                price            = to_lighter_price(entry_worst_price),
                is_ask           = is_ask,
                order_type       = self.client.ORDER_TYPE_MARKET,
                time_in_force    = self.client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only      = False,
                order_expiry     = self.client.DEFAULT_IOC_EXPIRY,
            )
            if err:
                log.error(f"Entry sign error: {err}"); return
            tx_types.append(tx_type)
            tx_infos.append(tx_info)

            # 2. Stop-loss (native SL order, reduce-only)
            tx_type, tx_info, tx_hash, err = self.client.sign_create_order(
                market_index     = BTC_MARKET_ID,
                client_order_index = sl_idx,
                base_amount      = qty_int,
                price            = sl_exec_price,
                is_ask           = not is_ask,   # opposite side to close
                order_type       = self.client.ORDER_TYPE_STOP_LOSS,
                time_in_force    = self.client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only      = True,
                order_expiry     = self.client.DEFAULT_28_DAY_ORDER_EXPIRY,
                trigger_price    = sl_trigger,
            )
            if err:
                log.error(f"SL sign error: {err}"); return
            tx_types.append(tx_type)
            tx_infos.append(tx_info)

            # 3. Take-profit (native TP order, reduce-only)
            tx_type, tx_info, tx_hash, err = self.client.sign_create_order(
                market_index     = BTC_MARKET_ID,
                client_order_index = tp_idx,
                base_amount      = qty_int,
                price            = tp_exec_price,
                is_ask           = not is_ask,
                order_type       = self.client.ORDER_TYPE_TAKE_PROFIT,
                time_in_force    = self.client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only      = True,
                order_expiry     = self.client.DEFAULT_28_DAY_ORDER_EXPIRY,
                trigger_price    = tp_trigger,
            )
            if err:
                log.error(f"TP sign error: {err}"); return
            tx_types.append(tx_type)
            tx_infos.append(tx_info)

            # Send batch
            # self.client.api is likely the TransactionApi instance internally used
            # If not, we can import TransactionApi, but usually it's exposed
            try:
                resp = await self.client.send_tx_batch(tx_types, tx_infos)
            except Exception as e:
                log.error(f"send_tx_batch error: {e}")
                return

            # Store order indices for later amendment / cancellation
            self.active_orders[trade.id] = {
                'sl'  : sl_idx,
                'tp'  : tp_idx,
                'qty' : qty_int,
                'is_ask_close': not is_ask,
            }
            log.info(f"  Orders placed in batch: entry={entry_idx} SL={sl_idx} TP={tp_idx}")

        except Exception as e:
            log.error(f"open_position exception: {e}", exc_info=True)''',
        '''        try:
            # 1. Market entry
            _, resp, err = await self.client.create_order(
                market_index       = BTC_MARKET_ID,
                client_order_index = entry_idx,
                base_amount        = qty_int,
                price              = to_lighter_price(entry_worst_price),
                is_ask             = is_ask,
                order_type         = self.client.ORDER_TYPE_MARKET,
                time_in_force      = self.client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only        = False,
                order_expiry       = self.client.DEFAULT_IOC_EXPIRY,
            )
            if err:
                log.error(f"Entry order error: {err}")
                return

            # 2. Stop-loss (native SL order, reduce-only)
            _, resp, err = await self.client.create_order(
                market_index       = BTC_MARKET_ID,
                client_order_index = sl_idx,
                base_amount        = qty_int,
                price              = sl_exec_price,
                is_ask             = not is_ask,   # opposite side to close
                order_type         = self.client.ORDER_TYPE_STOP_LOSS_LIMIT,
                time_in_force      = self.client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                reduce_only        = True,
                order_expiry       = self.client.DEFAULT_28_DAY_ORDER_EXPIRY,
                trigger_price      = sl_trigger,
            )
            if err:
                log.error(f"SL order error: {err}")

            # 3. Take-profit (native TP order, reduce-only)
            _, resp, err = await self.client.create_order(
                market_index       = BTC_MARKET_ID,
                client_order_index = tp_idx,
                base_amount        = qty_int,
                price              = tp_exec_price,
                is_ask             = not is_ask,
                order_type         = self.client.ORDER_TYPE_TAKE_PROFIT_LIMIT,
                time_in_force      = self.client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                reduce_only        = True,
                order_expiry       = self.client.DEFAULT_28_DAY_ORDER_EXPIRY,
                trigger_price      = tp_trigger,
            )
            if err:
                log.error(f"TP order error: {err}")

            # Store order indices for later amendment / cancellation
            self.active_orders[trade.id] = {
                'sl'  : sl_idx,
                'tp'  : tp_idx,
                'qty' : qty_int,
                'is_ask_close': not is_ask,
            }
            log.info(f"  Orders placed: entry={entry_idx} SL={sl_idx} TP={tp_idx}")

        except Exception as e:
            log.error(f"open_position exception: {e}", exc_info=True)'''
    ),
    (
        '''class PriceFeed:
    """
    Subscribes to Lighter\'s orderbook WebSocket for real-time mid-price.
    Falls back to REST poll if WS unavailable.
    """
    def __init__(self):
        self.last_price : float = 0.0
        self._running   : bool  = False

    async def start(self, client: lighter.ApiClient):
        """Start REST polling as price feed (simple, reliable)."""
        self._client  = client
        self._running = True
        asyncio.create_task(self._poll_loop())

    async def _poll_loop(self):
        order_api = lighter.OrderApi(self._client)
        while self._running:
            try:
                depth = await order_api.order_book_orders(market_id=BTC_MARKET_ID, limit=1)
                # Mid-price from best bid and ask
                if depth.bids and depth.asks:
                    best_bid = float(depth.bids[0].price)
                    best_ask = float(depth.asks[0].price)
                    self.last_price = (best_bid + best_ask) / 2
            except Exception as e:
                log.warning(f"Price feed error: {e}")
            await asyncio.sleep(2)   # poll every 2 seconds

    def stop(self):
        self._running = False''',
        '''class PriceFeed:
    """
    Subscribes to Lighter\'s orderbook for real-time mid-price.
    Falls back to REST poll if WS unavailable.
    """
    def __init__(self):
        self.last_price : float = 0.0
        self._running   : bool  = False

    async def start(self, client: lighter.ApiClient, market_id: int = MAINNET_BTC_MARKET_ID):
        """Start REST polling as price feed from Mainnet."""
        self._client    = client
        self._market_id = market_id
        self._running   = True
        asyncio.create_task(self._poll_loop())

    async def _poll_loop(self):
        order_api = lighter.OrderApi(self._client)
        while self._running:
            try:
                depth = await order_api.order_book_orders(market_id=self._market_id, limit=1)
                # Mid-price from best bid and ask
                if depth.bids and depth.asks:
                    best_bid = float(depth.bids[0].price)
                    best_ask = float(depth.asks[0].price)
                    self.last_price = (best_bid + best_ask) / 2
            except Exception as e:
                log.warning(f"Price feed error: {e}")
            await asyncio.sleep(2)   # poll every 2 seconds

    def stop(self):
        self._running = False'''
    ),
    (
        '''async def fetch_candles_lighter(client: lighter.ApiClient, limit: int = 5) -> list[Candle]:
    """Fetch recent 5m candles from Lighter historical data endpoint."""
    try:
        from lighter.api.candlestick_api import CandlestickApi
        import time
        
        api = CandlestickApi(client)
        res = await api.candles(
            market_id=BTC_MARKET_ID,
            resolution="5m",
            start_timestamp=0,
            end_timestamp=int(time.time() * 1000),
            count_back=limit
        )''',
        '''async def fetch_candles_lighter(client: lighter.ApiClient, market_id: int = MAINNET_BTC_MARKET_ID, limit: int = 5) -> list[Candle]:
    """Fetch recent 5m candles from Lighter historical data endpoint (Mainnet)."""
    try:
        from lighter.api.candlestick_api import CandlestickApi
        import time
        
        api = CandlestickApi(client)
        res = await api.candles(
            market_id=market_id,
            resolution="5m",
            start_timestamp=0,
            end_timestamp=int(time.time() * 1000),
            count_back=limit
        )'''
    ),
    (
        '''        # Lighter client (initialised in run())
        self.signer_client : Optional[lighter.SignerClient] = None
        self.api_client    : Optional[lighter.ApiClient]    = None
        self.executor      : Optional[LighterOrderExecutor] = None
        self.feed          : Optional[PriceFeed]            = None
        self.trail_monitor : Optional[TrailMonitor]         = None

        self._last_candle_ts : Optional[datetime] = None''',
        '''        # Lighter client (initialised in run())
        self.signer_client : Optional[lighter.SignerClient] = None
        self.api_client    : Optional[lighter.ApiClient]    = None
        self.market_api_client : Optional[lighter.ApiClient] = None
        self.executor      : Optional[LighterOrderExecutor] = None
        self.feed          : Optional[PriceFeed]            = None
        self.trail_monitor : Optional[TrailMonitor]         = None

        self._last_candle_ts : Optional[datetime] = None'''
    ),
    (
        '''        # ── Init Lighter clients ──
        self.signer_client = lighter.SignerClient(
            url             = BASE_URL,
            api_private_keys = {api_key_index: api_priv_key},
            account_index   = account_index,
        )
        self.api_client = lighter.ApiClient(
            lighter.Configuration(host=BASE_URL)
        )

        # ── Confirm market precision ──
        await self._confirm_market_details()

        # ── Init components ──
        self.executor     = LighterOrderExecutor(self.signer_client)
        self.feed         = PriceFeed()
        self.trail_monitor = TrailMonitor(self.engine, self.executor, self.feed)

        await self.feed.start(self.api_client)''',
        '''        # ── Init Lighter clients ──
        self.signer_client = lighter.SignerClient(
            url             = BASE_URL,
            api_private_keys = {api_key_index: api_priv_key},
            account_index   = account_index,
        )
        self.api_client = lighter.ApiClient(
            lighter.Configuration(host=BASE_URL)
        )
        self.market_api_client = lighter.ApiClient(
            lighter.Configuration(host=MAINNET_URL)
        )

        # ── Confirm market precision ──
        await self._confirm_market_details()

        # ── Init components ──
        self.executor     = LighterOrderExecutor(self.signer_client)
        self.feed         = PriceFeed()
        self.trail_monitor = TrailMonitor(self.engine, self.executor, self.feed)

        await self.feed.start(self.market_api_client, market_id=MAINNET_BTC_MARKET_ID)'''
    ),
    (
        '''    async def _process_latest_candle(self, now: datetime):
        candles = await fetch_candles_lighter(self.api_client, limit=5)
        if not candles:
            return

        # Last CLOSED candle = second-to-last in list
        if len(candles) < 2:
            return
        last_closed = candles[-2]

        if last_closed.timestamp == self._last_candle_ts:
            return   # already processed
        self._last_candle_ts = last_closed.timestamp

        try:
            import asyncio, telemetry
            asyncio.create_task(telemetry.post_telemetry_heartbeat("Lighter", last_closed.high, last_closed.low, last_closed.close))
        except Exception as e:
            pass

        sess = self.engine.current_session
        if sess is None:
            return

        self.engine.candle_idx += 1
        sess.candle_buffer.append(last_closed)

        # Range detection
        if sess.range is None and len(sess.candle_buffer) >= 2:
            found = self.engine.find_range(sess.candle_buffer[:-1], sess.start_time)
            if found:
                sess.range = found
                try:
                    from telemetry import post_telemetry_range
                    import asyncio
                    asyncio.create_task(post_telemetry_range("Lighter", sess))
                except Exception as e:
                    log.error(f"Telemetry range error: {e}")
                import asyncio
                asyncio.create_task(post_telemetry_range("Lighter", sess))
                log.info(
                    f"Range locked | upper={found.upper:.1f} "
                    f"lower={found.lower:.1f} width={found.width:.1f}pts"
                )

        # Process candle through strategy
        self.engine.process_candle(last_closed, sess)''',
        '''    async def _process_latest_candle(self, now: datetime):
        candles = await fetch_candles_lighter(self.market_api_client, market_id=MAINNET_BTC_MARKET_ID, limit=5)
        if not candles or len(candles) < 2:
            return

        last_closed = candles[-2]
        if last_closed.timestamp == self._last_candle_ts:
            return   # already processed
        self._last_candle_ts = last_closed.timestamp

        try:
            import asyncio, telemetry
            asyncio.create_task(telemetry.post_telemetry_heartbeat("Lighter", last_closed.high, last_closed.low, last_closed.close))
        except Exception as e:
            pass

        sess = self.engine.current_session
        if sess is None:
            return

        self.engine.candle_idx += 1
        sess.candle_buffer.append(last_closed)

        just_locked = False
        # Range detection
        if sess.range is None and len(sess.candle_buffer) >= 2:
            found = self.engine.find_range(sess.candle_buffer, sess.start_time)
            if found:
                sess.range = found
                just_locked = True
                try:
                    from telemetry import post_telemetry_range
                    import asyncio
                    asyncio.create_task(post_telemetry_range("Lighter", sess))
                except Exception as e:
                    log.error(f"Telemetry range error: {e}")
                log.info(
                    f"Range locked | upper={found.upper:.1f} "
                    f"lower={found.lower:.1f} width={found.width:.1f}pts"
                )

        # Process candle through strategy (skip if this candle was the one defining the range)
        if not just_locked:
            self.engine.process_candle(last_closed, sess)'''
    ),
    (
        '''    async def _confirm_market_details(self):
        """Log market precision so you can verify PRICE_DECIMALS/SIZE_DECIMALS."""
        try:
            order_api = lighter.OrderApi(self.api_client)
            details   = await order_api.order_book_details()
            # `details` has `order_book_details` for perps, or `spot_order_book_details` for spot
            book_details = getattr(details, 'order_book_details', []) or getattr(details, 'spot_order_book_details', [])
            for m in book_details:
                if getattr(m, 'market_id', -1) == BTC_MARKET_ID:
                    log.info(
                        f"BTC market confirmed: "
                        f"price_decimals={m.supported_price_decimals} "
                        f"size_decimals={m.supported_size_decimals} "
                        f"min_base={m.min_base_amount}"
                    )
        except Exception as e:
            log.warning(f"Could not confirm market details: {e}")''',
        '''    async def _confirm_market_details(self):
        """Update and log market precision for testnet execution."""
        global PRICE_DECIMALS, SIZE_DECIMALS
        try:
            order_api = lighter.OrderApi(self.api_client)
            details   = await order_api.order_book_details()
            book_details = getattr(details, 'order_book_details', []) or getattr(details, 'spot_order_book_details', [])
            for m in book_details:
                if getattr(m, 'market_id', -1) == BTC_MARKET_ID:
                    PRICE_DECIMALS = m.supported_price_decimals
                    SIZE_DECIMALS  = m.supported_size_decimals
                    log.info(
                        f"BTC testnet market confirmed: "
                        f"price_decimals={PRICE_DECIMALS} "
                        f"size_decimals={SIZE_DECIMALS} "
                        f"min_base={m.min_base_amount}"
                    )
        except Exception as e:
            log.warning(f"Could not confirm market details: {e}")'''
    ),
    (
        '''            await self.api_client.close()
            log.info("Runner stopped.")''',
        '''            await self.api_client.close()
            if self.market_api_client:
                await self.market_api_client.close()
            log.info("Runner stopped.")'''
    )
]

patch_file("/Users/anindyacr7/foxAlgo/lighter_live.py", lighter_replacements)
