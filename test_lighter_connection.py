import os
import asyncio
import lighter

async def test_lighter():
    try:
        api_key_index = int(os.environ.get("LIGHTER_API_KEY_INDEX", "0"))
        api_priv_key = os.environ.get("LIGHTER_API_PRIVATE_KEY", "")
        account_index = int(os.environ.get("LIGHTER_ACCOUNT_INDEX", "0"))

        print(f"Using Key Index: {api_key_index}, Account: {account_index}")
        
        # Test if it requires 0x prefix
        if not api_priv_key.startswith("0x"):
            print("Note: API Private Key does not start with 0x. We will test it as-is.")

        BASE_URL = "https://testnet.zklighter.elliot.ai"
        signer_client = lighter.SignerClient(
            url = BASE_URL,
            api_private_keys = {api_key_index: api_priv_key},
            account_index = account_index,
        )
        print("✅ Lighter SignerClient created successfully.")
        
        api_client = lighter.ApiClient(
            lighter.Configuration(host=BASE_URL)
        )
        order_api = lighter.OrderApi(api_client)
        # Fetch some data to test the API Client
        res = await order_api.order_book_details()
        print("✅ Lighter API Client connected successfully.")
    except Exception as e:
        print(f"❌ Lighter connection test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_lighter())
