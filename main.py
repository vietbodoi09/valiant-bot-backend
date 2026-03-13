"""
Valiant Bot Backend - Production FastAPI Server
Multi-user bot control with secure API key handling
"""
import os
import sys
import json
import asyncio
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-12s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Backend")

# Global bot sessions storage
bot_sessions: Dict[str, 'BotSession'] = {}

class BotConfig(BaseModel):
    mode: str = "hedge"  # "spam" or "hedge"
    symbol: str = "BTC"
    size_usd: float = 150.0
    leverage: int = 10
    spam_interval: float = 10.0
    spam_rounds: int = 10
    hedge_hold_hours: float = 8.0
    auto_reenter: bool = True

class APIKeys(BaseModel):
    valiant_agent_key: str
    valiant_master_address: str
    lighter_api_key: str  # JSON string
    lighter_account_index: int = 0

class StartRequest(BaseModel):
    config: BotConfig
    api_keys: APIKeys

class BotSession:
    """Manages a single bot instance for a user"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.bot = None
        self.bot_task = None
        self.is_running = False
        self.config = None
        self.api_keys = None
        self.websockets = []
        self.logs = []
        self.positions = {
            "hyperliquid": None,
            "lighter": None
        }
        self.stats = {
            "total_trades": 0,
            "total_volume": 0.0,
            "total_pnl": 0.0,
            "start_time": None
        }
        self.created_at = datetime.now()
    
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
        """Broadcast message to all connected websockets"""
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
        """Send current state to websocket"""
        try:
            await websocket.send_json({
                "type": "state",
                "data": {
                    "is_running": self.is_running,
                    "mode": self.config.mode if self.config else "hedge",
                    "stats": self.stats,
                    "positions": self.positions,
                    "logs": self.logs[-100:]  # Last 100 logs
                }
            })
        except Exception as e:
            logger.error(f"[{self.session_id}] Failed to send state: {e}")
    
    def add_log(self, message: str):
        """Add log entry"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        
        # Keep only last 1000 logs
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
        
        # Broadcast to all websockets
        asyncio.create_task(self.broadcast({
            "type": "log",
            "data": log_entry
        }))
    
    def update_position(self, exchange: str, position: dict):
        """Update position data"""
        self.positions[exchange] = position
        asyncio.create_task(self.broadcast({
            "type": "position",
            "data": {
                "exchange": exchange,
                "position": position
            }
        }))
    
    def update_stats(self, stats: dict):
        """Update stats"""
        self.stats.update(stats)
        asyncio.create_task(self.broadcast({
            "type": "stats",
            "data": self.stats
        }))
    
    async def start_bot(self, config: BotConfig, api_keys: APIKeys):
        """Start the bot"""
        if self.is_running:
            raise HTTPException(status_code=400, detail="Bot is already running")
        
        self.config = config
        self.api_keys = api_keys
        self.is_running = True
        self.stats["start_time"] = datetime.now().isoformat()
        
        self.add_log(f"Bot STARTED - {config.mode.upper()} mode")
        self.add_log(f"Symbol: {config.symbol}, Size: ${config.size_usd}, Leverage: {config.leverage}x")
        
        # Start bot in background task
        self.bot_task = asyncio.create_task(self._run_bot())
        
        return {"status": "started", "session_id": self.session_id}
    
    async def _run_bot(self):
        """Run bot loop"""
        try:
            # Import bot here to use updated env vars
            from bot_runner import BotRunner
            
            # Set env vars for this session
            os.environ["VALIANT_AGENT_KEY"] = self.api_keys.valiant_agent_key
            os.environ["VALIANT_MASTER_ADDRESS"] = self.api_keys.valiant_master_address
            os.environ["LIGHTER_API_PRIVATE_KEYS"] = self.api_keys.lighter_api_key
            os.environ["LIGHTER_ACCOUNT_INDEX"] = str(self.api_keys.lighter_account_index)
            
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
        """Stop the bot"""
        if not self.is_running:
            return {"status": "not_running"}
        
        self.is_running = False
        
        if self.bot_task:
            self.bot_task.cancel()
            try:
                await self.bot_task
            except asyncio.CancelledError:
                pass
        
        if self.bot:
            await self.bot.stop()
        
        self.add_log("Bot STOPPED by user")
        return {"status": "stopped"}


# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan handler"""
    logger.info("=" * 50)
    logger.info("Backend starting...")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Active sessions: {len(bot_sessions)}")
    logger.info("=" * 50)
    
    # Keep-alive ping to prevent Render from sleeping when bots are running
    async def keep_alive():
        while True:
            await asyncio.sleep(60)  # Every minute
            running_count = sum(1 for s in bot_sessions.values() if s.is_running)
            if running_count > 0:
                logger.info(f"Keep-alive: {running_count} bots running")
    
    # Cleanup old sessions periodically
    async def cleanup_old_sessions():
        while True:
            await asyncio.sleep(3600)  # Every hour
            now = datetime.now()
            to_remove = []
            for session_id, session in bot_sessions.items():
                # Remove sessions older than 24 hours that are not running
                if not session.is_running and (now - session.created_at).total_seconds() > 86400:
                    to_remove.append(session_id)
            
            for session_id in to_remove:
                del bot_sessions[session_id]
                logger.info(f"Cleaned up old session: {session_id}")
    
    keep_alive_task = asyncio.create_task(keep_alive())
    cleanup_task = asyncio.create_task(cleanup_old_sessions())
    yield
    
    keep_alive_task.cancel()
    cleanup_task.cancel()
    logger.info("Backend shutting down...")
    
    # Stop all running bots
    for session in bot_sessions.values():
        if session.is_running:
            await session.stop_bot()

app = FastAPI(title="Valiant Bot Backend", lifespan=lifespan)

# CORS - Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# REST API Endpoints
@app.get("/")
async def root():
    return {
        "message": "Valiant Bot Backend",
        "status": "running",
        "active_sessions": len(bot_sessions),
        "running_bots": sum(1 for s in bot_sessions.values() if s.is_running)
    }

@app.get("/health")
async def health():
    logger.info("Health check requested")
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/api/test")
async def test():
    """Test endpoint"""
    return {"message": "Backend is working!"}

@app.get("/api/status/{session_id}")
async def get_status(session_id: str):
    """Get bot status for a session"""
    if session_id not in bot_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = bot_sessions[session_id]
    return {
        "is_running": session.is_running,
        "mode": session.config.mode if session.config else None,
        "stats": session.stats,
        "positions": session.positions
    }

@app.post("/api/start")
async def start_bot(request: StartRequest):
    """Start a new bot session"""
    # Generate new session ID
    session_id = str(uuid.uuid4())[:8]
    
    # Create new session
    session = BotSession(session_id)
    bot_sessions[session_id] = session
    
    # Start bot
    return await session.start_bot(request.config, request.api_keys)

@app.post("/api/stop/{session_id}")
async def stop_bot(session_id: str):
    """Stop a bot session"""
    if session_id not in bot_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return await bot_sessions[session_id].stop_bot()

@app.get("/api/logs/{session_id}")
async def get_logs(session_id: str, limit: int = 100):
    """Get bot logs for a session"""
    if session_id not in bot_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"logs": bot_sessions[session_id].logs[-limit:]}


# WebSocket Endpoint
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    if session_id not in bot_sessions:
        await websocket.close(code=4004, reason="Session not found")
        return
    
    session = bot_sessions[session_id]
    await session.connect_websocket(websocket)
    
    try:
        while True:
            # Use receive_text with timeout to allow periodic checks
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(data)
                
                if msg.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg.get("action") == "stop":
                    await session.stop_bot()
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
            except json.JSONDecodeError:
                pass  # Ignore invalid JSON
            except Exception as e:
                logger.error(f"[{session_id}] WebSocket receive error: {e}")
                break
            
    except WebSocketDisconnect:
        logger.info(f"[{session_id}] WebSocket disconnected by client")
    except Exception as e:
        logger.error(f"[{session_id}] WebSocket error: {e}")
    finally:
        await session.disconnect_websocket(websocket)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
