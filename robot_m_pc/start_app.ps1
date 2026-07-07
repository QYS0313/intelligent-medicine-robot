$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
$pythonPath = Join-Path $projectDir ".venv\Scripts\python.exe"
$runPath = Join-Path $projectDir "run.py"
$envPath = Join-Path $projectDir ".env"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host "Python virtual environment was not found: $pythonPath" -ForegroundColor Red
    Write-Host "Create .venv and install requirements first."
    Read-Host "Press Enter to exit"
    exit 1
}

$appHost = "127.0.0.1"
$appPort = "18080"
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*APP_HOST\s*=\s*(.+?)\s*$') { $appHost = $Matches[1] }
        if ($line -match '^\s*APP_PORT\s*=\s*(\d+)\s*$') { $appPort = $Matches[1] }
    }
}
if ($appHost -in @("0.0.0.0", "::")) { $appHost = "127.0.0.1" }
$appUrl = "http://${appHost}:${appPort}"

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri "$appUrl/api/status" -UseBasicParsing -TimeoutSec 1
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (-not (Test-AppReady)) {
    $escapedProject = $projectDir.Replace("'", "''")
    $escapedPython = $pythonPath.Replace("'", "''")
    $escapedRun = $runPath.Replace("'", "''")
    $serverCommand = @"
`$Host.UI.RawUI.WindowTitle = 'Qihuang Robot Service'
Set-Location -LiteralPath '$escapedProject'
Write-Host 'Starting Qihuang consultation service...' -ForegroundColor Green
& '$escapedPython' '$escapedRun'
"@
    Start-Process powershell.exe -WorkingDirectory $projectDir -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $serverCommand
    )

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-AppReady) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        Write-Host "The service did not start within 30 seconds. Check the server terminal." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

Start-Process $appUrl
