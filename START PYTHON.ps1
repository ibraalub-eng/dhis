# Starts the HEALTH-ai FastAPI Windows service (auto-restart, starts on boot).
# The app listens on http://127.0.0.1:9090; the service depends on postgresql17,
# so the database is guaranteed to be up first.
$svc = Get-Service HealthAI -ErrorAction SilentlyContinue
if (-not $svc) { Write-Error "Service 'HealthAI' not found. Register it with nssm first."; exit 1 }
if ($svc.Status -ne 'Running') { Start-Service HealthAI }
$svc.WaitForStatus('Running', '00:00:30')
Write-Host "HEALTH-ai is running on http://127.0.0.1:9090 (service: $($svc.Status))"
