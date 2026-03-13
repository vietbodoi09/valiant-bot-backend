"""
Run backend locally with ngrok tunnel
IP nhà bạn sẽ bypass Cloudflare, Lighter sẽ work!
"""
import subprocess
import sys
import os
import time

def check_ngrok():
    """Check if ngrok is installed"""
    try:
        result = subprocess.run(['ngrok', '--version'], capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False

def install_ngrok():
    """Install ngrok"""
    print("📦 Installing ngrok...")
    # Windows install via Chocolatey or direct download
    try:
        subprocess.run(['choco', 'install', 'ngrok', '-y'], check=True)
    except:
        print("Please install ngrok manually from https://ngrok.com/download")
        print("Or run: choco install ngrok")
        sys.exit(1)

def main():
    # Check ngrok token
    ngrok_token = os.getenv("NGROK_AUTH_TOKEN")
    if not ngrok_token:
        print("="*60)
        print("🚨 NGROK_AUTH_TOKEN not set!")
        print("="*60)
        print("\n1. Go to https://ngrok.com and sign up (free)")
        print("2. Get your authtoken from dashboard")
        print("3. Run: set NGROK_AUTH_TOKEN=your_token_here")
        print("4. Run this script again\n")
        return
    
    # Check ngrok
    if not check_ngrok():
        install_ngrok()
    
    # Config ngrok
    print("🔧 Configuring ngrok...")
    subprocess.run(['ngrok', 'config', 'add-authtoken', ngrok_token], check=True)
    
    print("\n" + "="*60)
    print("🚀 Starting Backend + Ngrok...")
    print("="*60)
    print("\n⚠️  IMPORTANT:")
    print("- Backend will run on http://localhost:8000")
    print("- Ngrok will create public URL")
    print("- Copy the https://xxxx.ngrok-free.app URL")
    print("- Update it in frontend\n")
    
    # Install pyngrok
    try:
        from pyngrok import ngrok
    except:
        print("📦 Installing pyngrok...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyngrok'], check=True)
        from pyngrok import ngrok
    
    ngrok.set_auth_token(ngrok_token)
    
    # Start ngrok tunnel
    print("🌐 Starting ngrok tunnel...")
    public_url = ngrok.connect(8000, "http")
    print(f"\n{'='*60}")
    print(f"🎉 PUBLIC URL: {public_url}")
    print(f"{'='*60}\n")
    
    # Update frontend automatically
    frontend_file = os.path.join(os.path.dirname(__file__), '..', 'app', 'src', 'pages', 'BotDashboard.tsx')
    if os.path.exists(frontend_file):
        print(f"📝 Updating frontend API_URL...")
        with open(frontend_file, 'r') as f:
            content = f.read()
        
        # Replace API_URL
        import re
        new_content = re.sub(
            r"const API_URL = '[^']+'",
            f"const API_URL = '{public_url}'",
            content
        )
        
        with open(frontend_file, 'w') as f:
            f.write(new_content)
        print("✅ Frontend updated! Commit and push to deploy.\n")
    
    print("🚀 Starting backend server...")
    print("Press Ctrl+C to stop\n")
    
    try:
        # Run uvicorn
        subprocess.run([
            sys.executable, '-m', 'uvicorn',
            'main:app',
            '--host', '0.0.0.0',
            '--port', '8000',
            '--reload'
        ])
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping...")
        ngrok.disconnect(public_url)
        print("✅ Done!")

if __name__ == "__main__":
    main()
