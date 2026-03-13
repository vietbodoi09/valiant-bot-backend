# Setup Proxy cho Lighter API

## Vấn đề
Cloudflare block IP từ Render data center → Lighter API 403

## Giải pháp: Dùng Proxy Residential

### Bước 1: Đăng ký Webshare (Free)
1. Vào https://www.webshare.io/
2. Sign up free account
3. Vào dashboard lấy proxy credentials

### Bước 2: Set Environment Variable trên Render
Vào Render Dashboard → Environment → Add Variable:

```
LIGHTER_PROXY_URL=http://p.webshare.io:9999/username:password
```

Hoặc dùng format:
```
LIGHTER_PROXY_URL=http://username:password@p.webshare.io:9999
```

### Bước 3: Redeploy backend

## Test Proxy
Sau khi deploy, check log xem có dòng này không:
```
Using proxy for Lighter API
SignerClient using proxy
```

Nếu có → Lighter API sẽ hoạt động!

## Alternatives (nếu Webshare không work)

### Proxy-Cheap
- https://proxycheap.com/
- Residential proxy ~$3/GB

### Bright Data (formerly Luminati)  
- https://brightdata.com/
- Có free trial

### OxyLabs
- https://oxylabs.io/
- Residential proxy

## Lưu ý
- Chỉ cần proxy cho Lighter API
- Hyperliquid vẫn work bình thường không cần proxy
