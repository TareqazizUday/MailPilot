param(
  # Run even when deploy_check reports FAIL lines (not recommended).
  [switch]$SkipCheck,
  # Leave out Stripe/PayPal checks (e.g. PayPal live not used).
  [switch]$SkipBilling,
  # Only prepare (deps, migrate, static, check); restart the server yourself.
  [switch]$NoRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$envFile = Join-Path $root ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
  throw "Missing .env. Copy .env.production.example to .env and fill it in first."
}
if (-not (Select-String -LiteralPath $envFile -Pattern '^\s*MAILPILOT_ENV\s*=\s*production\s*$' -Quiet)) {
  throw ".env must contain MAILPILOT_ENV=production on the live server."
}

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
  $py = Join-Path $root "venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $py)) {
  throw "Python venv not found. Run: python -m venv .venv"
}

function Invoke-Step {
  param([string]$Title, [string[]]$Arguments)
  Write-Host "==> $Title" -ForegroundColor Cyan
  & $py @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Title failed (exit $LASTEXITCODE)." }
}

Invoke-Step "Install requirements" @("-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check")
Invoke-Step "Apply database migrations" @("manage.py", "migrate", "--noinput")
Invoke-Step "Collect static files" @("manage.py", "collectstatic", "--noinput")

$checkArgs = @("manage.py", "deploy_check")
if ($SkipBilling) { $checkArgs += "--skip-billing" }
Write-Host "==> Deploy check" -ForegroundColor Cyan
& $py @checkArgs
if ($LASTEXITCODE -ne 0) {
  if ($SkipCheck) {
    Write-Host "deploy_check reported failures; continuing because -SkipCheck was given." -ForegroundColor Yellow
  } else {
    throw "deploy_check failed. Fix the FAIL lines above (or re-run with -SkipCheck)."
  }
}

if ($NoRestart) {
  Write-Host "Prepared. Restart the web server to load the new code." -ForegroundColor Green
  exit 0
}

$restart = Join-Path $root "restart_8011.ps1"
Write-Host "==> Restart (Waitress on 127.0.0.1:8011)" -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $restart
if ($LASTEXITCODE -ne 0) { throw "Restart failed (exit $LASTEXITCODE)." }

Write-Host "Deployed. Check https://mailpilots.net/healthz" -ForegroundColor Green
