# Deploy to Fly.io

## 1. Install Fly CLI
```bash
# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex

# Mac/Linux
curl -L https://fly.io/install.sh | sh
```

## 2. Login
```bash
fly auth login
```

## 3. Launch App
```bash
cd backend
fly launch
```
- Chọn app name: `valiant-bot-backend` (hoặc tên khác)
- Chọn region: Singapore (sin) gần VN nhất
- Database: No (không cần)

## 4. Set Secrets (Environment Variables)
```bash
fly secrets set VALIANT_AGENT_KEY="your_key"
fly secrets set VALIANT_MASTER_ADDRESS="0x..."
fly secrets set LIGHTER_API_PRIVATE_KEYS='{"2":"your_key"}'
fly secrets set LIGHTER_ACCOUNT_INDEX="2"
fly secrets set OPENAI_API_KEY="sk-..."  # nếu cần
```

## 5. Deploy
```bash
fly deploy
```

## 6. Check Logs
```bash
fly logs
```

## 7. Get URL
```bash
fly status
# Hoặc
fly info
```

URL sẽ là: `https://valiant-bot-backend.fly.dev`

## 8. Update Frontend
Sửa `app/src/config.ts`:
```typescript
export const API_URL = 'https://valiant-bot-backend.fly.dev';
```

## Scale (Free Tier)
```bash
# Scale to 1 machine, 512MB RAM (free)
fly scale vm shared-cpu-1x --memory 512

# Ensure 1 machine always running
fly scale count 1
```

## Check if Lighter works
Trong logs nếu thấy:
```
Lighter SDK connected successfully!
USDC Balance: $xxx
```
→ Lighter hoạt động! Chạy được **Hedge mode**!

## Troubleshooting

### If Lighter still 403
Fly.io IP có thể vẫn bị block. Thêm proxy:
```bash
fly secrets set LIGHTER_PROXY_URL="http://user:pass@proxy:port"
```

### Restart app
```bash
fly restart
```

### Check machine status
```bash
fly machine list
fly machine status <machine_id>
```
