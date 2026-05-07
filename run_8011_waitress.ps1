Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Prefer .venv (common on this machine); fall back to venv.
$py = Join-Path $root ".venv\\Scripts\\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
  $py = Join-Path $root "venv\\Scripts\\python.exe"
}
if (-not (Test-Path -LiteralPath $py)) {
  throw "Python not found. Create a venv at .venv or venv under: $root"
}

& $py -m waitress --listen=0.0.0.0:8011 mailpilot.wsgi:application

