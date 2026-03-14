"""
Valiant Bot Backend - Production FastAPI Server
Multi-user bot control with secure API key handling + Admin Key Management
"""
import os
import sys
import json
import asyncio
import logging
import uuid
import hashlib
import hmac
import secrets
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Try to import jwt
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    print("Warning: PyJWT not installed. Using simple token system.")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-12s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Backend")

# ==================== AUTH CONFIGURATION ====================
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
KEY_SALT = os.getenv("KEY_SALT", secrets.token_hex(16))
ADMIN_KEY = os.getenv("ADMIN_KEY", secrets.token_urlsafe(16))
RATE_LIMIT_WINDOW = 300
RATE_LIMIT_MAX = 5

# ==================== MASTER KEY DATABASE ====================
class MasterKey:
    def __init__(self, name: str, expires_days: Optional[int] = None, max_devices: int = 1):
        self.id = str(uuid.uuid4())[:8]
        self.key = f"VALIANT-{secrets.token_hex(8).upper()}"
        self.name = name
        self.created_at = datetime.now()
        self.expires_at = datetime.now() + timedelta(days=expires_days) if expires_days else None
        self.is_active = True
        self.max_devices = max_devices
        self.current_devices = 0
        self.usage_count = 0
        self.last_used = None
        self.created_by = "admin"
        self.device_ids = set()
    
    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key[:20] + "..." if self.is_active else self.key,  # Mask active keys
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "max_devices": self.max_devices,
            "current_devices": self.current_devices,
            "usage_count": self.usage_count,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "created_by": self.created_by
        }

# In-memory storage
master_keys_db: Dict[str, MasterKey] = {}
failed_attempts: Dict[str, list] = {}
revoked_tokens: set = set()

# ==================== AUTH MODELS ====================
class CreateKeyRequest(BaseModel):
    admin_key: str
    name: str
    expires_days: Optional[int] = 30
    max_devices: int = 1

class AuthRequest(BaseModel):
    master_key: str
    device_fingerprint: str
    timestamp: int

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    device_id: str

# ==================== AUTH FUNCTIONS ====================
def verify_admin_key(key: str) -> bool:
    """Verify admin key"""
    return hmac.compare_digest(key, ADMIN_KEY)

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    attempts = failed_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < RATE_LIMIT_WINDOW]
    failed_attempts[ip] = attempts
    return len(attempts) < RATE_LIMIT_MAX

def record_failed_attempt(ip: str):
    if ip not in failed_attempts:
        failed_attempts[ip] = []
    failed_attempts[ip].append(time.time())

def create_token(device_fingerprint: str) -> str:
    if JWT_AVAILABLE:
        now = datetime.utcnow()
        payload = {
            "sub": device_fingerprint,
            "iat": now,
            "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
            "jti": secrets.token_hex(16),
            "type": "access"
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    else:
        return hashlib.sha256(f"{device_fingerprint}{JWT_SECRET}{time.time()}".encode()).hexdigest()

def verify_token(token: str) -> Optional[dict]:
    if token in revoked_tokens:
        return None
    if JWT_AVAILABLE:
        try:
            return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except:
            return None
    return {"sub": "unknown"}

def generate_device_id(fingerprint: str) -> str:
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]

def verify_master_key(key: str, device_id: str) -> Optional[MasterKey]:
    """Verify master key and check device limits"""
    for mk in master_keys_db.values():
        if mk.key == key and mk.is_active:
            # Check expiry
            if mk.expires_at and datetime.now() > mk.expires_at:
                return None
            
            # Check device limit
            if device_id not in mk.device_ids and len(mk.device_ids) >= mk.max_devices:
                return None
            
            # Register device
            mk.device_ids.add(device_id)
            mk.current_devices = len(mk.device_ids)
            mk.usage_count += 1
            mk.last_used = datetime.now()
            
            return mk
    return None

# ==================== ORIGINAL BOT CODE ====================
def check_lighter_config():
    lighter_keys = os.getenv("LIGHTER_API_PRIVATE_KEYS")
    lighter_account = os.getenv("LIGHTER_ACCOUNT_INDEX", "0")
    lighter_api_key_idx = os.getenv("LIGHTER_API_KEY_INDEX")
    
    if not lighter_keys:
        logger.warning("LIGHTER_API_PRIVATE_KEYS not set - Lighter trading will fail")
        return
    
    try:
        keys = json.loads(lighter_keys)
        account_idx = int(lighter_account)
        if lighter_api_key_idx is not None:
            api_key_idx = int(lighter_api_key_idx)
        else:
            api_key_idx = int(list(keys.keys())[0]) if keys else 0
        
        logger.info(f"Lighter config: API key indices: {list(keys.keys())}, account: {account_idx}, api_key: {api_key_idx}")
        
        if str(api_key_idx) not in keys:
            logger.error(f"API key index {api_key_idx} not found!")
    except Exception as e:
        logger.error(f"Error checking Lighter config: {e}")

check_lighter_config()

bot_sessions: Dict[str, 'BotSession'] = {}

class BotConfig(BaseModel):
    mode: str = "hedge"
    symbol: str = "BTC"
    size_usd: float = 150.0
    leverage: int = 10
    spam_interval: float = 10.0
    spam_rounds: int = 10
    hedge_hold_hours: float = 8.0
    auto_reenter: bool = True
    cycles: int = 1

class APIKeys(BaseModel):
    valiant_agent_key: str
    valiant_master_address: str
    lighter_api_key: str
    lighter_account_index: int = 0
    lighter_api_key_index: int = 2

class StartRequest(BaseModel):
    config: BotConfig
    api_keys: APIKeys

class BotSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.bot = None
        self.bot_task = None
        self.is_running = False
        self.config = None
        self.api_keys = None
        self.websockets = []
        self.logs = []
        self.positions = {"hyperliquid": None, "lighter": None}
        self.balances = {"hyperliquid": 0.0, "lighter": 0.0}
        self.stats = {"total_trades": 0, "total_volume": 0.0, "total_pnl": 0.0, "start_time": None}
        self.created_at = datetime.now()
        self._log_batch = []
        self._broadcast_task = None
    
    def _schedule_broadcast(self):
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._flush_log_batch())
    
    async def _flush_log_batch(self):
        await asyncio.sleep(0.05)
        if self._log_batch:
            await self.broadcast({"type": "log", "data": self._log_batch})
            self._log_batch = []
    
    async def connect_websocket(self, websocket: WebSocket):
        await websocket.accept()
        self.websockets.append(websocket)
        logger.info(f"[{self.session_id}] WebSocket connected. Total: {len(self.websockets)}")
        await self.send_state(websocket)
    
    async def disconnect_websocket(self, websocket: WebSocket):
        if websocket in self.websockets:
            self.websockets.remove(websocket)
        logger.info(f"[{self.session_id}] WebSocket disconnected. Total: {len(self.websockets)}")
    
    async def broadcast(self, message: dict):
        disconnected = []
        for ws in self.websockets:
            try:
                await ws.send_json(message)
            except:
                disconnected.append(ws)
        for ws in disconnected:
            if ws in self.websockets:
                self.websockets.remove(ws)
    
    async def send_state(self, websocket: WebSocket):
        try:
            await websocket.send_json({
                "type": "state",
                "data": {
                    "is_running": self.is_running,
                    "mode": self.config.mode if self.config else "hedge",
                    "stats": self.stats,
                    "positions": self.positions,
                    "balances": self.balances,
                    "logs": self.logs[-100:]
                }
            })
        except Exception as e:
            logger.error(f"[{self.session_id}] Failed to send state: {e}")
    
    def add_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        self._log_batch.append(log_entry)
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
        self._schedule_broadcast()
    
    def update_position(self, exchange: str, position: dict):
        self.positions[exchange] = position
        asyncio.create_task(self.broadcast({
            "type": "position",
            "data": {"exchange": exchange, "position": position}
        }))
    
    def update_stats(self, stats: dict):
        self.stats.update(stats)
        asyncio.create_task(self.broadcast({"type": "stats", "data": self.stats}))
    
    def update_balances(self, balances: dict):
        self.balances.update(balances)
        asyncio.create_task(self.broadcast({"type": "balances", "data": self.balances}))
    
    async def start_bot(self, config: BotConfig, api_keys: APIKeys):
        if self.is_running:
            raise HTTPException(status_code=400, detail="Bot is already running")
        
        self.config = config
        self.api_keys = api_keys
        self.is_running = True
        self.stats["start_time"] = datetime.now().isoformat()
        
        self.add_log(f"Bot STARTED - {config.mode.upper()} mode")
        self.add_log(f"Symbol: {config.symbol}, Size: ${config.size_usd}, Leverage: {config.leverage}x")
        
        self.bot_task = asyncio.create_task(self._run_bot())
        return {"status": "started", "session_id": self.session_id}
    
    async def _run_bot(self):
        try:
            from bot_runner import BotRunner
            
            os.environ["VALIANT_AGENT_KEY"] = self.api_keys.valiant_agent_key
            os.environ["VALIANT_MASTER_ADDRESS"] = self.api_keys.valiant_master_address
            os.environ["LIGHTER_API_PRIVATE_KEYS"] = self.api_keys.lighter_api_key
            os.environ["LIGHTER_ACCOUNT_INDEX"] = str(self.api_keys.lighter_account_index)
            os.environ["LIGHTER_API_KEY_INDEX"] = str(self.api_keys.lighter_api_key_index)
            
            self.bot = BotRunner(self.config.dict(), self)
            await self.bot.run()
            
        except Exception as e:
            logger.error(f"[{self.session_id}] Bot error: {e}")
            self.add_log(f"ERROR: {str(e)}")
            import traceback
            self.add_log(traceback.format_exc())
        finally:
            self.is_running = False
            self.add_log("Bot STOPPED")
    
    async def stop_bot(self):
        if not self.is_running:
            return {"status": "not_running"}
        
        if getattr(self, '_is_stopping', False):
            return {"status": "already_stopping"}
        self._is_stopping = True
        
        self.is_running = False
        self.add_log("Stopping bot and closing all positions...")
        
        if self.bot_task:
            self.bot_task.cancel()
            try:
                await self.bot_task
            except asyncio.CancelledError:
                pass
        
        if self.bot:
            try:
                await self.bot.stop()
            except Exception as e:
                self.add_log(f"Error during stop: {e}")
        
        self._is_stopping = False
        self.add_log("Bot STOPPED by user")
        return {"status": "stopped"}


# ==================== FASTAPI APP ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 50)
    logger.info("Backend starting...")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Sessions: {len(bot_sessions)}")
    logger.info(f"Master Keys: {len(master_keys_db)}")
    logger.info(f"JWT: {JWT_AVAILABLE}")
    logger.info("=" * 50)
    
    async def keep_alive():
        while True:
            await asyncio.sleep(60)
            running = sum(1 for s in bot_sessions.values() if s.is_running)
            if running > 0:
                logger.info(f"Keep-alive: {running} bots running")
    
    async def cleanup():
        while True:
            await asyncio.sleep(3600)
            now = datetime.now()
            for sid, session in list(bot_sessions.items()):
                if not session.is_running and (now - session.created_at).total_seconds() > 86400:
                    del bot_sessions[sid]
                    logger.info(f"Cleaned up: {sid}")
    
    asyncio.create_task(keep_alive())
    asyncio.create_task(cleanup())
    yield
    
    for session in bot_sessions.values():
        if session.is_running:
            await session.stop_bot()

app = FastAPI(title="Valiant Bot Backend with Admin", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== ADMIN ENDPOINTS ====================
@app.get("/api/admin/verify")
async def verify_admin(admin_key: str):
    """Verify admin key"""
    if not verify_admin_key(admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return {"valid": True}

@app.get("/api/admin/stats")
async def get_admin_stats(admin_key: str):
    """Get admin statistics"""
    if not verify_admin_key(admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    
    active_keys = sum(1 for k in master_keys_db.values() if k.is_active)
    expired_keys = sum(1 for k in master_keys_db.values() if k.expires_at and datetime.now() > k.expires_at)
    
    return {
        "total_keys": len(master_keys_db),
        "active_keys": active_keys,
        "revoked_keys": len(master_keys_db) - active_keys,
        "expired_keys": expired_keys,
        "total_sessions": len(bot_sessions),
        "active_sessions": sum(1 for s in bot_sessions.values() if s.is_running),
        "failed_attempts_24h": sum(len(attempts) for attempts in failed_attempts.values())
    }

@app.get("/api/admin/keys")
async def list_keys(admin_key: str):
    """List all master keys"""
    if not verify_admin_key(admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    
    return {"keys": [k.to_dict() for k in master_keys_db.values()]}

@app.post("/api/admin/keys")
async def create_key(request: CreateKeyRequest):
    """Create new master key"""
    if not verify_admin_key(request.admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    
    key = MasterKey(
        name=request.name,
        expires_days=request.expires_days,
        max_devices=request.max_devices
    )
    master_keys_db[key.id] = key
    
    logger.info(f"Created master key: {key.id} for {request.name}")
    
    return {
        "id": key.id,
        "key": key.key,  # Only show full key once
        "name": key.name,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None
    }

@app.post("/api/admin/keys/{key_id}/revoke")
async def revoke_key(key_id: str, admin_key: str):
    """Revoke a master key"""
    if not verify_admin_key(admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    
    if key_id not in master_keys_db:
        raise HTTPException(status_code=404, detail="Key not found")
    
    master_keys_db[key_id].is_active = False
    logger.info(f"Revoked key: {key_id}")
    
    return {"status": "revoked"}

@app.post("/api/admin/keys/{key_id}/reactivate")
async def reactivate_key(key_id: str, admin_key: str):
    """Reactivate a revoked key"""
    if not verify_admin_key(admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    
    if key_id not in master_keys_db:
        raise HTTPException(status_code=404, detail="Key not found")
    
    master_keys_db[key_id].is_active = True
    logger.info(f"Reactivated key: {key_id}")
    
    return {"status": "reactivated"}

@app.delete("/api/admin/keys/{key_id}")
async def delete_key(key_id: str, admin_key: str):
    """Permanently delete a key"""
    if not verify_admin_key(admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    
    if key_id not in master_keys_db:
        raise HTTPException(status_code=404, detail="Key not found")
    
    del master_keys_db[key_id]
    logger.info(f"Deleted key: {key_id}")
    
    return {"status": "deleted"}


# ==================== AUTH ENDPOINTS ====================
@app.post("/api/auth/verify")
async def authenticate(request: Request, auth_req: AuthRequest):
    """Verify master key and issue token"""
    client_ip = get_client_ip(request)
    
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 5 minutes.")
    
    now = int(time.time())
    if abs(now - auth_req.timestamp) > 60:
        raise HTTPException(status_code=400, detail="Request expired.")
    
    device_id = generate_device_id(auth_req.device_fingerprint)
    master_key = verify_master_key(auth_req.master_key, device_id)
    
    if not master_key:
        record_failed_attempt(client_ip)
        remaining = RATE_LIMIT_MAX - len(failed_attempts.get(client_ip, []))
        raise HTTPException(status_code=401, detail=f"Invalid key or device limit reached. {remaining} attempts left.")
    
    token = create_token(auth_req.device_fingerprint)
    
    return {
        "access_token": token,
        "expires_in": JWT_EXPIRY_HOURS * 3600,
        "device_id": device_id,
        "key_name": master_key.name
    }

@app.post("/api/auth/refresh")
async def refresh_token(token: str):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    new_token = create_token(payload["sub"])
    revoked_tokens.add(token)
    
    return {"access_token": new_token, "expires_in": JWT_EXPIRY_HOURS * 3600}

@app.post("/api/auth/logout")
async def logout(token: str):
    revoked_tokens.add(token)
    return {"status": "logged_out"}

@app.get("/api/auth/verify-token")
async def check_token(token: str):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"valid": True}


# ==================== BOT ENDPOINTS ====================
@app.get("/")
async def root():
    return {
        "message": "Valiant Bot Backend with Admin",
        "status": "running",
        "master_keys": len(master_keys_db),
        "sessions": len(bot_sessions),
        "running_bots": sum(1 for s in bot_sessions.values() if s.is_running)
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/api/start")
async def start_bot(request: StartRequest):
    session_id = str(uuid.uuid4())[:8]
    session = BotSession(session_id)
    bot_sessions[session_id] = session
    return await session.start_bot(request.config, request.api_keys)

@app.post("/api/stop/{session_id}")
async def stop_bot(session_id: str):
    if session_id not in bot_sessions:
        return {"status": "stopped"}
    return await bot_sessions[session_id].stop_bot()

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    if session_id not in bot_sessions:
        await websocket.close(code=4004)
        return
    
    session = bot_sessions[session_id]
    await session.connect_websocket(websocket)
    
    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.receive":
                text = data.get("text", "")
                if text:
                    msg = json.loads(text)
                    if msg.get("action") == "stop":
                        await session.stop_bot()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        await session.disconnect_websocket(websocket)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)