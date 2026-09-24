# HEALTH-ai Watchdog — keeps app + tunnels alive, logs status
# Registered as scheduled task "HEALTH-ai Watchdog" (every 5 minutes, SYSTEM)
$ErrorActionPreference = "Continue"
$root    = "C:\Users\Administrator\Documents\GitHub\dhis"
$log     = Join-Path $root "logs\watchdog.log"
$urlFile = Join-Path $root "logs\CURRENT-PUBLIC-URL.txt"
$cf      = "C:\ProgramData\chocolatey\bin\cloudflared.exe"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $log -Value $line
}

function Test-AppHealth {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:9090/health" -UseBasicParsing -TimeoutSec 10
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

# --- 1. App service ---
$svc = Get-Service HealthAI -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne "Running") {
    Write-Log "APP: service HealthAI is $($svc.Status) -> starting"
    Start-Service HealthAI -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 10
    Write-Log "APP: service now $((Get-Service HealthAI).Status)"
}

# --- 2. App HTTP health (restart once if hung) ---
if (-not (Test-AppHealth)) {
    Write-Log "APP: /health NOT responding -> restarting HealthAI"
    Restart-Service HealthAI -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 12
    if (Test-AppHealth) { Write-Log "APP: /health OK after restart" }
    else { Write-Log "APP: /health STILL failing after restart - manual attention needed" }
} else {
    Write-Log "APP: /health OK"
}

# --- 3. Permanent tunnel service ---
$cfSvc = Get-Service cloudflaredAI -ErrorAction SilentlyContinue
if ($cfSvc -and $cfSvc.Status -ne "Running") {
    Write-Log "TUNNEL: cloudflaredAI is $($cfSvc.Status) -> starting"
    Start-Service cloudflaredAI -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 8
    Write-Log "TUNNEL: cloudflaredAI now $((Get-Service cloudflaredAI).Status)"
} elseif ($cfSvc) {
    Write-Log "TUNNEL: cloudflaredAI OK (permanent)"
}

# --- 4. Quick tunnel process ---
$quick = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like "*--url*" }
if (-not $quick) {
    Write-Log "QUICKTUNNEL: not running -> starting new quick tunnel"
    Remove-Item (Join-Path $root "logs\cloudflared-quick.log") -Force -ErrorAction SilentlyContinue
    Start-Process $cf -ArgumentList "tunnel","--url","http://127.0.0.1:9090","--logfile","C:\Users\Administrator\Documents\GitHub\dhis\logs\cloudflared-quick.log" -WindowStyle Hidden
    Start-Sleep -Seconds 14
    $u = Select-String -Path (Join-Path $root "logs\cloudflared-quick.log") -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -AllMatches -ErrorAction SilentlyContinue |
         Select-Object -Last 1
    if ($u -and $u.Matches.Count -gt 0) {
        $url = $u.Matches[0].Value
        Set-Content -Path $urlFile -Value $url
        Write-Log "QUICKTUNNEL: started -> $url"
    } else {
        Write-Log "QUICKTUNNEL: started but URL not found in log yet"
    }
} else {
    $url = if (Test-Path $urlFile) { Get-Content $urlFile -TotalCount 1 } else { "(unknown)" }
    Write-Log "QUICKTUNNEL: OK ($url)"
}

Write-Log "---- watchdog run complete ----"
