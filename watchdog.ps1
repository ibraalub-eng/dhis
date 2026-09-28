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

# --- 2b. Code-drift check: is the running process OLDER than the repo code? ---
# The service runs uvicorn straight from this working tree with no auto-reload.
# After a git pull / commit the running process keeps serving the OLD code
# (endpoints added later simply 404 — this bit the never-reported button).
# Fix: find the live python.exe launched by NSSM from the repo venv and compare
# its start time against the newest mtime among app/**/*.py. Newer code ->
# restart the service once so it loads the new build. A state file prevents
# restart loops when the process time itself is unreadable.
$driftStateFile = Join-Path $root "logs\.code_drift_restarted"
try {
    $repoPy   = Join-Path $root ".venv\Scripts\python.exe"
    $liveProc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.ExecutablePath -eq $repoPy } |
                Sort-Object CreationDate | Select-Object -First 1

    if ($liveProc) {
        # Newest Python source file under app/ = the code that SHOULD be serving.
        $newestCode = Get-ChildItem -Path (Join-Path $root "app") -Recurse -Filter *.py -ErrorAction SilentlyContinue |
                      Sort-Object LastWriteTime | Select-Object -Last 1
        $newestStamp = if ($newestCode) { $newestCode.LastWriteTimeUtc } else { $null }
        $procStamp   = $liveProc.CreationDate.ToUniversalTime()

        if ($newestStamp -and $procStamp -and ($newestStamp -gt $procStamp.AddMinutes(-1))) {
            $skip = (Test-Path $driftStateFile) -and
                    ((Get-Date) - (Get-Item $driftStateFile).LastWriteTime).TotalMinutes -lt 15
            if ($skip) {
                Write-Log "DRIFT: code newer than process but restart already attempted <15m ago - skipping"
            } else {
                Write-Log ("DRIFT: code file {0} ({1}) is newer than live process start ({2}) -> restarting HealthAI" -f `
                    $newestCode.Name, $newestStamp.ToString('HH:mm:ss'), $procStamp.ToString('HH:mm:ss'))
                Set-Content -Path $driftStateFile -Value (Get-Date -Format o) -ErrorAction SilentlyContinue
                Restart-Service HealthAI -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 12
                if (Test-AppHealth) { Write-Log "DRIFT: restart done - /health OK, service now on current code" }
                else { Write-Log "DRIFT: restart done but /health failing - manual attention needed" }
            }
        } else {
            Write-Log "DRIFT: process is current (started after newest code change)"
            Remove-Item $driftStateFile -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Log "DRIFT: no live venv python process found - skipping version check"
    }
} catch {
    Write-Log "DRIFT: check failed non-fatally: $($_.Exception.Message)"
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
