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

# Bind loopback only; IIS (web.config) reverse-proxies to 127.0.0.1:8011.
& $py -m waitress --listen=127.0.0.1:8011 mailpilot.wsgi:application

