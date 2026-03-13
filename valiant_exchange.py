"""
Valiant Hyperliquid Exchange Integration
Sử dụng Agent Wallet để trade (an toàn hơn, không thể withdraw)
"""
import os
import logging
import time
import requests
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import pandas as pd
import eth_account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

logger = logging.getLogger("ValiantExchange")


class ValiantHyperliquidExchange:
    """
    Exchange wrapper sử dụng Valiant Agent Wallet
    
    Agent wallet CHỈ có quyền:
    - Đặt/hủy lệnh
    - Mở/đóng vị thế
    - Set leverage
    
    KHÔNG có quyền:
    - Deposit/Withdraw
    - Transfer
    """
    
    def __init__(self, 
                 agent_private_key: str = None,
                 master_address: str = None,
                 testnet: bool = False):
        """
        Khởi tạo Valiant exchange
        
        Args:
            agent_private_key: Private key của agent wallet
            master_address: Địa chỉ master wallet
            testnet: Dùng testnet hay mainnet
        """
        # Load từ env nếu không được truyền vào
        self.agent_private_key = agent_private_key or os.getenv("VALIANT_AGENT_KEY")
        self.master_address = master_address or os.getenv("VALIANT_MASTER_ADDRESS")
        
        if not self.agent_private_key or not self.master_address:
            raise ValueError(
                "Thiếu agent_private_key hoặc master_address. "
                "Set env VALIANT_AGENT_KEY và VALIANT_MASTER_ADDRESS"
            )
        
        # Khởi tạo wallet từ agent key
        self.wallet = eth_account.Account.from_key(self.agent_private_key)
        
        # Chọn API URL
        api_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        
        # Khởi tạo info và exchange
        self.info = Info(api_url)
        self.exchange = Exchange(
            self.wallet,
            api_url,
            account_address=self.master_address
        )
        
        # Store master address for internal use
        self.master_address = self.master_address
        
        # Store API URL for direct queries
        self.api_url = api_url
        
        logger.info(f"Valiant Exchange initialized")
        logger.info(f"  Master: {self.master_address}")
        logger.info(f"  Agent:  {self.wallet.address}")
        logger.info(f"  Mode:   {'TESTNET' if testnet else 'MAINNET'}")
        
        self.testnet = testnet
    
    def get_balance(self) -> float:
        """Lấy số dư tài khoản (hỗ trợ Unified Account)"""
        try:
            # 1. Thử lấy từ Perp account trước
            state = self.info.user_state(self.master_address)
            margin = state.get("marginSummary", {})
            perp_balance = float(margin.get("accountValue", 0))
            
            # 2. Nếu Perp = 0, thử lấy từ Spot (Unified Account)
            if perp_balance < 0.01:
                try:
                    spot_state = self.info.spot_user_state(self.master_address)
                    spot_balances = spot_state.get("balances", [])
                    for bal in spot_balances:
                        if bal.get("coin") == "USDC":
                            spot_usdc = float(bal.get("total", 0))
                            if spot_usdc > 0:
                                logger.info(f"Unified Account: Using Spot USDC ${spot_usdc:.2f}")
                                return spot_usdc
                except Exception as spot_err:
                    logger.debug(f"Không lấy được Spot balance: {spot_err}")
            
            return perp_balance
        except Exception as e:
            logger.error(f"Lỗi lấy balance: {e}")
            return 0.0
    
    def get_positions(self) -> List[Dict]:
        """Lấy danh sách vị thế đang mở"""
        try:
            state = self.info.user_state(self.master_address)
            positions = state.get("assetPositions", [])
            
            result = []
            for pos in positions:
                p = pos.get("position", {})
                size = float(p.get("szi", 0))
                if size == 0:
                    continue
                    
                result.append({
                    "symbol": p.get("coin", ""),
                    "size": size,
                    "entry_price": float(p.get("entryPx", 0)),
                    "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                    "liquidation_price": p.get("liquidationPx"),
                    "leverage": p.get("leverage", {}).get("value", 1),
                    "side": "LONG" if size > 0 else "SHORT"
                })
            
            return result
        except Exception as e:
            logger.error(f"Lỗi lấy positions: {e}")
            return []
    
    def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """Lấy danh sách lệnh đang chờ, filter theo symbol nếu có"""
        try:
            orders = self.info.open_orders(self.master_address)
            result = []
            for o in orders:
                # Filter by symbol if provided
                if symbol and o.get("coin") != symbol:
                    continue
                result.append({
                    "symbol": o.get("coin", ""),
                    "side": "BUY" if o.get("side") == "B" else "SELL",
                    "size": float(o.get("sz", 0)),
                    "price": float(o.get("limitPx", 0)),
                    "order_id": o.get("oid", 0)
                })
            return result
        except Exception as e:
            logger.error(f"Lỗi lấy open orders: {e}")
            return []
    
    def get_mid_price(self, symbol: str) -> Optional[float]:
        """Lấy giá mid hiện tại"""
        try:
            mids = self.info.all_mids()
            price = mids.get(symbol)
            return float(price) if price else None
        except Exception as e:
            logger.error(f"Lỗi lấy giá {symbol}: {e}")
            return None
    
    def get_candles(self, symbol: str, interval: str = "15m", 
                    limit: int = 100) -> Optional[List[Dict]]:
        """Lấy dữ liệu nến từ Hyperliquid API"""
        try:
            # Map interval sang định dạng Hyperliquid
            interval_map = {
                "1m": "1m", "5m": "5m", "15m": "15m",
                "1h": "1h", "4h": "4h", "1d": "1d"
            }
            hl_interval = interval_map.get(interval, "15m")
            
            # Tính startTime (milliseconds)
            import time
            end_time = int(time.time() * 1000)
            
            # Estimate start time dựa trên interval và limit
            interval_ms = {
                "1m": 60 * 1000, "5m": 5 * 60 * 1000, "15m": 15 * 60 * 1000,
                "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000
            }
            start_time = end_time - (limit * interval_ms.get(hl_interval, 15 * 60 * 1000))
            
            # Thử gọi API candles_snapshot
            try:
                candles = self.info.candles_snapshot(
                    symbol,  # coin
                    hl_interval,  # interval
                    start_time,  # startTime
                    end_time  # endTime
                )
            except TypeError:
                # Fallback: dùng query trực tiếp
                candles = self.info.query(
                    {"type": "candleSnapshot",
                     "req": {"coin": symbol, "interval": hl_interval,
                            "startTime": start_time, "endTime": end_time}}
                )
            
            if not candles:
                return None
            
            # Format lại
            result = []
            for c in candles:
                result.append({
                    "timestamp": int(c.get("t", 0)),
                    "open": float(c.get("o", 0)),
                    "high": float(c.get("h", 0)),
                    "low": float(c.get("l", 0)),
                    "close": float(c.get("c", 0)),
                    "volume": float(c.get("v", 0))
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Lỗi lấy candles {symbol}: {e}")
            return None
    
    def get_recent_trades(self, symbol: str, limit: int = 500) -> List[Dict]:
        """Lấy recent trades từ Hyperliquid API"""
        try:
            api_url = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL
            logger.info(f"{symbol}: Calling API {api_url}/info for recentTrades")
            
            resp = requests.post(
                f"{api_url}/info",
                json={"type": "recentTrades", "coin": symbol},
                timeout=10
            )
            
            logger.info(f"{symbol}: Response status={resp.status_code}")
            
            if resp.status_code != 200:
                logger.error(f"{symbol}: API error {resp.status_code}: {resp.text[:200]}")
                return []
            
            trades = resp.json()
            logger.info(f"{symbol}: Raw response type={type(trades).__name__}, len={len(trades) if trades else 0}")
            
            if not trades or not isinstance(trades, list):
                logger.info(f"{symbol}: No trades data")
                return []
            
            result = trades[-limit:] if len(trades) > limit else trades
            logger.info(f"{symbol}: Fetched {len(result)} trades")
            return result
            
        except Exception as e:
            logger.error(f"Lỗi lấy trades {symbol}: {type(e).__name__}: {e}")
            return []
    
    def set_leverage(self, symbol: str, leverage: int, 
                     is_cross: bool = True) -> Dict:
        """Set leverage cho symbol"""
        try:
            result = self.exchange.update_leverage(
                leverage, 
                symbol, 
                is_cross
            )
            # Check if leverage was actually set
            if result and result.get('status') == 'ok':
                logger.info(f"✅ Set {symbol} leverage = {leverage}x ({'cross' if is_cross else 'isolated'})")
            else:
                logger.warning(f"⚠️ Set {symbol} leverage {leverage}x returned: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ Lỗi set leverage {symbol}: {e}")
            return {"error": str(e)}
    
    def _round_size(self, symbol: str, size: float) -> float:
        """Round size to valid szDecimals for Hyperliquid."""
        # szDecimals by symbol ( Hyperliquid requirement )
        sz_decimals = {
            'BTC': 5, 'ETH': 4, 'SOL': 2, 'TAO': 3, 'SUI': 2,
            'ARB': 0, 'ZEC': 4, 'BCH': 3, 'LTC': 3, 'XRP': 1,
            'DOGE': 0, 'MATIC': 1, 'LINK': 2, 'UNI': 2, 'AAVE': 2,
        }
        decimals = sz_decimals.get(symbol, 3)  # Default 3 decimals
        return round(size, decimals)
    
    def _round_price(self, symbol: str, price: float) -> float:
        """Round price to valid tick size for Hyperliquid."""
        # Tick sizes by price level (approximate)
        # Lower cap = more precision needed
        if price >= 10000:  # BTC
            tick = 1.0
            decimals = 1
        elif price >= 1000:  # ETH
            tick = 0.1
            decimals = 2
        elif price >= 100:  # TAO, BCH
            tick = 0.01
            decimals = 3
        elif price >= 10:   # SOL, LINK
            tick = 0.001
            decimals = 4
        elif price >= 1:    # SUI
            tick = 0.0001
            decimals = 5
        elif price >= 0.1:  # ARB, low price
            tick = 0.00001
            decimals = 6
        else:  # Very low price
            tick = 0.000001
            decimals = 7
        return round(round(price / tick) * tick, decimals)
    
    def _post_info(self, payload: dict):
        """Query info endpoint directly."""
        import requests
        try:
            resp = requests.post(
                f"{self.api_url}/info",
                json=payload,
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"API query failed: {e}")
            return None
    
    def _ensure_perp_margin(self, amount_usd: float = 30.0) -> bool:
        """
        Kiểm tra margin cho Unified Account.
        Với Unified Account, Agent có thể dùng Spot USDC của Master làm margin trực tiếp.
        """
        try:
            # Check Spot USDC (có thể dùng làm margin cho Perp)
            spot = self._post_info({
                "type": "spotClearinghouseState", 
                "user": self.master_address
            })
            spot_usdc = 0.0
            if spot and 'balances' in spot:
                for b in spot['balances']:
                    if b.get('coin') == 'USDC':
                        spot_usdc = float(b.get('total', 0))
                        break
            
            # Check Perp balance
            state = self._post_info({
                "type": "clearinghouseState",
                "user": self.master_address
            })
            perp_value = float(state.get('marginSummary', {}).get('accountValue', 0)) if state else 0.0
            
            total = spot_usdc + perp_value
            
            logger.info(f"Unified Account - Spot: ${spot_usdc:.2f}, Perp: ${perp_value:.2f}, Total: ${total:.2f}")
            
            if total >= amount_usd:
                return True  # Đủ tiền
            else:
                logger.warning(f"Không đủ USDC. Total: ${total:.2f}, cần: ${amount_usd:.2f}")
                return False
                
        except Exception as e:
            logger.error(f"Lỗi kiểm tra margin: {e}")
            return False
    
    def market_order(self, symbol: str, side: str, 
                     size: float, reduce_only: bool = False) -> Dict:
        """
        Đặt lệnh market
        
        Args:
            symbol: Coin (BTC, ETH, ...)
            side: "long" hoặc "short"
            size: Kích thước position
        """
        try:
            # Đảm bảo có margin trong Perp (Unified Account)
            if not self._ensure_perp_margin(30.0):
                return {"error": "Không đủ margin trong Perp account"}
            
            is_long = side.lower() == "long"
            size = self._round_size(symbol, size)
            
            logger.info(f"DEBUG market_open: {side.upper()} {symbol} size={size} reduce_only={reduce_only}")
            
            result = self.exchange.market_open(
                name=symbol,
                is_buy=is_long,
                sz=size
            )
            
            # Parse deeply to detect errors
            has_error = False
            error_msg = ""
            if result.get("status") == "ok":
                # Check nested errors
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                for s in statuses:
                    if "error" in s:
                        has_error = True
                        error_msg = s["error"]
                        break
                
                if has_error:
                    logger.error(f"❌ Order rejected by exchange: {error_msg}")
                    return {"error": error_msg, "raw": result}
                else:
                    logger.info(f"✅ Order executed: {result}")
            else:
                logger.error(f"❌ Order failed: {result}")
            
            return result
        except Exception as e:
            logger.error(f"Lỗi market order {symbol}: {e}")
            return {"error": str(e)}
    
    def place_order(self, symbol: str, side: str = None, size: float = None, 
                    order_type: str = "market", price: float = None,
                    reduce_only: bool = False, is_buy: bool = None) -> Dict:
        """
        Universal order method for bot.py compatibility
        Supports both 'side' (long/short) and 'is_buy' (bool) parameters
        Delegates to market_order or limit_order based on order_type
        """
        try:
            # Handle is_buy parameter (from bot.py)
            if is_buy is not None:
                side = "long" if is_buy else "short"
            
            if side is None:
                return {"error": "Either 'side' or 'is_buy' must be provided"}
            
            if order_type.lower() == "market":
                return self.market_order(symbol, side, size, reduce_only=reduce_only)
            elif order_type.lower() == "limit":
                if price is None:
                    return {"error": "Limit order requires price"}
                price = self._round_price(symbol, price)
                result = self.limit_order(symbol, side, size, price)
                # Add rounded price to result for correct logging
                if result and "error" not in result:
                    result["executed_price"] = price
                return result
            else:
                return {"error": f"Unsupported order type: {order_type}"}
        except Exception as e:
            logger.error(f"Lỗi place_order {symbol}: {e}")
            return {"error": str(e)}
    
    def market_close(self, symbol: str) -> Dict:
        """Đóng toàn bộ vị thế của symbol"""
        try:
            logger.info(f"Closing position {symbol}")
            
            result = self.exchange.market_close(symbol)
            
            if result.get("status") == "ok":
                logger.info(f"✅ Position closed: {result}")
            else:
                logger.error(f"❌ Close failed: {result}")
            
            return result
        except Exception as e:
            logger.error(f"Lỗi close position {symbol}: {e}")
            return {"error": str(e)}
    
    def place_trigger_order(
        self,
        symbol: str,
        is_buy: bool,
        size: float,
        trigger_price: float,
        order_type: str = "sl",  # "sl" or "tp"
    ) -> Dict:
        """Place SL or TP trigger order on exchange (server-side)."""
        try:
            tp = self._round_price(symbol, float(trigger_price))
            sz = self._round_size(symbol, size)
            result = self.exchange.order(
                name=symbol,
                is_buy=is_buy,
                sz=sz,
                limit_px=tp,
                order_type={
                    "trigger": {
                        "isMarket": True,
                        "triggerPx": tp,
                        "tpsl": order_type,
                    }
                },
                reduce_only=True,
            )
            logger.info(f"DEBUG trigger order: symbol={symbol}, is_buy={is_buy}, sz={sz}, tp={tp}, reduce_only=True, result={result}")
            label = "SL" if order_type == "sl" else "TP"
            
            # Parse deeply to detect errors
            has_error = False
            error_msg = ""
            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                for s in statuses:
                    if "error" in s:
                        has_error = True
                        error_msg = s["error"]
                        break
                
                if has_error:
                    logger.error(f"❌ {label} rejected: {error_msg}")
                    return {"error": error_msg, "raw": result}
                else:
                    logger.info(f"✅ {label} placed @ ${tp:.2f}")
            else:
                logger.error(f"❌ {label} failed: {result}")
            
            return result
        except Exception as e:
            logger.error(f"Trigger order failed: {e}")
            return {"error": str(e)}
    
    def limit_order(self, symbol: str, side: str, 
                    size: float, price: float, 
                    tif: str = "Gtc") -> Dict:
        """
        Đặt lệnh limit
        
        Args:
            tif: 'Gtc' (Good til Cancel), 'Ioc', 'Alo'
        """
        try:
            # Đảm bảo có margin trong Perp (Unified Account)
            if not self._ensure_perp_margin(30.0):
                return {"error": "Không đủ margin trong Perp account"}
            
            is_buy = side.lower() == "buy"
            size = self._round_size(symbol, size)
            price = self._round_price(symbol, price)
            
            logger.info(f"Limit {side.upper()} {symbol} size={size} @ ${price}")
            
            result = self.exchange.order(
                name=symbol,
                is_buy=is_buy,
                sz=size,
                limit_px=price,
                order_type={"limit": {"tif": tif}}
            )
            
            if result.get("status") == "ok":
                logger.info(f"✅ Limit order placed: {result}")
            else:
                logger.error(f"❌ Limit order failed: {result}")
            
            return result
        except Exception as e:
            logger.error(f"Lỗi limit order {symbol}: {e}")
            return {"error": str(e)}
    
    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """Hủy lệnh theo ID"""
        try:
            result = self.exchange.cancel(symbol, order_id)
            logger.info(f"Cancelled order {order_id} on {symbol}")
            return result
        except Exception as e:
            logger.error(f"Lỗi cancel order: {e}")
            return {"error": str(e)}
    
    def cancel_all_orders(self) -> None:
        """Hủy tất cả lệnh đang chờ"""
        try:
            orders = self.get_open_orders()
            for o in orders:
                self.cancel_order(o["symbol"], o["order_id"])
            logger.info(f"Cancelled {len(orders)} orders")
        except Exception as e:
            logger.error(f"Lỗi cancel all: {e}")
    
    def get_account_summary(self) -> Dict:
        """Lấy tóm tắt tài khoản"""
        try:
            state = self.info.user_state(self.master_address)
            margin = state.get("marginSummary", {})
            
            return {
                "account_value": float(margin.get("accountValue", 0)),
                "total_margin_used": float(margin.get("totalMarginUsed", 0)),
                "total_ntl_pos": float(margin.get("totalNtlPos", 0)),
                "available": float(margin.get("totalRawUsd", 0)),
                "positions_count": len(state.get("assetPositions", [])),
            }
        except Exception as e:
            logger.error(f"Lỗi lấy summary: {e}")
            return {}


# ============================================================
# COMPATIBILITY LAYER - Wrap Valiant exchange cho bot hiện tại
# ============================================================

class HyperliquidConnector:
    """
    Wrapper class compatible với bot.py hiện tại
    Thay thế connector cũ bằng Valiant exchange
    """
    
    def __init__(self, network_config=None):
        """
        Khởi tạo từ network config hoặc env
        """
        # Load from env trước (để .env file work)
        from dotenv import load_dotenv
        load_dotenv()
        
        # Ưu tiên từ config, nếu không có thì lấy từ env
        if network_config:
            agent_key = getattr(network_config, 'valiant_agent_key', None) or os.getenv('VALIANT_AGENT_KEY')
            master_addr = getattr(network_config, 'valiant_master_address', None) or os.getenv('VALIANT_MASTER_ADDRESS')
            testnet = getattr(network_config, 'use_testnet', False)
        else:
            agent_key = os.getenv('VALIANT_AGENT_KEY')
            master_addr = os.getenv('VALIANT_MASTER_ADDRESS')
            testnet = os.getenv('USE_TESTNET', 'false').lower() == 'true'
        
        self._exchange = ValiantHyperliquidExchange(
            agent_private_key=agent_key,
            master_address=master_addr,
            testnet=testnet
        )
        
        # Expose methods
        self.get_balance = self._exchange.get_balance
        self.get_positions = self._exchange.get_positions
        self.get_open_positions = self._exchange.get_positions  # Alias for compatibility
        self.get_open_orders = self._exchange.get_open_orders
        self.get_mid_price = self._exchange.get_mid_price
        self.get_candles = self._exchange.get_candles
        self.set_leverage = self._exchange.set_leverage
        self.market_order = self._exchange.market_order
        self.market_close = self._exchange.market_close
        self.limit_order = self._exchange.limit_order
        self.cancel_order = self._exchange.cancel_order
        self.cancel_all_orders = self._exchange.cancel_all_orders
        self.get_account_summary = self._exchange.get_account_summary
        
        # FIX: Add place_order for bot.py compatibility
        self.place_order = self._exchange.place_order
        self.place_trigger_order = self._exchange.place_trigger_order
        
        # Expose remaining methods
        self.get_funding_rate = lambda symbol: 0.0  # TODO: implement
        self.get_recent_trades = self._exchange.get_recent_trades  # Fixed!
        self.stop_ws = lambda: None  # No WebSocket to stop


# ============================================================
# CLI TEST
# ============================================================

def test_valiant_connection():
    """Test kết nối Valiant"""
    print("=" * 60)
    print("VALIANT HYPERLIQUID TEST")
    print("=" * 60)
    
    try:
        # Khởi tạo
        exchange = ValiantHyperliquidExchange()
        
        # Test balance
        balance = exchange.get_balance()
        print(f"\n💰 Balance: ${balance:.2f}")
        
        # Test positions
        positions = exchange.get_positions()
        print(f"📊 Positions: {len(positions)}")
        for p in positions:
            print(f"   {p['symbol']}: {p['side']} {p['size']} @ ${p['entry_price']}")
        
        # Test price
        btc_price = exchange.get_mid_price("BTC")
        print(f"\n💵 BTC Price: ${btc_price}")
        
        # Test candles
        candles = exchange.get_candles("BTC", "15m", 5)
        if candles:
            print(f"\n📈 BTC Candles (last 5):")
            for c in candles[-5:]:
                print(f"   O:{c['open']:.0f} H:{c['high']:.0f} L:{c['low']:.0f} C:{c['close']:.0f}")
        
        print("\n✅ Connection successful!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_valiant_connection()
    else:
        print("Usage: python valiant_exchange.py --test")
        print("\nSet environment variables:")
        print("  VALIANT_AGENT_KEY=<your_agent_private_key>")
        print("  VALIANT_MASTER_ADDRESS=<your_master_address>")
