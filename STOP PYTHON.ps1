# Stops the HEALTH-ai FastAPI Windows service (app listens on port 9090) gracefully.
# Do NOT taskkill uvicorn directly — NSSM auto-restarts it. Stop the service instead.
$svc = Get-Service HealthAI -ErrorAction SilentlyContinue
if (-not $svc) { Write-Error "Service 'HealthAI' not found."; exit 1 }
if ($svc.Status -ne 'Stopped') { Stop-Service HealthAI -Force }
$svc.WaitForStatus('Stopped', '00:00:30')
Write-Host "HEALTH-ai service stopped."
