Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
    try {
      Stop-Process -Id $procId -Force -ErrorAction Stop
    } catch {
      # ignore
    }
  }
}

Stop-PortListener -Port 8011
Start-Sleep -Seconds 2

$start = Join-Path $root "run_8011_waitress.ps1"
if (-not (Test-Path -LiteralPath $start)) {
  throw "Missing start script: $start"
}

# Start in background (detached)
Start-Process -WindowStyle Hidden -FilePath "powershell.exe" -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $start
)

