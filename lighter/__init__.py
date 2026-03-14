"""
Lighter SDK - Full Implementation for Valiant Bot
REST API client for Lighter DEX (zkLighter)
"""
import logging
import os
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
    api_key: str = None

class ApiClient:
    """REST API Client for Lighter"""
    
    # Browser-like headers to avoid Cloudflare blocking datacenter IPs
    # NOTE: Do NOT include Accept-Encoding - proxy may not decompress gzip/br responses
    BROWSER_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
    }
    
    def __init__(self, configuration: Configuration = None):
        self.config = configuration or Configuration()
        self.session = requests.Session()
        
        # Add proxy if configured (to bypass Cloudflare from datacenter IPs)
        proxy_url = os.getenv('LIGHTER_PROXY_URL')
        if proxy_url:
            self.session.proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
            logger.info(f"Using proxy for Lighter API")
        
        # Use browser-like headers to pass Cloudflare
        self.session.headers.update(self.BROWSER_HEADERS)
        
    async def call_api(self, path: str, method: str = "GET", **kwargs) -> Any:
        """Make API call"""
        url = f"{self.config.host}{path}"
        try:
            response = self.session.request(method, url, **kwargs)
            
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception as je:
                    logger.warning(f"JSON parse failed for {path} via proxy, trying direct...")
                    # Fallback: direct request without proxy
                    try:
                        direct = requests.get(url, headers=self.BROWSER_HEADERS, timeout=10)
                        if direct.status_code == 200:
                            return direct.json()
                    except Exception as e2:
                        logger.error(f"Direct fallback also failed: {e2}")
                    return None
            else:
                logger.error(f"API error {response.status_code} for {path}")
                # If error, try direct request without proxy
                if self.session.proxies:
                    try:
                        direct = requests.get(url, headers=self.BROWSER_HEADERS, timeout=10)
                        if direct.status_code == 200:
                            logger.info(f"Direct request succeeded for {path}")
                            return direct.json()
                    except Exception as e2:
                        logger.error(f"Direct request failed: {e2}")
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
        result = await self.client.call_api(f"/api/v1/orderBookDetails?market_id={market_id}")
        if result:
            # Response format: {"code":200,"order_book_details":[...]}
            if isinstance(result, dict) and 'order_book_details' in result:
                details = result['order_book_details']
                return DictObject({
                    'order_book_details': [DictObject(d) for d in details] if isinstance(details, list) else [DictObject(details)]
                })
            # Fallback: direct list or single object
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
        result = await self.client.call_api("/api/v1/fundingRates")
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
        result = await self.client.call_api(f"/api/v1/account?by={by}&value={value}")
        if result and isinstance(result, dict):
            # Response format: {"code":200, "total":1, "accounts":[{...account data...}]}
            if 'accounts' in result:
                accs = result['accounts']
                if isinstance(accs, list):
                    return DictObject({
                        'accounts': [DictObject(a) for a in accs]
                    })
            # Fallback: response IS the account object directly
            return DictObject({
                'accounts': [DictObject(result)]
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