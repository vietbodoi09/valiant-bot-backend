"""
Lighter Trader - Using official lighter-python SDK
Proper transaction signing via official SignerClient with Go binary signer
"""
import os
import sys
import json
import asyncio
import logging
import time
from typing import Optional, Dict, Literal
from decimal import Decimal

# Use official lighter-python SDK
import lighter
from lighter import SignerClient, Configuration, ApiClient, AccountApi, OrderApi, TransactionApi

logger = logging.getLogger("LighterSDK")


class LighterSDKTrader:
    """
    Lighter Full SDK Trader - Uses official lighter-python SDK
    
    Required env vars:
    - LIGHTER_ACCOUNT_INDEX: Account ID (e.g., 719083)
    - LIGHTER_API_PRIVATE_KEYS: JSON dict {"2": "private_key"}
    - LIGHTER_API_KEY_INDEX: Which key to use (e.g., 2)
    """
    
    # Market IDs (from Lighter API)
    MARKET_ETH = 0   # ETH
    MARKET_BTC = 1   # BTC
    MARKET_SOL = 3   # SOL
    
    def __init__(self):
        self.base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai")
        self.account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
        
        self.signer_client: Optional[SignerClient] = None
        self.api_client: Optional[ApiClient] = None
        self._connected = False
        self._market_info_cache: Dict = {}
        
        self._load_config()
    
    def _load_config(self):
        """Load config from env vars"""
        keys_json = os.getenv("LIGHTER_API_PRIVATE_KEYS")
        if not keys_json:
            raise ValueError("LIGHTER_API_PRIVATE_KEYS not set")
        
        parsed = json.loads(keys_json)
        self.api_private_keys = {int(k): v for k, v in parsed.items()}
        self.api_key_index = int(os.getenv("LIGHTER_API_KEY_INDEX", str(list(self.api_private_keys.keys())[0])))
        
        logger.info(f"Account index: {self.account_index}, API key index: {self.api_key_index}")
        logger.info(f"Loaded private keys for API indices: {list(self.api_private_keys.keys())}")
        
        if self.api_key_index not in self.api_private_keys:
            raise ValueError(f"API key index {self.api_key_index} not found. Available: {list(self.api_private_keys.keys())}")
        
        logger.info(f"Private key available for API key index {self.api_key_index}: Yes")
    
    async def connect(self):
        """Initialize connection using official SDK"""
        try:
            # Official API client for REST operations
            config = Configuration(host=self.base_url)
            self.api_client = ApiClient(configuration=config)
            logger.info(f"REST API client configured for {self.base_url}")
            
            # Official SignerClient for trading (uses Go binary signer)
            self.signer_client = SignerClient(
                url=self.base_url,
                account_index=self.account_index,
                api_private_keys=self.api_private_keys,
            )
            
            # Verify API key is valid
            err = self.signer_client.check_client()
            if err:
                raise Exception(f"SignerClient check failed: {err}")
            
            self._connected = True
            logger.info("Lighter SDK connected successfully!")
            
            # Log balance
            balance = await self.get_balance()
            if balance is not None:
                logger.info(f"USDC Balance: ${balance:.2f}")
            else:
                logger.warning("Could not get USDC balance")
            
        except Exception as e:
            logger.error(f"Lighter connection failed: {e}")
            raise
    
    # === Market Info ===
    
    async def _get_market_info(self, market_id: int) -> Dict:
        """Get market info (size_decimals, price_decimals) from orderBookDetails"""
        if market_id in self._market_info_cache:
            return self._market_info_cache[market_id]
        
        try:
            order_api = OrderApi(self.api_client)
            result = await order_api.order_book_details(market_id=market_id)
            
            details = getattr(result, 'order_book_details', [])
            if details and len(details) > 0:
                d = details[0]
                info = {
                    "size_decimals": int(getattr(d, 'size_decimals', getattr(d, 'supported_size_decimals', 5))),
                    "price_decimals": int(getattr(d, 'price_decimals', getattr(d, 'supported_price_decimals', 1))),
                    "min_base_amount": float(getattr(d, 'min_base_amount', 0)),
                }
                self._market_info_cache[market_id] = info
                logger.info(f"Market {market_id} info: size_decimals={info['size_decimals']}, price_decimals={info['price_decimals']}")
                return info
        except Exception as e:
            logger.debug(f"Failed to get market info: {e}")
        
        # Fallback defaults
        defaults = {
            1: {"size_decimals": 5, "price_decimals": 1, "min_base_amount": 0.0002},   # BTC
            0: {"size_decimals": 4, "price_decimals": 2, "min_base_amount": 0.001},     # ETH  
            3: {"size_decimals": 3, "price_decimals": 3, "min_base_amount": 0.01},      # SOL
        }
        return defaults.get(market_id, {"size_decimals": 5, "price_decimals": 1, "min_base_amount": 0.0002})
    
    async def _get_size_decimals(self, market_id: int) -> int:
        info = await self._get_market_info(market_id)
        return info["size_decimals"]
    
    async def _get_price_decimals(self, market_id: int) -> int:
        info = await self._get_market_info(market_id)
        return info["price_decimals"]

    # === Data Queries ===

    async def get_funding_rate(self, market_id: int = MARKET_BTC) -> float:
        """Get funding rate for a market"""
        try:
            funding_api = lighter.CandlestickApi(self.api_client)
            result = await funding_api.fundings()
            
            rates = result if isinstance(result, list) else getattr(result, 'data', [])
            if not rates and hasattr(result, 'funding_rates'):
                rates = result.funding_rates
                
            for r in rates:
                mid = getattr(r, 'market_id', getattr(r, 'market_index', None))
                if mid == market_id:
                    return float(getattr(r, 'rate', getattr(r, 'funding_rate', 0)))
            return 0.0
        except Exception as e:
            logger.debug(f"Failed to get funding rate: {e}")
            return 0.0
    
    async def get_balance(self, token: str = "USDC") -> float:
        """Get USDC balance"""
        try:
            account_api = AccountApi(self.api_client)
            result = await account_api.account(by="index", value=str(self.account_index))
            
            if result is None:
                return 0.0
            
            # Official SDK returns DetailedAccounts with .accounts list
            accounts = getattr(result, 'accounts', [])
            if accounts and len(accounts) > 0:
                acc = accounts[0]
                
                collateral = getattr(acc, 'collateral', None)
                if collateral:
                    return float(collateral)
                
                available = getattr(acc, 'available_balance', None)
                if available:
                    return float(available)
                    
            return 0.0
        except Exception as e:
            logger.warning(f"Get balance error: {e}")
            return 0.0
    
    async def get_position(self, market_id: int = MARKET_BTC) -> Optional[Dict]:
        """Get position for a market"""
        try:
            account_api = AccountApi(self.api_client)
            result = await account_api.account(by="index", value=str(self.account_index))
            
            accounts = getattr(result, 'accounts', [])
            if accounts:
                acc = accounts[0]
                positions = getattr(acc, 'positions', [])
                
                for p in positions:
                    if p.market_id == market_id:
                        position_size = float(p.position)
                        sign = int(p.sign)
                        
                        return {
                            "market_id": market_id,
                            "size": position_size,
                            "side": "long" if sign > 0 else "short",
                            "entry_price": float(p.avg_entry_price),
                            "unrealized_pnl": float(p.unrealized_pnl),
                            "position_value": float(p.position_value),
                            "liquidation_price": float(p.liquidation_price) if p.liquidation_price else 0,
                        }
            return None
        except Exception as e:
            logger.debug(f"Failed to get position: {e}")
            return None
    
    async def get_mid_price(self, market_id: int = MARKET_BTC) -> Optional[float]:
        """Get mid price from order book details"""
        try:
            order_api = OrderApi(self.api_client)
            result = await order_api.order_book_details(market_id=market_id)
            
            details = getattr(result, 'order_book_details', [])
            if details and len(details) > 0:
                last_price = getattr(details[0], 'last_trade_price', None)
                if last_price:
                    return float(last_price)
            return None
        except Exception as e:
            logger.debug(f"Failed to get price: {e}")
            return None
    
    # === Trading ===
    
    async def market_order(self, side: Literal["long", "short"], size_usd: float,
                          market_id: int = MARKET_BTC, price: float = None) -> Dict:
        """Place a market order using official SDK"""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            if price is None:
                price = await self.get_mid_price(market_id)
            if not price:
                return {"status": "error", "error": "Cannot get price"}
            
            size_decimals = await self._get_size_decimals(market_id)
            price_decimals = await self._get_price_decimals(market_id)
            
            # Convert USD -> base amount
            size_btc = size_usd / price
            base_amount = round(size_btc * (10 ** size_decimals))
            if base_amount < 1:
                base_amount = 1
            
            expected_btc = base_amount / (10 ** size_decimals)
            expected_usd = expected_btc * price
            
            logger.info(f"  USD input: ${size_usd:.2f}")
            logger.info(f"  Size BTC: {size_btc:.8f}")
            logger.info(f"  Base amount: {base_amount}")
            logger.info(f"  Expected BTC: {expected_btc:.8f}")
            logger.info(f"  Expected USD: ${expected_usd:.2f}")
            
            is_ask = side.lower() == "short"
            client_order_index = int(time.time() * 1000) % 1000000000
            
            # Slippage 1%
            slippage = 0.01
            if is_ask:
                slippage_price = price * (1 - slippage)
            else:
                slippage_price = price * (1 + slippage)
            
            avg_exec_price = int(slippage_price * (10 ** price_decimals))
            
            logger.info(f"Placing {side.upper()} market order: ${size_usd:.2f} ({base_amount} units) @ ~${price:.0f}")
            
            # Use official SDK create_market_order
            tx, tx_hash, err = await self.signer_client.create_market_order(
                market_index=market_id,
                client_order_index=client_order_index,
                base_amount=base_amount,
                avg_execution_price=avg_exec_price,
                is_ask=is_ask,
            )
            
            if err:
                logger.error(f"Order failed: {err}")
                return {"status": "error", "error": str(err)}
            
            tx_hash_str = str(tx_hash) if tx_hash else ""
            logger.info(f"Order placed: tx_hash={tx_hash_str[:64]}")
            
            return {
                "status": "filled",
                "tx_hash": tx_hash_str,
                "client_order_index": client_order_index,
            }
            
        except Exception as e:
            logger.error(f"Market order failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def close_position(self, market_id: int = MARKET_BTC) -> Dict:
        """Close position"""
        pos = await self.get_position(market_id)
        if not pos or pos["size"] == 0:
            return {"status": "no_position"}
        return await self.close_position_direct(pos, market_id)
    
    async def close_position_direct(self, pos: Dict, market_id: int = MARKET_BTC, price: float = None) -> Dict:
        """Close position with existing data"""
        if not pos or pos["size"] == 0:
            return {"status": "no_position"}
        
        close_side = "short" if pos["side"] == "long" else "long"
        mark_price = price or pos.get("entry_price", 70000)
        size_usd = pos["size"] * mark_price
        
        logger.info(f"  Closing {pos['size']:.8f} BTC @ ~${mark_price:,.0f} = ${size_usd:.2f}")
        return await self.market_order(close_side, size_usd, market_id, price=mark_price)
    
    async def close(self):
        """Close connections"""
        if self.api_client:
            await self.api_client.close()
        if self.signer_client:
            await self.signer_client.close()
        self._connected = False


class LighterSDKTraderWrapper:
    """Wrapper for bot2 - keeps interface compatible"""
    
    def __init__(self):
        self.trader = None
        self.connected = False
        self.account = None
        
        try:
            self.trader = LighterSDKTrader()
            self.account = f"Account {self.trader.account_index}"
        except Exception as e:
            logger.warning(f"Lighter SDK not available: {e}")
    
    async def connect(self):
        if self.trader:
            await self.trader.connect()
            self.connected = True
    
    def get_funding_rate(self) -> float:
        if not self.connected:
            return 0.0
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.get_funding_rate()
            )
        except:
            return 0.0
    
    def market_order(self, side: str, size_usd: float) -> Dict:
        if not self.connected:
            return {"status": "error", "error": "Not connected"}
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.market_order(side, size_usd)
            )
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def close_position(self) -> Dict:
        if not self.connected:
            return {"status": "error", "error": "Not connected"}
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.close_position()
            )
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_position(self) -> Optional[Dict]:
        if not self.connected:
            return None
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.get_position()
            )
        except:
            return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        trader = LighterSDKTrader()
        await trader.connect()
        
        print(f"Balance: ${await trader.get_balance():.2f}")
        print(f"Position: {await trader.get_position()}")
        print(f"Funding Rate: {await trader.get_funding_rate()}")
        print(f"Price: {await trader.get_mid_price()}")
        
        await trader.close()
    
    asyncio.run(test())