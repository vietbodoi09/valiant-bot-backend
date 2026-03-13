# Deploy to Fly.io - Simple PowerShell script

# 1. Install fly CLI if not exists
if (!(Get-Command fly -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Fly CLI..." -ForegroundColor Yellow
    iwr https://fly.io/install.ps1 -useb | iex
    $env:PATH += ";$env:USERPROFILE\.fly\bin"
}

# 2. Login (opens browser)
Write-Host "`nLogging in... (browser will open)" -ForegroundColor Green
fly auth login

# 3. Create unique app name
$timestamp = Get-Date -Format "HHmmss"
$appName = "valiant-bot-$timestamp"

Write-Host "`nCreating app: $appName" -ForegroundColor Cyan
fly apps create $appName

# 4. Deploy
Write-Host "`nDeploying..." -ForegroundColor Green
fly deploy --app $appName --region sin

# 5. Show status
Write-Host "`n==================================" -ForegroundColor Green
Write-Host "DEPLOY SUCCESS!" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host "URL: https://$appName.fly.dev" -ForegroundColor Yellow
Write-Host "`nUpdate frontend API_URL with this URL"
