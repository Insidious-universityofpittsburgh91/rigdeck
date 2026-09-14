# Installs the SCS telemetry plugin that Rig Deck reads from.
#
# The plugin is RenCloud/scs-sdk-plugin: a DLL the game loads at start-up, which mirrors
# its telemetry into shared memory. It sits alongside any other plugins already there
# (SIM Dashboard's, for example) -- the game loads all of them.
#
#   powershell -ExecutionPolicy Bypass -File install_plugin.ps1
#   powershell -ExecutionPolicy Bypass -File install_plugin.ps1 -WhatIf   # dry run

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string[]]$GameDir,
    [string]$Zip
)

$ErrorActionPreference = "Stop"

function Find-Games {
    $found = @()
    $steamRoots = @()

    $steam = Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue
    if ($steam -and $steam.SteamPath) { $steamRoots += ($steam.SteamPath -replace '/', '\') }

    foreach ($root in @($steamRoots)) {
        $vdf = Join-Path $root "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            foreach ($line in (Get-Content $vdf | Select-String '"path"')) {
                if ($line -match '"path"\s+"(.+?)"') {
                    $steamRoots += ($matches[1] -replace '\\\\', '\')
                }
            }
        }
    }

    # Steam reports the same library as both "d:\..." and "D:\...", and -Unique is
    # case-sensitive, so without folding the case the plugin gets installed twice.
    foreach ($root in ($steamRoots | Sort-Object -Unique -CaseSensitive:$false)) {
        foreach ($title in @("Euro Truck Simulator 2", "American Truck Simulator")) {
            $path = Join-Path $root "steamapps\common\$title"
            if (Test-Path $path) { $found += $path }
        }
    }
    return $found | Sort-Object -Unique -CaseSensitive:$false
}

$games = if ($GameDir) { $GameDir } else { Find-Games }
if (-not $games) {
    Write-Host "No ETS2 or ATS installation found. Pass -GameDir '<path to the game folder>'." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "  Games found:" -ForegroundColor Cyan
$games | ForEach-Object { Write-Host "    $_" }

$work = Join-Path $env:TEMP "rigdeck-plugin"
New-Item -ItemType Directory -Force $work | Out-Null

if (-not $Zip) {
    Write-Host ""
    Write-Host "  Fetching the latest scs-sdk-plugin release..." -ForegroundColor Cyan
    $release = Invoke-RestMethod -UseBasicParsing `
        -Uri "https://api.github.com/repos/RenCloud/scs-sdk-plugin/releases/latest" `
        -Headers @{ "User-Agent" = "rigdeck" }
    $asset = $release.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1
    if (-not $asset) { throw "the release has no zip asset" }
    Write-Host "    $($release.tag_name) -- $($asset.name)"
    $Zip = Join-Path $work $asset.name
    Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $Zip
}

$extract = Join-Path $work "extracted"
if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
Expand-Archive -Path $Zip -DestinationPath $extract -Force

$dll = Get-ChildItem -Path $extract -Recurse -Filter "scs-telemetry.dll" |
    Where-Object { $_.FullName -match "x64|win_x64|64" } |
    Select-Object -First 1
if (-not $dll) {
    $dll = Get-ChildItem -Path $extract -Recurse -Filter "scs-telemetry.dll" | Select-Object -First 1
}
if (-not $dll) { throw "scs-telemetry.dll was not found inside the release zip" }

Write-Host ""
Write-Host "  Using $($dll.FullName)" -ForegroundColor Cyan
Write-Host ""

foreach ($game in $games) {
    $plugins = Join-Path $game "bin\win_x64\plugins"
    if ($PSCmdlet.ShouldProcess($plugins, "install scs-telemetry.dll")) {
        New-Item -ItemType Directory -Force $plugins | Out-Null
        Copy-Item $dll.FullName (Join-Path $plugins "scs-telemetry.dll") -Force
        Write-Host "  installed -> $plugins" -ForegroundColor Green
    } else {
        Write-Host "  would install -> $plugins" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  Done. Start the game; Rig Deck picks the telemetry up automatically." -ForegroundColor Green
Write-Host ""
