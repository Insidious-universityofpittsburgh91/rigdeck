# Starts the Rig Deck server.
#
#   .\run.ps1              start the panel server
#   .\run.ps1 -Mock        write fake telemetry instead, to try the panel with the game closed
#   .\run.ps1 -Mock -Game ATS   the same, but in miles, dollars and around Phoenix
#   .\run.ps1 -Bindings    print the vJoy button sheet to bind in the game

param(
    [switch]$Mock,
    [switch]$Bindings,
    [ValidateSet("ETS2", "ATS")]
    [string]$Game = "ETS2",
    [int]$Port
)

$ErrorActionPreference = "Stop"

$python = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "python"
) | Where-Object { $_ -eq "python" -or (Test-Path $_) } | Select-Object -First 1

$server = Join-Path $PSScriptRoot "server"
$argsList = @("-m", "rigdeck")
if ($Mock) { $argsList += @("--mock", "--game", $Game) }
if ($Bindings) { $argsList += "--bindings" }
if ($Port) { $argsList += @("--port", "$Port") }

Push-Location $server
try {
    & $python @argsList
} finally {
    Pop-Location
}
