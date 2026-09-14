<#
    Writes Rig Deck's thirty-two buttons into the game's own controls.sii.

    This is the script behind "2 - POVEZI TIPKE U IGRI.bat", and the installer calls it
    too. It is separate from the installer because it is the one step that cannot be done
    on a brand-new PC: the game has to have been started once with vJoy already installed,
    so that it has a controller slot for it.

    The game must be closed. It keeps the profile in memory and writes it back out when it
    exits, so anything written underneath a running game is thrown away.
#>

param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$root   = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'runtime\python.exe'
$server = Join-Path $root 'server'

if (-not $Quiet) {
    Write-Host ""
    Write-Host "  RIG DECK -- binding the buttons in the game" -ForegroundColor White
    Write-Host ""
    Write-Host "  Every panel button gets its own vJoy button in your profile, and the file" -ForegroundColor DarkGray
    Write-Host "  as it was is kept beside it as controls.sii.rigdeck-backup." -ForegroundColor DarkGray
    Write-Host ""
}

Push-Location $server
try {
    & $python 'bindwrite.py' --write --claim
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if (-not $Quiet) {
    Write-Host ""
    if ($code -eq 0) {
        Write-Host "  Done. Start the game and try the horn from the tablet." -ForegroundColor Green
    } elseif ($code -eq 2) {
        Write-Host "  Close the game first, then run this again." -ForegroundColor Yellow
    } else {
        Write-Host "  Nothing was written. The usual reason on a new PC:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "    1. start the game" -ForegroundColor Yellow
        Write-Host "    2. Options -> Controls, and pick vJoy Device in the list of controllers" -ForegroundColor Yellow
        Write-Host "    3. quit the game" -ForegroundColor Yellow
        Write-Host "    4. run this again" -ForegroundColor Yellow
    }
    Write-Host ""
}

exit $code
