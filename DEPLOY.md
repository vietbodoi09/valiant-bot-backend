# Deploy Backend to Render

## Quick Deploy (One-Click)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/yourusername/valiant-bot-backend)

## Manual Deploy

### Step 1: Create Render Account
1. Go to [render.com](https://render.com)
2. Sign up with GitHub or email
3. Verify your account

### Step 2: Create New Web Service
1. Click "New +" → "Web Service"
2. Connect your GitHub repo or use "Build and deploy from a Git repository"
3. If no repo, use "Create a new Web Service" with these settings:

**Settings:**
- **Name**: `valiant-bot-backend`
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Step 3: Environment Variables
No env vars needed - API keys are sent from frontend!

### Step 4: Deploy
Click "Create Web Service" and wait for deployment.

Your backend will be at: `https://valiant-bot-backend.onrender.com`

---

## Update Frontend to Use Deployed Backend

In `BotDashboard.tsx`, change:

```typescript
const API_URL = 'https://valiant-bot-backend.onrender.com';
```

Then rebuild and redeploy frontend.

---

## Important Notes

### Free Tier Limitations (Render)
- **Sleep after 15 min inactivity** - First request after sleep takes ~30s
- **512 MB RAM** - Should be enough for bot
- **100 GB bandwidth/month**

### Security
- API keys are NOT stored on server
- Each user sends their own keys when starting bot
- Sessions auto-delete after 24 hours

### Multiple Users
- Each user gets their own session ID
- Multiple bots can run simultaneously
- No interference between users

---

## Troubleshooting

### Bot won't start
Check Render logs for errors:
1. Go to Render dashboard
2. Click your service
3. Click "Logs" tab

### WebSocket disconnected
- Render free tier has 15min timeout
- Bot continues running even if WebSocket disconnects
- Reconnect by refreshing page

### "Session not found"
- Session expired (24 hours)
- Start a new bot session
