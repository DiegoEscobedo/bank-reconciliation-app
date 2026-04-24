# NSSM reset + clean setup for BankReconciliationApp
# Run in PowerShell as Administrator on the server.

$ErrorActionPreference = "Stop"

# 1) Variables
$N = "C:\tools\nssm\nssm.exe"
$S = "BankReconciliationApp"
$APP = "C:\apps\bank-reconciliation-app"
$BAT = "$APP\start_service.bat"

Write-Host "[1/9] Validating paths..."
if (!(Test-Path $N)) { throw "NSSM not found at: $N" }
if (!(Test-Path $APP)) { throw "App folder not found at: $APP" }

Write-Host "[2/9] Updating repository..."
Set-Location $APP
git pull origin main

Write-Host "[3/9] Creating/updating start_service.bat..."
@"
@echo off
set APP_DIR=C:\apps\bank-reconciliation-app
set PY=%APP_DIR%\.venv_clean\Scripts\python.exe
cd /d %APP_DIR%
"%PY%" -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --browser.gatherUsageStats false
"@ | Set-Content -Encoding ASCII $BAT

Write-Host "[4/9] Preparing logs..."
New-Item -ItemType Directory -Path "$APP\logs" -Force | Out-Null
Remove-Item "$APP\logs\service_out.log" -Force -ErrorAction SilentlyContinue
Remove-Item "$APP\logs\service_err.log" -Force -ErrorAction SilentlyContinue

Write-Host "[5/9] Stopping and removing existing service (if any)..."
& $N stop $S 2>$null
Start-Sleep -Seconds 2
& $N remove $S confirm 2>$null

Write-Host "[6/9] Installing service via BAT..."
& $N install $S "C:\Windows\System32\cmd.exe" "/c $BAT"
& $N set $S AppDirectory $APP
& $N set $S Start SERVICE_AUTO_START
& $N set $S AppStdout "$APP\logs\service_out.log"
& $N set $S AppStderr "$APP\logs\service_err.log"

Write-Host "[7/9] Starting service..."
& $N start $S
Start-Sleep -Seconds 3

Write-Host "[8/9] Validation..."
Get-Service $S
try {
    Get-NetTCPConnection -LocalPort 8501 -State Listen
} catch {
    Write-Warning "Port 8501 is not listening yet. Check logs below."
}

Write-Host "[9/9] Effective NSSM config and latest logs..."
& $N get $S Application
& $N get $S AppParameters
& $N get $S AppDirectory

Write-Host "--- service_err.log (tail 80) ---"
if (Test-Path "$APP\logs\service_err.log") {
    Get-Content "$APP\logs\service_err.log" -Tail 80
} else {
    Write-Host "No error log file yet."
}

Write-Host "--- service_out.log (tail 80) ---"
if (Test-Path "$APP\logs\service_out.log") {
    Get-Content "$APP\logs\service_out.log" -Tail 80
} else {
    Write-Host "No output log file yet."
}

Write-Host "Done."
