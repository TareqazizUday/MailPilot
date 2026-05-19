Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Re-launch elevated so we can stop a listener owned by another user/service.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
  $self = $MyInvocation.MyCommand.Path
  Write-Host "Requesting Administrator approval to restart MailPilot on port 8011..." -ForegroundColor Yellow
  $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$self`""
  ) -Wait -PassThru
  if ($proc) { exit $proc.ExitCode }
  exit 1
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Stop-PortListener {
  param([int]$Port)
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
  } catch {
    return
  }

  $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($procId in $pids) {
    if (-not $procId) { continue }
    Write-Host "Stopping PID $procId on port $Port"
    Stop-Process -Id $procId -Force -ErrorAction Stop
  }
}

function Test-MailPilotHealth {
  param([string]$BaseUrl = "http://127.0.0.1:8011")
  try {
    $r = Invoke-WebRequest -Uri "$BaseUrl/healthz" -UseBasicParsing -TimeoutSec 8
    return ($r.StatusCode -eq 200 -and $r.Content -match '"ok"\s*:\s*true')
  } catch {
    return $false
  }
}

Stop-PortListener -Port 8011
Start-Sleep -Seconds 2

$start = Join-Path $root "run_8011_waitress.ps1"
if (-not (Test-Path -LiteralPath $start)) {
  throw "Missing start script: $start"
}

Start-Process -WindowStyle Hidden -FilePath "powershell.exe" -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $start
)

$deadline = (Get-Date).AddSeconds(25)
$ok = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  if (Test-MailPilotHealth) {
    $ok = $true
    break
  }
}

if (-not $ok) {
  throw "MailPilot did not become healthy at http://127.0.0.1:8011/healthz within 25s."
}

Write-Host "MailPilot is running on http://127.0.0.1:8011 (IIS -> https://mailpilot.tedbotai.com/)" -ForegroundColor Green
