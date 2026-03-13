"""
Lighter SDK - Full Implementation for Valiant Bot
REST API client for Lighter DEX (zkLighter)
"""
import logging
import requests
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from decimal import Decimal

logger = logging.getLogger("lighter")

@dataclass
class Configuration:
    """Lighter API Configuration"""
    host: str = "https://mainnet.zklighter.elliot.ai"

class ApiClient:
    """REST API Client for Lighter"""
    
    def __init__(self, configuration: Configuration = None):
        self.config = configuration or Configuration()
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
    async def call_api(self, path: str, method: str = "GET", **kwargs) -> Any:
        """Make API call"""
        url = f"{self.config.host}{path}"
        try:
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API error {response.status_code}: {response.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"API call failed: {e}")
            return None
    
    async def close(self):
        """Close session"""
        self.session.close()

class OrderApi:
    """Order API for Lighter"""
    
    def __init__(self, api_client: ApiClient):
        self.client = api_client
    
    async def order_book_details(self, market_id: int) -> Any:
        """Get order book details for a market"""
        result = await self.client.call_api(f"/v1/orderBookDetails?marketId={market_id}")
        if result:
            # Convert dict to object-like access
            return DictObject({
                'order_book_details': [DictObject(d) for d in result] if isinstance(result, list) else [DictObject(result)]
            })
        return None

class FundingApi:
    """Funding API for Lighter"""
    
    def __init__(self, api_client: ApiClient):
        self.client = api_client
    
    async def funding_rates(self) -> List[Dict]:
        """Get funding rates for all markets"""
        result = await self.client.call_api("/v1/fundingRates")
        if result:
            if isinstance(result, list):
                return [DictObject(r) for r in result]
            return [DictObject(result)]
        return []

class AccountApi:
    """Account API for Lighter"""
    
    def __init__(self, api_client: ApiClient):
        self.client = api_client
    
    async def account(self, by: str = "index", value: str = "0") -> Any:
        """Get account details"""
        result = await self.client.call_api(f"/v1/account?by={by}&value={value}")
        if result:
            return DictObject({
                'accounts': [DictObject(result)] if not isinstance(result, list) else [DictObject(r) for r in result]
            })
        return None

class DictObject:
    """Helper class to access dict keys as attributes"""
    def __init__(self, data: dict):
        self._data = data
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, DictObject(value))
            elif isinstance(value, list):
                setattr(self, key, [DictObject(item) if isinstance(item, dict) else item for item in value])
            else:
                setattr(self, key, value)
    
    def __getattr__(self, name):
        return self._data.get(name, None)
    
    def __repr__(self):
        return f"DictObject({self._data})"

# Export all classes
__all__ = [
    'Configuration', 
    'ApiClient', 
    'OrderApi', 
    'FundingApi', 
    'AccountApi',
    'DictObject'
]
