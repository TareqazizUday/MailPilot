# One-time IIS setup: site + bindings for https://mailpilot.tedbotai.com/
# Run elevated:  powershell -ExecutionPolicy Bypass -File .\setup_iis_mailpilot_site.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
  $self = $MyInvocation.MyCommand.Path
  Write-Host "Requesting Administrator approval for IIS setup..." -ForegroundColor Yellow
  $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$self`""
  ) -Wait -PassThru
  if ($proc) { exit $proc.ExitCode }
  exit 1
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$siteName = "MailPilot"
$hostName = "mailpilot.tedbotai.com"
$appPool = "MailPilot"

Import-Module WebAdministration -ErrorAction Stop

# URL Rewrite: allow forwarded headers (required by web.config serverVariables).
$vars = @("HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_HOST")
foreach ($name in $vars) {
  $existing = Get-WebConfigurationProperty -pspath "MACHINE/WEBROOT" -filter "system.webServer/rewrite/allowedServerVariables" -name "." |
    Select-Object -ExpandProperty Collection |
    Where-Object { $_.name -eq $name }
  if (-not $existing) {
    Add-WebConfigurationProperty -pspath "MACHINE/WEBROOT" -filter "system.webServer/rewrite/allowedServerVariables" -name "." -value @{ name = $name }
    Write-Host "Allowed server variable: $name"
  }
}

if (-not (Test-Path "IIS:\AppPools\$appPool")) {
  New-WebAppPool -Name $appPool | Out-Null
  Set-ItemProperty "IIS:\AppPools\$appPool" -Name managedRuntimeVersion -Value ""
  Write-Host "Created app pool: $appPool"
}

$existing = Get-Website -Name $siteName -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Updating existing site: $siteName"
  Set-ItemProperty "IIS:\Sites\$siteName" -Name physicalPath -Value $root
  Set-ItemProperty "IIS:\Sites\$siteName" -Name applicationPool -Value $appPool
} else {
  New-Website -Name $siteName -PhysicalPath $root -ApplicationPool $appPool -Port 80 -HostHeader $hostName | Out-Null
  Write-Host "Created site: $siteName -> $root"
}

# Ensure HTTP binding for the hostname.
$httpBinding = "*:80:$hostName"
$site = Get-Website -Name $siteName
$hasHttp = $false
foreach ($b in $site.bindings.Collection) {
  if ($b.protocol -eq "http" -and $b.bindingInformation -eq $httpBinding) { $hasHttp = $true }
}
if (-not $hasHttp) {
  New-WebBinding -Name $siteName -Protocol http -Port 80 -HostHeader $hostName | Out-Null
  Write-Host "Added HTTP binding: $httpBinding"
}

# HTTPS binding when a matching certificate is installed.
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
  $_.Subject -match "tedbotai|mailpilot" -or
  ($_.DnsNameList -and ($_.DnsNameList.Unicode -contains $hostName -or $_.DnsNameList.Unicode -contains "*.tedbotai.com"))
} | Sort-Object NotAfter -Descending | Select-Object -First 1

if ($cert) {
  $httpsBinding = "*:443:$hostName"
  $hasHttps = $false
  foreach ($b in (Get-Website -Name $siteName).bindings.Collection) {
    if ($b.protocol -eq "https" -and $b.bindingInformation -eq $httpsBinding) { $hasHttps = $true }
  }
  if (-not $hasHttps) {
    New-WebBinding -Name $siteName -Protocol https -Port 443 -HostHeader $hostName -SslFlags 1 | Out-Null
    Push-Location "IIS:\SslBindings\0.0.0.0!443!$hostName"
    try {
      Get-Item . | Remove-Item -ErrorAction SilentlyContinue
    } catch {}
    Pop-Location
    New-Item "IIS:\SslBindings\0.0.0.0!443!$hostName" -Value $cert | Out-Null
    Write-Host "Added HTTPS binding with cert: $($cert.Subject)"
  }
} else {
  Write-Host "No SSL cert found for $hostName - HTTP only. Install a cert (e.g. win-acme) for HTTPS." -ForegroundColor Yellow
}

Restart-WebAppPool -Name $appPool
Write-Host ('IIS site ready: https://{0}/ (proxy to 127.0.0.1:8011 via web.config)' -f $hostName) -ForegroundColor Green
Write-Host 'Start the app: powershell -ExecutionPolicy Bypass -File .\restart_8011.ps1' -ForegroundColor Green
