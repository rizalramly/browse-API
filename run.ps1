# run.ps1 — one-shot launcher for gen-api.
#
#   .\run.ps1           start (or update) the whole stack, wait until healthy
#   .\run.ps1 -Down     stop the stack (data volumes are kept)
#   .\run.ps1 -Reset    stop the stack AND wipe data volumes (keys, usage log)
#
param(
    [switch]$Down,
    [switch]$Reset
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Down) {
    docker compose down
    exit $LASTEXITCODE
}
if ($Reset) {
    docker compose down -v
    exit $LASTEXITCODE
}

# 1. Docker must be up
try {
    docker info --format "{{.ServerVersion}}" | Out-Null
} catch {
    Write-Host "Docker is not running. Start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

# 2. .env: create from the example on first run, with a real SearXNG secret
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    $secret = -join ((1..48) | ForEach-Object { "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".ToCharArray() | Get-Random })
    (Get-Content ".env") -replace "^SEARXNG_SECRET=.*$", "SEARXNG_SECRET=$secret" |
        Set-Content -Encoding utf8 ".env"
    Write-Host "Created .env from .env.example (SEARXNG_SECRET generated)." -ForegroundColor Yellow
}

# 3. Build + start everything
Write-Host "Starting gen-api stack (api + redis + postgres + searxng)..." -ForegroundColor Cyan
docker compose up --build -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 4. Wait for the API and its dependencies to be healthy
$healthy = $false
foreach ($attempt in 1..30) {
    Start-Sleep -Seconds 3
    try {
        $deps = Invoke-RestMethod "http://localhost:8000/health/deps" -TimeoutSec 5
        if ($deps.status -eq "ok") { $healthy = $true; break }
        Write-Host "  waiting... ($($deps | ConvertTo-Json -Compress))"
    } catch {
        Write-Host "  waiting for API to come up ($attempt/30)..."
    }
}
if (-not $healthy) {
    Write-Host "Stack did not become healthy. Inspect with: docker compose logs api" -ForegroundColor Red
    exit 1
}

# 5. Make sure at least one API key exists; create a default one if not
$keyCount = (docker compose exec -T postgres psql -U gen -d gen -t -A -c "SELECT count(*) FROM api_keys WHERE active;").Trim()
if ($keyCount -eq "0") {
    $newKey = (docker compose exec -T api python -m app.cli create-key --name default) | Select-Object -Last 1
    Write-Host ""
    Write-Host "Created API key 'default' (10000 credits) - store it somewhere safe:" -ForegroundColor Yellow
    Write-Host "  $newKey" -ForegroundColor Green
}

Write-Host ""
Write-Host "gen-api is up." -ForegroundColor Green
Write-Host "  API + docs   http://localhost:8000/docs"
Write-Host "  Health       http://localhost:8000/health/deps"
Write-Host "  Metrics      http://localhost:8000/metrics"
Write-Host "  SearXNG UI   http://localhost:8081"
Write-Host ""
Write-Host "Try it:"
Write-Host '  curl -X POST http://localhost:8000/search -H "X-API-KEY: <key>" -H "Content-Type: application/json" -d "{\"q\":\"hello world\"}"'
Write-Host ""
Write-Host "More keys:     docker compose exec api python -m app.cli create-key --name <consumer>"
Write-Host "Stop:          .\run.ps1 -Down      (keeps data)"
Write-Host "Full reset:    .\run.ps1 -Reset     (wipes keys + usage log)"
