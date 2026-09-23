import ccxt
import os
import sys

def test_binance():
    api_key = os.environ.get("BINANCE_API_KEY")
    secret = os.environ.get("BINANCE_API_SECRET")
    
    if not api_key or not secret:
        print("Please set BINANCE_API_KEY and BINANCE_API_SECRET in the environment.")
        sys.exit(1)

    print("Connecting to Binance Futures Testnet...")
    client = ccxt.binance({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    client.enable_demo_trading(True)
    
    try:
        balance = client.fetch_balance()
        usdt_balance = balance.get('USDT', {}).get('free', 0)
        print(f"✅ Authenticated successfully! USDT Balance: {usdt_balance}")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)

    symbol = "BTC/USDT:USDT"
    try:
        candles = client.fetch_ohlcv(symbol, '5m', limit=5)
        print(f"✅ Fetched {len(candles)} 5m candles for {symbol} successfully!")
    except Exception as e:
        print(f"❌ Failed to fetch candles for {symbol}: {e}")
        symbol = "BTC/USDT"
        print(f"Trying {symbol}...")
        try:
            candles = client.fetch_ohlcv(symbol, '5m', limit=5)
            print(f"✅ Fetched {len(candles)} 5m candles for {symbol} successfully!")
        except Exception as e:
            print(f"❌ Failed to fetch candles for {symbol}: {e}")
            sys.exit(1)

    try:
        print("\nPlacing a test limit order (far from market)...")
        ticker = client.fetch_ticker(symbol)
        last_price = ticker['last']
        test_price = round(last_price * 0.8, 1) # 20% below market
        
        order = client.create_order(symbol, 'limit', 'buy', 0.001, test_price)
        print(f"✅ Order placed successfully! Order ID: {order['id']}")
        
        print("Canceling the test order...")
        client.cancel_order(order['id'], symbol)
        print("✅ Order canceled successfully!")
    except Exception as e:
        print(f"❌ Order test failed: {e}")

if __name__ == "__main__":
    test_binance()
