"""
Run backend locally with ngrok tunnel for Lighter API access
"""
import subprocess
import sys
import os
from pyngrok import ngrok

def main():
    # Setup ngrok (cần authtoken - đăng ký free tại ngrok.com)
    ngrok_token = os.getenv("NGROK_AUTH_TOKEN")
    if not ngrok_token:
        print("⚠️  Chưa có NGROK_AUTH_TOKEN")
        print("1. Vào https://ngrok.com đăng ký free account")
        print("2. Lấy authtoken từ dashboard")
        print("3. Set env: set NGROK_AUTH_TOKEN=your_token_here")
        return
    
    ngrok.set_auth_token(ngrok_token)
    
    # Start ngrok tunnel to port 8000
    public_url = ngrok.connect(8000, "http")
    print(f"🌐 Public URL: {public_url}")
    print(f"📋 Copy URL này update vào frontend API_URL")
    
    # Run uvicorn
    print("🚀 Starting backend...")
    subprocess.run([
        sys.executable, "-m", "uvicorn", 
        "main:app", 
        "--host", "0.0.0.0", 
        "--port", "8000",
        "--reload"
    ])

if __name__ == "__main__":
    main()
