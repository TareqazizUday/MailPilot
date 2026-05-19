# One-time (per machine): allow URL Rewrite to set forwarded headers for Django behind HTTPS.
# Run in elevated PowerShell:  powershell -ExecutionPolicy Bypass -File .\configure_iis_rewrite_vars.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module WebAdministration -ErrorAction Stop

$vars = @("HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_HOST")
foreach ($name in $vars) {
  $existing = Get-WebConfigurationProperty -pspath "MACHINE/WEBROOT" -filter "system.webServer/rewrite/allowedServerVariables" -name "." |
    Select-Object -ExpandProperty Collection |
    Where-Object { $_.name -eq $name }
  if (-not $existing) {
    Add-WebConfigurationProperty -pspath "MACHINE/WEBROOT" -filter "system.webServer/rewrite/allowedServerVariables" -name "." -value @{ name = $name }
    Write-Host "Allowed server variable: $name"
  } else {
    Write-Host "Already allowed: $name"
  }
}

Write-Host "Done. Recycle the IIS site if you changed web.config serverVariables." -ForegroundColor Green
