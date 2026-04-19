Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = Join-Path $root "venv\\Scripts\\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
  throw "venv python not found at: $py"
}

& $py -m waitress --listen=0.0.0.0:8011 mailpilot.wsgi:application

