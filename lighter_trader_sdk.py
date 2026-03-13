"""
Lighter Trader - Full SDK Implementation (Windows Compatible)
Sử dụng lighter-python SDK đã patch để chạy trên Windows
"""
import os
import sys
import json
import asyncio
import logging
from typing import Optional, Dict, Literal
from decimal import Decimal
from pathlib import Path

# Add lighter-python to path
LIGHTER_PATH = Path(__file__).parent / "lighter-python"
if str(LIGHTER_PATH) not in sys.path:
    sys.path.insert(0, str(LIGHTER_PATH))

import lighter
from lighter.signer_client import SignerClient

logger = logging.getLogger("LighterSDK")


class LighterSDKTrader:
    """
    Lighter Full SDK Trader - Đã fix để chạy trên Windows
    
    Required:
    - api_key_config.json: File config từ lighter setup
    Hoặc env vars:
    - LIGHTER_BASE_URL
    - LIGHTER_ACCOUNT_INDEX  
    - LIGHTER_API_PRIVATE_KEYS (JSON dict: {"3": "private_key"})
    """
    
    # Market IDs từ Lighter (lấy từ API)
    MARKET_ETH = 2   # ETH
    MARKET_BTC = 1   # BTC
    MARKET_SOL = 3   # SOL
    
    def __init__(self):
        self.config_file = os.getenv("LIGHTER_CONFIG", "./api_key_config.json")
        self.base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai")
        self.account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
        
        self.signer_client: Optional[SignerClient] = None
        self.api_client: Optional[lighter.ApiClient] = None
        self._connected = False
        self._market_info_cache: Dict = {}
        
        self._load_config()
    
    def _load_config(self):
        """Load config từ file hoặc env"""
        if os.path.exists(self.config_file):
            # Load từ file
            with open(self.config_file) as f:
                cfg = json.load(f)
            self.base_url = cfg["baseUrl"]
            self.account_index = cfg["accountIndex"]
            # Convert string keys to int
            self.api_private_keys = {int(k): v for k, v in cfg["privateKeys"].items()}
        else:
            # Load từ env
            keys_json = os.getenv("LIGHTER_API_PRIVATE_KEYS")
            account_index_str = os.getenv("LIGHTER_ACCOUNT_INDEX", "0")
            self.account_index = int(account_index_str)
            
            if keys_json:
                try:
                    parsed_keys = json.loads(keys_json)
                    self.api_private_keys = {int(k): v for k, v in parsed_keys.items()}
                    logger.info(f"Loaded private keys for accounts: {list(self.api_private_keys.keys())}")
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid LIGHTER_API_PRIVATE_KEYS format (must be valid JSON): {e}")
            else:
                raise ValueError("No Lighter config found. Set LIGHTER_CONFIG or LIGHTER_API_PRIVATE_KEYS")
        
        # Validate account index exists
        if self.account_index not in self.api_private_keys:
            available = list(self.api_private_keys.keys())
            raise ValueError(
                f"Account {self.account_index} not found in private keys! "
                f"Available accounts: {available}. "
                f"Check LIGHTER_ACCOUNT_INDEX matches the keys in LIGHTER_API_PRIVATE_KEYS"
            )
        
        logger.info(f"Lighter config: {self.base_url}, Account {self.account_index}")
        logger.info(f"Private key available for account {self.account_index}: {'Yes' if self.account_index in self.api_private_keys else 'No'}")
    
    async def connect(self):
        """Khởi tạo kết nối"""
        try:
            # REST API client cho read operations
            api_key = self.api_private_keys.get(self.account_index, "")
            
            # Try with query parameter auth (some APIs use this)
            config = lighter.Configuration(host=self.base_url)
            if api_key:
                # Add API key as default query param
                config.api_key['api_key'] = api_key
                config.api_key_prefix['api_key'] = 'Bearer'
                logger.info(f"API Key configured for account {self.account_index}")
            
            self.api_client = lighter.ApiClient(configuration=config)
            
            # Signer client cho trading (đã fix để chạy trên Windows)
            self.signer_client = SignerClient(
                url=self.base_url,
                account_index=self.account_index,
                api_private_keys=self.api_private_keys,
            )
            
            # Check client
            err = self.signer_client.check_client()
            if err:
                raise Exception(f"SignerClient check failed: {err}")
            
            self._connected = True
            logger.info("Lighter SDK connected successfully!")
            
            # Log balance
            balance = await self.get_balance()
            logger.info(f"USDC Balance: ${balance:.2f}")
            
        except Exception as e:
            logger.error(f"Lighter connection failed: {e}")
            raise
    
    # Market info helpers
    
    async def _get_market_info(self, market_id: int) -> Dict:
        """Lấy market info (size_decimals, price_decimals) từ orderBookDetails API"""
        if market_id in self._market_info_cache:
            return self._market_info_cache[market_id]
        
        try:
            order_api = lighter.OrderApi(self.api_client)
            result = await order_api.order_book_details(market_id=market_id)
            
            details = getattr(result, 'order_book_details', [])
            if details and len(details) > 0:
                d = details[0]
                info = {
                    "size_decimals": int(getattr(d, 'size_decimals', 5)),
                    "price_decimals": int(getattr(d, 'price_decimals', 1)),
                    "min_base_amount": float(getattr(d, 'min_base_amount', 0)),
                }
                self._market_info_cache[market_id] = info
                logger.info(f"Market {market_id} info: size_decimals={info['size_decimals']}, price_decimals={info['price_decimals']}")
                return info
        except lighter.exceptions.ApiException as e:
            if e.status == 403:
                logger.error(f"Market info API 403: Cannot access market {market_id}. API authentication failed.")
            logger.debug(f"Failed to get market info: {e.status} - {e.reason}")
        
        # Fallback defaults từ API data đã biết
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

    async def get_funding_rate(self, market_id: int = MARKET_BTC) -> float:
        """Lấy funding rate"""
        try:
            funding_api = lighter.FundingApi(self.api_client)
            result = await funding_api.funding_rates()
            
            # API trả về list trực tiếp hoặc có attribute 'data'
            rates = result if isinstance(result, list) else getattr(result, 'data', [])
            if not rates and hasattr(result, 'rates'):
                rates = result.rates
            if not rates and hasattr(result, 'funding_rates'):
                rates = result.funding_rates
                
            for r in rates:
                market_id_attr = getattr(r, 'market_id', getattr(r, 'market_index', None))
                if market_id_attr == market_id:
                    return float(getattr(r, 'rate', getattr(r, 'funding_rate', 0)))
            return 0.0
        except lighter.exceptions.ApiException as e:
            if e.status == 403:
                logger.error(f"Funding API 403: {e.body}")
            else:
                logger.warning(f"Funding API error {e.status}: {e.reason}")
            return 0.0
        except Exception as e:
            logger.debug(f"Failed to get funding rate: {e}")
            return 0.0
    
    async def get_balance(self, token: str = "USDC") -> float:
        """Lấy số dư"""
        try:
            # Try with raw requests first to test auth
            import aiohttp
            api_key = self.api_private_keys.get(self.account_index, "")
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                url = f"{self.base_url}/v1/account?by=index&value={self.account_index}"
                
                logger.debug(f"Testing balance API with auth header...")
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 403:
                        text = await resp.text()
                        logger.error(f"Raw request 403: {text}")
                    elif resp.status == 200:
                        logger.info(f"Raw request success! Balance API accessible")
            
            # Fallback to SDK
            account_api = lighter.AccountApi(self.api_client)
            result = await account_api.account(by="index", value=str(self.account_index))
            
            # API trả về DetailedAccounts có field 'accounts' là list
            accounts = getattr(result, 'accounts', [])
            if accounts and len(accounts) > 0:
                acc = accounts[0]
                # Thử lấy balance từ các field khác nhau
                available = getattr(acc, 'available_balance', None)
                if available:
                    return float(available)
                
                collateral = getattr(acc, 'collateral', None)
                if collateral:
                    return float(collateral)
                    
                # Hoặc từ assets list
                assets = getattr(acc, 'assets', [])
                for asset in assets:
                    if getattr(asset, 'token', '') == token:
                        return float(getattr(asset, 'available', 0))
                    
            return 0.0
        except lighter.exceptions.ApiException as e:
            if e.status == 403:
                logger.error(f"Account API 403: Cannot access account {self.account_index}")
                logger.error(f"Response body: {e.body}")
                logger.error("Possible causes: Account not registered, key expired, or insufficient permissions")
            else:
                logger.warning(f"Account API error {e.status}: {e.reason}")
            return 0.0
        except Exception as e:
            logger.debug(f"Failed to get balance: {e}")
            return 0.0
    
    async def get_position(self, market_id: int = MARKET_BTC) -> Optional[Dict]:
        """Lấy vị thế từ Lighter"""
        try:
            account_api = lighter.AccountApi(self.api_client)
            result = await account_api.account(by="index", value=str(self.account_index))
            
            # Lấy positions từ accounts list
            accounts = getattr(result, 'accounts', [])
            if accounts:
                acc = accounts[0]
                positions = getattr(acc, 'positions', [])
                
                for p in positions:
                    if p.market_id == market_id:
                        # Lighter dùng 'position' (string) và 'sign' (1/-1)
                        position_size = float(p.position)  # Size BTC
                        sign = int(p.sign)  # 1 = long, -1 = short
                        
                        actual_size = position_size * sign
                        
                        return {
                            "market_id": market_id,
                            "size": position_size,  # Absolute size
                            "side": "long" if sign > 0 else "short",
                            "entry_price": float(p.avg_entry_price),
                            "unrealized_pnl": float(p.unrealized_pnl),
                            "position_value": float(p.position_value),
                            "liquidation_price": float(p.liquidation_price) if p.liquidation_price else 0,
                        }
            return None
        except lighter.exceptions.ApiException as e:
            if e.status == 403:
                logger.error(f"Position API 403: Cannot access account {self.account_index}")
            return None
        except Exception as e:
            logger.debug(f"Failed to get position: {e}")
            return None
    
    async def get_mid_price(self, market_id: int = MARKET_BTC) -> Optional[float]:
        """Lấy giá từ order book details (dùng last_trade_price)"""
        try:
            order_api = lighter.OrderApi(self.api_client)
            result = await order_api.order_book_details(market_id=market_id)
            
            # API trả về OrderBookDetails có field 'order_book_details' là list
            details = getattr(result, 'order_book_details', [])
            if details and len(details) > 0:
                # Dùng last_trade_price
                last_price = getattr(details[0], 'last_trade_price', None)
                if last_price:
                    return float(last_price)
                    
            return None
        except lighter.exceptions.ApiException as e:
            if e.status == 403:
                logger.error(f"Price API 403: {e.body}")
            return None
        except Exception as e:
            logger.debug(f"Failed to get price: {e}")
            return None
    
    async def market_order(self, side: Literal["long", "short"], size_usd: float,
                          market_id: int = MARKET_BTC, price: float = None) -> Dict:
        """
        Đặt lệnh market
        
        Args:
            side: "long" hoặc "short"
            size_usd: Size USD
            market_id: Mặc định BTC = 1
            price: Giá để tính size (nếu None sẽ lấy từ order book)
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            # Lấy giá để tính base_amount (nếu chưa có)
            if price is None:
                price = await self.get_mid_price(market_id)
            if not price:
                return {"status": "error", "error": "Cannot get price"}
            
            # Convert USD -> base amount
            # Lighter dùng base_amount = integer, 1 unit = 10^(-size_decimals) BTC
            # BTC market: size_decimals=5, nên 1 base_amount = 0.00001 BTC
            # ETH market: size_decimals=4, nên 1 base_amount = 0.0001 ETH
            # Docs example: base_amount=100 = 0.01 ETH (size_decimals=4)
            
            # Lấy size_decimals cho market này
            size_decimals = await self._get_size_decimals(market_id)
            
            # Tính BTC size từ USD
            size_btc = size_usd / price
            
            # Convert sang base_amount: size_btc / (10^(-size_decimals))
            # = size_btc * 10^size_decimals
            base_amount = int(size_btc * (10 ** size_decimals))
            
            if base_amount < 1:
                base_amount = 1
            
            expected_btc = base_amount / (10 ** size_decimals)
            expected_usd = expected_btc * price
            
            logger.info(f"  USD input: ${size_usd:.2f}")
            logger.info(f"  Size BTC: {size_btc:.8f}")
            logger.info(f"  Size decimals: {size_decimals}")
            logger.info(f"  Base amount: {base_amount}")
            logger.info(f"  Expected BTC: {expected_btc:.8f}")
            logger.info(f"  Expected USD: ${expected_usd:.2f}")
            
            # Lighter dùng is_ask=True để SELL (short), is_ask=False để BUY (long)
            is_ask = side.lower() == "short"
            
            # Client order index (unique)
            import time
            client_order_index = int(time.time() * 1000) % 1000000000
            
            # Price format: int(price * 10^price_decimals)
            # BTC: price_decimals=1, nên $71000.0 -> 710000
            # ETH: price_decimals=2, nên $3100.00 -> 310000
            price_decimals = await self._get_price_decimals(market_id)
            
            # Slippage 1%: buy cao hơn, sell thấp hơn
            slippage = 0.01
            if is_ask:  # Selling/short → accept lower price
                slippage_price = price * (1 - slippage)
            else:  # Buying/long → accept higher price
                slippage_price = price * (1 + slippage)
            
            avg_exec_price = int(slippage_price * (10 ** price_decimals))
            
            logger.info(f"Placing {side.upper()} market order: ${size_usd:.2f} ({base_amount} units) @ ~${price:.0f}")
            logger.info(f"  avg_execution_price: {avg_exec_price} (price_decimals={price_decimals})")
            
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
            
            # Parse response
            tx_hash_str = str(tx_hash) if tx_hash else ""
            
            # "didn't use volume quota" = lệnh THÀNH CÔNG, dùng free slot (1/15s)
            # "volume quota remaining" = lệnh THÀNH CÔNG, trừ quota
            # Chỉ reject khi có lỗi thật sự
            
            # Check for REAL rejection patterns (not informational messages)
            rejected = False
            reject_reason = ""
            
            real_error_patterns = [
                "insufficient",
                "rejected",
                "invalid",
                "failed",
                "error",
                "not enough",
                "exceed",
            ]
            
            # Chỉ check error nếu KHÔNG có tx_hash hợp lệ
            # tx_hash hợp lệ = hex string dài (không chứa "code=" ở đầu)
            has_valid_tx = (tx_hash_str and 
                          len(tx_hash_str) > 20 and 
                          not tx_hash_str.startswith("code="))
            
            if not has_valid_tx:
                # Không có tx_hash → check lỗi
                for pattern in real_error_patterns:
                    if pattern in tx_hash_str.lower():
                        rejected = True
                        reject_reason = pattern
                        break
            
            if rejected:
                logger.error(f"Order REJECTED by Lighter: {reject_reason}")
                logger.error(f"  Full response: tx={tx}, tx_hash={tx_hash_str[:200]}")
                return {"status": "error", "error": f"Order rejected: {reject_reason}"}
            
            # Log quota info nếu có
            if "didn't use volume quota" in tx_hash_str:
                logger.info(f"Order sent (free slot, no quota used)")
            elif "volume quota remaining" in tx_hash_str.lower():
                logger.info(f"Order sent (quota used)")
            
            # Extract real tx_hash from response string
            # Format: code=200 message='...' tx_hash='abc123...' predicted_...
            real_hash = tx_hash_str
            if "tx_hash='" in tx_hash_str:
                # Tìm tx_hash thứ 2 (cái đầu là field name của object)
                parts = tx_hash_str.split("tx_hash='")
                if len(parts) >= 2:
                    # Lấy hash từ phần cuối
                    for part in parts[1:]:
                        h = part.split("'")[0]
                        if len(h) > 20:  # Hash hợp lệ
                            real_hash = h
                            break
            
            logger.info(f"Order placed: tx_hash={real_hash[:64]}")
            return {
                "status": "filled",
                "tx_hash": real_hash,
                "client_order_index": client_order_index,
            }
            
        except Exception as e:
            logger.error(f"Market order failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def close_position(self, market_id: int = MARKET_BTC) -> Dict:
        """Đóng position với đúng size hiện tại (2 API calls: get_position + market_order)"""
        pos = await self.get_position(market_id)
        if not pos or pos["size"] == 0:
            return {"status": "no_position"}
        
        return await self.close_position_direct(pos, market_id)
    
    async def close_position_direct(self, pos: Dict, market_id: int = MARKET_BTC, price: float = None) -> Dict:
        """Đóng position với data đã có sẵn (1 API call only - tránh rate limit)
        
        Args:
            pos: Position dict từ get_position() đã gọi trước đó
            market_id: Market ID
            price: Giá hiện tại (nếu None sẽ dùng entry_price)
        """
        if not pos or pos["size"] == 0:
            return {"status": "no_position"}
        
        close_side = "short" if pos["side"] == "long" else "long"
        
        # Dùng price truyền vào hoặc entry_price (không gọi API thêm)
        mark_price = price or pos.get("entry_price", 70000)
        
        size_usd = pos["size"] * mark_price
        
        logger.info(f"  Closing {pos['size']:.8f} BTC @ ~${mark_price:,.0f} = ${size_usd:.2f}")
        
        return await self.market_order(close_side, size_usd, market_id, price=mark_price)
    
    async def close(self):
        """Đóng kết nối"""
        if self.api_client:
            await self.api_client.close()
        if self.signer_client:
            await self.signer_client.close()
        self._connected = False


class LighterSDKTraderWrapper:
    """Wrapper cho bot2 - giữ interface tương thích"""
    
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
        """Khởi tạo kết nối async"""
        if self.trader:
            await self.trader.connect()
            self.connected = True
    
    def get_funding_rate(self) -> float:
        """Sync wrapper cho funding rate"""
        if not self.connected:
            return 0.0
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.get_funding_rate()
            )
        except:
            return 0.0
    
    def market_order(self, side: str, size_usd: float) -> Dict:
        """Sync wrapper cho market order"""
        if not self.connected:
            return {"status": "error", "error": "Not connected"}
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.market_order(side, size_usd)
            )
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def close_position(self) -> Dict:
        """Sync wrapper cho close"""
        if not self.connected:
            return {"status": "error", "error": "Not connected"}
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.close_position()
            )
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_position(self) -> Optional[Dict]:
        """Sync wrapper cho position"""
        if not self.connected:
            return None
        try:
            return asyncio.get_event_loop().run_until_complete(
                self.trader.get_position()
            )
        except:
            return None


# Test
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