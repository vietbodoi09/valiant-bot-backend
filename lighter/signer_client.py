"""
Signer Client for Lighter - Handles transaction signing
"""
import logging
import json
import time
import hashlib
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal
import requests

logger = logging.getLogger("lighter.signer_client")

class SignerClient:
    """
    SignerClient for Lighter trading
    Handles order signing and submission to Lighter API
    """
    
    def __init__(self, url: str, account_index: int, api_private_keys: Dict[int, str]):
        self.url = url.rstrip('/')
        self.account_index = account_index
        self.api_private_keys = api_private_keys
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self._connected = False
        logger.info(f"SignerClient initialized for account {account_index}")
        
    def check_client(self) -> Optional[str]:
        """Check if client is properly configured"""
        if not self.api_private_keys:
            return "No API keys provided"
        if self.account_index not in self.api_private_keys:
            return f"No API key for account index {self.account_index}"
        self._connected = True
        return None
        
    def _get_private_key(self) -> str:
        """Get private key for current account"""
        return self.api_private_keys.get(self.account_index, "")
    
    def _sign_message(self, message: str) -> str:
        """Sign a message with the private key (simplified)"""
        # In production, this should use proper ECDSA signing
        # For now, we return a placeholder signature
        private_key = self._get_private_key()
        if not private_key:
            return ""
        # Create a simple hash-based signature
        data = f"{message}:{private_key}:{int(time.time())}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    async def create_market_order(
        self,
        market_index: int,
        client_order_index: int,
        base_amount: int,
        avg_execution_price: int,
        is_ask: bool
    ) -> Tuple[Any, str, Optional[str]]:
        """
        Create a market order
        
        Args:
            market_index: Market ID (1=BTC, 2=ETH, 3=SOL)
            client_order_index: Unique order index
            base_amount: Amount in base units
            avg_execution_price: Price with slippage
            is_ask: True for sell/short, False for buy/long
            
        Returns:
            Tuple of (transaction_response, tx_hash, error)
        """
        try:
            # Build order payload
            order_payload = {
                "market_index": market_index,
                "client_order_index": client_order_index,
                "base_amount": str(base_amount),
                "avg_execution_price": str(avg_execution_price),
                "is_ask": is_ask,
                "account_index": self.account_index,
                "signature": self._sign_message(f"{market_index}:{client_order_index}:{base_amount}")
            }
            
            # Submit to Lighter API
            response = self.session.post(
                f"{self.url}/v1/order",
                json=order_payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                tx_hash = result.get('tx_hash', '') or result.get('transaction_hash', '')
                
                # Check for quota messages
                message = result.get('message', '')
                if tx_hash:
                    logger.info(f"Order placed successfully: {tx_hash[:32]}...")
                    return result, tx_hash, None
                else:
                    return result, str(result), None
            else:
                error_msg = f"Order failed: HTTP {response.status_code} - {response.text[:200]}"
                logger.error(error_msg)
                return None, "", error_msg
                
        except Exception as e:
            error_msg = f"Order exception: {str(e)}"
            logger.error(error_msg)
            return None, "", error_msg
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        try:
            response = self.session.post(
                f"{self.url}/v1/cancelOrder",
                json={
                    "order_id": order_id,
                    "account_index": self.account_index,
                    "signature": self._sign_message(f"cancel:{order_id}")
                },
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False
    
    def get_balance(self) -> float:
        """Get USDC balance"""
        try:
            response = self.session.get(
                f"{self.url}/v1/account?by=index&value={self.account_index}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    available = data.get('available_balance', 0)
                    collateral = data.get('collateral', 0)
                    return float(available or collateral or 0)
            return 0.0
        except Exception as e:
            logger.debug(f"Get balance failed: {e}")
            return 0.0
        
    def get_position(self, market_id: int) -> Optional[Dict]:
        """Get position for a market"""
        try:
            response = self.session.get(
                f"{self.url}/v1/account?by=index&value={self.account_index}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                positions = data.get('positions', []) if isinstance(data, dict) else []
                
                for p in positions:
                    if p.get('market_id') == market_id or p.get('market_index') == market_id:
                        position_size = float(p.get('position', 0))
                        sign = int(p.get('sign', 1))
                        
                        return {
                            "market_id": market_id,
                            "size": position_size,
                            "side": "long" if sign > 0 else "short",
                            "entry_price": float(p.get('avg_entry_price', 0)),
                            "unrealized_pnl": float(p.get('unrealized_pnl', 0)),
                            "position_value": float(p.get('position_value', 0)),
                            "liquidation_price": float(p.get('liquidation_price', 0)) if p.get('liquidation_price') else 0,
                        }
            return None
        except Exception as e:
            logger.debug(f"Get position failed: {e}")
            return None
    
    async def close(self):
        """Close session"""
        self.session.close()
        self._connected = False
