param(
    [switch]$StartWhatsAppGateway
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Start-DemoTerminal {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Command
    )

    $encodedCommand = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($Command)
    )
    Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $repoRoot `
        -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encodedCommand) `
        -WindowStyle Normal
    Write-Host "Started terminal: $Name"
}

function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $client = New-Object System.Net.Sockets.TcpClient
    $waitHandle = $null
    try {
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        $waitHandle = $connect.AsyncWaitHandle
        if (-not $waitHandle.WaitOne(1000)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($waitHandle) {
            $waitHandle.Close()
        }
        $client.Close()
    }
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker CLI was not found. Install/start Docker Desktop and try again."
}
& docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose is unavailable. Install/start Docker Desktop and try again."
}

$python = $null
foreach ($candidate in @(
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    (Join-Path $repoRoot "venv\Scripts\python.exe")
)) {
    if (Test-Path -LiteralPath $candidate) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Create a virtual environment and install requirements.txt."
    }
    $python = $pythonCommand.Source
}

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
    throw "npm.cmd was not found. Install Node.js and npm before launching the dashboard."
}
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "models\toy_yolo.onnx"))) {
    throw "Missing models\toy_yolo.onnx. Restore the demo ONNX model before launching."
}
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "models\labels.txt"))) {
    throw "Missing models\labels.txt."
}

$rootLiteral = "'" + $repoRoot.Replace("'", "''") + "'"
$pythonLiteral = "'" + $python.Replace("'", "''") + "'"
$npmLiteral = "'" + $npm.Source.Replace("'", "''") + "'"

Start-DemoTerminal -Name "Mosquitto MQTT broker" -Command `
    "Set-Location -LiteralPath $rootLiteral; docker compose up"

$brokerReady = $false
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    if (Test-TcpPort -HostName "127.0.0.1" -Port 1883) {
        $brokerReady = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $brokerReady) {
    throw "Mosquitto did not become available on localhost:1883 within 60 seconds. Check the broker terminal."
}

Start-DemoTerminal -Name "FastAPI backend" -Command `
    "Set-Location -LiteralPath $rootLiteral; & $pythonLiteral server.py"
Start-DemoTerminal -Name "ONNX edge simulator" -Command `
    "Set-Location -LiteralPath $rootLiteral; & $pythonLiteral edge_sim.py --bus-id BEST-104 --route R-12 --broker mqtt://localhost:1883 --fps 5 --imu-file .\data\imu_samples.json --model .\models\toy_yolo.onnx --labels .\models\labels.txt --offline-probability 0"
Start-DemoTerminal -Name "React MapLibre dashboard" -Command `
    "Set-Location -LiteralPath $rootLiteral; & $npmLiteral --prefix .\frontend run dev"

if ($StartWhatsAppGateway) {
    Start-DemoTerminal -Name "Optional WhatsApp gateway" -Command `
        "Set-Location -LiteralPath $rootLiteral; node .\whatsapp_bot.js"
}

Write-Host ""
Write-Host "Local demo launched. Dashboard: http://localhost:5173"
Write-Host "Backend API: http://localhost:8000"
Write-Host "Stop each terminal with Ctrl+C; stop Mosquitto with docker compose down."
