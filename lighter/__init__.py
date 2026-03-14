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
    BROWSER_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
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
                return response.json()
            else:
                body_preview = response.text[:500] if response.text else "(empty)"
                logger.error(f"API error {response.status_code} for {path}: {body_preview}")
                # If 403, try without proxy as fallback
                if response.status_code == 403 and self.session.proxies:
                    logger.info(f"Retrying {path} without proxy...")
                    try:
                        fallback = requests.get(url, headers=self.BROWSER_HEADERS, timeout=10)
                        if fallback.status_code == 200:
                            logger.info(f"Direct request succeeded for {path}!")
                            return fallback.json()
                        else:
                            logger.error(f"Direct request also failed: {fallback.status_code}: {fallback.text[:200]}")
                    except Exception as e2:
                        logger.error(f"Direct request exception: {e2}")
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
        if result:
            # Response may be wrapped: {"code":200, ...account_fields...}
            # or direct account object
            if isinstance(result, dict):
                return DictObject({
                    'accounts': [DictObject(result)]
                })
            elif isinstance(result, list):
                return DictObject({
                    'accounts': [DictObject(r) for r in result]
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