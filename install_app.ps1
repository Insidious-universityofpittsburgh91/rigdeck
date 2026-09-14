<#
    Turns Rig Deck into an ordinary Windows app: an icon in the Start menu and on the
    desktop, and a tray icon while it runs. No console window anywhere.

        .\install_app.ps1              install
        .\install_app.ps1 -Uninstall   remove the shortcuts

    It does NOT add itself to Windows startup, and there is no switch to make it. Start
    it when you sit down to drive; quit it from the tray when you are done.

    Nothing is copied anywhere and no installer runs -- the shortcuts point straight at
    this folder, so `git pull` is enough to update.
#>

param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$server = Join-Path $PSScriptRoot 'server'
$launcher = Join-Path $server 'rigdeck_tray.py'
$icon = Join-Path $PSScriptRoot 'RigDeck.ico'

$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Rig Deck.lnk'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Rig Deck.lnk'

# -- uninstall -------------------------------------------------------------------
if ($Uninstall) {
    foreach ($link in @($desktop, $startMenu)) {
        if (Test-Path $link) { Remove-Item $link -Force; Write-Host "  removed $link" }
    }
    # Nothing here writes this any more, but an earlier build could have, so it is worth
    # sweeping up.
    $run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if ((Get-ItemProperty $run -ErrorAction SilentlyContinue).RigDeck) {
        Remove-ItemProperty $run -Name RigDeck
        Write-Host '  removed a leftover startup entry'
    }
    Write-Host "`n  Rig Deck is unhooked. The folder itself is untouched.`n"
    return
}

# -- python ----------------------------------------------------------------------
# pythonw runs without a console window; python.exe would leave a black box open.
$python = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $python) {
    $found = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    # The Store's stub is a launcher, not an interpreter, and it opens a console.
    if ($found -and $found -notlike '*WindowsApps*') { $python = $found }
}
if (-not $python) { throw 'No pythonw.exe found. Install Python 3.13 or newer.' }
Write-Host "  python  $python"

# -- the icon --------------------------------------------------------------------
if (-not (Test-Path $icon)) {
    Write-Host '  drawing the icon'
    & $python.Replace('pythonw.exe', 'python.exe') (Join-Path $server 'rigdeck_tray.py') --write-ico $icon
    if (-not (Test-Path $icon)) { throw 'the icon was not written' }
}

# -- shortcuts -------------------------------------------------------------------
$shell = New-Object -ComObject WScript.Shell
foreach ($link in @($desktop, $startMenu)) {
    $sc = $shell.CreateShortcut($link)
    $sc.TargetPath = $python
    $sc.Arguments = "`"$launcher`""
    $sc.WorkingDirectory = $server
    $sc.IconLocation = "$icon,0"
    $sc.Description = 'Rig Deck -- dashboard server for ETS2 and ATS'
    $sc.Save()
    Write-Host "  shortcut $link"
}

Write-Host ""
Write-Host "  Done. Open Rig Deck from the Start menu -- it sits in the tray by the clock."
Write-Host "  Right-click that icon to pair a tablet or see the button sheet."
Write-Host ""
