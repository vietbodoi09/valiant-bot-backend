# Valiant Bot Backend

FastAPI backend for Delta-Neutral Arbitrage Bot. Controls bot execution and provides real-time updates via WebSocket.

## Features

- **REST API**: Start/stop bot, get status, fetch logs
- **WebSocket**: Real-time position updates, PnL, logs
- **Bot Integration**: Wrapper for bot2.py (Hyperliquid + Lighter)

## Prerequisites

```bash
# Python 3.9+
python --version

# Install dependencies
pip install -r requirements.txt

# Install Lighter SDK (if needed)
git clone https://github.com/lighter-io/lighter-python.git
```

## Configuration

Create `.env` file:

```env
# Optional - can also be sent from frontend
VALIANT_AGENT_KEY=your_agent_key
VALIANT_MASTER_ADDRESS=your_master_address
LIGHTER_API_PRIVATE_KEYS={"3": "your_private_key"}
LIGHTER_ACCOUNT_INDEX=0
```

## Run Backend

```bash
# Development
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/api/status` | GET | Get bot status |
| `/api/start` | POST | Start bot |
| `/api/stop` | POST | Stop bot |
| `/api/logs` | GET | Get bot logs |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws` | Real-time updates |

### Start Bot Request

```json
POST /api/start
{
  "config": {
    "mode": "hedge",
    "symbol": "BTC",
    "size_usd": 500,
    "leverage": 4,
    "spam_interval": 10,
    "spam_rounds": 10,
    "hedge_hold_hours": 8,
    "auto_reenter": true
  },
  "api_keys": {
    "valiant_agent_key": "0x...",
    "valiant_master_address": "0x...",
    "lighter_api_key": "{\"3\": \"...\"}",
    "lighter_account_index": 0
  }
}
```

### WebSocket Messages

**From Server:**

```json
// State update
{"type": "state", "data": {"is_running": true, "mode": "hedge", ...}}

// Log message
{"type": "log", "data": "[14:32:15] Bot started"}

// Position update
{"type": "position", "data": {"exchange": "hyperliquid", "position": {...}}}

// Stats update
{"type": "stats", "data": {"total_trades": 5, ...}}
```

## Frontend Integration

Update `API_URL` in `BotDashboard.tsx`:

```typescript
const API_URL = 'http://localhost:8000'; // Your backend URL
```

## Architecture

```
Frontend (React) <--WebSocket/HTTP--> Backend (FastAPI) <---> Bot Runner <---> Exchanges
                                                              (Hyperliquid, Lighter)
```

## Troubleshooting

### CORS Error

Update `main.py` to allow your frontend domain:

```python
allow_origins=["https://yourdomain.com"]
```

### Bot Not Starting

1. Check API keys are correct
2. Verify backend is running: `curl http://localhost:8000/`
3. Check logs for errors

### WebSocket Disconnects

- Backend auto-reconnects after 3 seconds
- Check network connection
- Verify backend is running
