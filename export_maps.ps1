# Builds the panel's map out of your own game files.
#
# There is no download here and no community map image: the road network, the city
# names and the ferry lines all come from the .scs archives on this PC, including the
# map mods your profile has enabled. That is the only way a ProMods route can match
# what you actually see through the windscreen.
#
# Which mods are active, and in what order, is read from each game's own game.log.txt,
# so start the game once after changing mods and then re-run this.
#
# A standalone map mod (Hungary, and others) adds its own map next to the base one, often
# on the very same coordinates. Pass -Map to export just that one, otherwise every map
# found is merged and they end up drawn on top of each other. The exporter prints the
# names it found on each run.
#
#   powershell -ExecutionPolicy Bypass -File export_maps.ps1
#   powershell -ExecutionPolicy Bypass -File export_maps.ps1 -Game ETS2
#   powershell -ExecutionPolicy Bypass -File export_maps.ps1 -Game ETS2 -Map hungary
#   powershell -ExecutionPolicy Bypass -File export_maps.ps1 -NoMods    # base game only
#   powershell -ExecutionPolicy Bypass -File export_maps.ps1 -ListMaps  # JSON, for the tray menu

[CmdletBinding()]
param(
    [ValidateSet("ETS2", "ATS", "Both")]
    [string]$Game = "Both",
    [string]$Map,
    [switch]$NoMods,
    [switch]$Preview,
    [switch]$ListMaps
)

$ErrorActionPreference = "Stop"
$tools = Join-Path $PSScriptRoot "tools"
$exe = Join-Path $tools "mapexport\bin\MapExport.exe"

$GAMES = @{
    ETS2 = @{ Title = "Euro Truck Simulator 2"; Out = "ets2" }
    ATS  = @{ Title = "American Truck Simulator"; Out = "ats" }
}

function Get-MSBuild {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { return $null }
    & $vswhere -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" |
        Select-Object -First 1
}

function Get-Package($id, $version, $destination) {
    $lower = $id.ToLower()
    $cache = Join-Path $tools "nupkg"
    New-Item -ItemType Directory -Force $cache | Out-Null
    $zip = Join-Path $cache "$id.$version.zip"
    if (-not (Test-Path $zip)) {
        Invoke-WebRequest -UseBasicParsing -OutFile $zip `
            -Uri "https://api.nuget.org/v3-flatcontainer/$lower/$version/$lower.$version.nupkg"
    }
    if (-not (Test-Path $destination)) { Expand-Archive $zip -DestinationPath $destination -Force }
}

function Build-Exporter {
    $msbuild = Get-MSBuild
    if (-not $msbuild) {
        throw "MSBuild was not found. Install Visual Studio Build Tools with the MSBuild component."
    }

    $tsmap = Join-Path $tools "ts-map"
    if (-not (Test-Path $tsmap)) {
        Write-Host "  cloning ts-map (the map reader)..." -ForegroundColor Cyan
        git clone --depth 1 https://github.com/dariowouters/ts-map.git $tsmap
    }

    # ts-map is a .NET Framework project and this machine has no targeting pack, so the
    # reference assemblies come from NuGet and are handed to MSBuild directly.
    Get-Package "Newtonsoft.Json" "13.0.1" (Join-Path $tsmap "packages\Newtonsoft.Json.13.0.1")
    Get-Package "Microsoft.NETFramework.ReferenceAssemblies.net472" "1.0.3" (Join-Path $tools "refs\net472")
    $refs = Join-Path $tools "refs\net472\build\.NETFramework\v4.7.2"

    Write-Host "  building..." -ForegroundColor Cyan
    foreach ($project in @((Join-Path $tsmap "TsMap.sln"), (Join-Path $tools "mapexport\MapExport.csproj"))) {
        & $msbuild $project /p:Configuration=Release /p:Platform=x64 `
            /p:FrameworkPathOverride=$refs /v:quiet /nologo
        if ($LASTEXITCODE -ne 0) { throw "build failed: $project" }
    }
}

# The game logs every mod it mounts, newest session last, in priority order.
function Get-ActiveMods($title) {
    $log = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "$title\game.log.txt"
    if (-not (Test-Path $log)) {
        Write-Host "  no game.log.txt -- start $title once so it records its mod list" -ForegroundColor Yellow
        return @()
    }

    $lines = Get-Content $log
    $last = ($lines | Select-String "\[mods\] Active \d+ mods" | Select-Object -Last 1)
    if (-not $last) { return @() }

    $names = @()
    foreach ($line in $lines[$last.LineNumber..($lines.Count - 1)]) {
        if ($line -match "\[mods\] Active local mod (.+?) \(name:") { $names += $matches[1] }
        elseif ($line -match "\[mods\] Active \d+ mods" -and $names.Count) { break }
    }

    $modDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "$title\mod"
    $files = @()
    foreach ($name in $names) {
        $match = @("$name.scs", "$name.zip") |
            ForEach-Object { Join-Path $modDir $_ } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($match) { $files += $match }
        else { Write-Host "  skipping '$name' -- no matching file in the mod folder" -ForegroundColor Yellow }
    }
    return $files
}

function Find-GameDir($title) {
    $roots = @()
    $steam = Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue
    if ($steam -and $steam.SteamPath) { $roots += ($steam.SteamPath -replace '/', '\') }
    foreach ($root in @($roots)) {
        $vdf = Join-Path $root "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            foreach ($line in (Get-Content $vdf | Select-String '"path"')) {
                if ($line -match '"path"\s+"(.+?)"') { $roots += ($matches[1] -replace '\\\\', '\') }
            }
        }
    }
    foreach ($root in ($roots | Sort-Object -Unique -CaseSensitive:$false)) {
        $path = Join-Path $root "steamapps\common\$title"
        if (Test-Path $path) { return $path }
    }
    return $null
}

if (-not $ListMaps) { Write-Host "" }
# Rebuild when the exporter's own sources have moved on, not just when the exe is
# missing: editing Program.cs and seeing the old binary run is a long way to a wrong map.
$sources = @(
    (Join-Path $tools "mapexport\Program.cs"),
    (Join-Path $tools "mapexport\MapExport.csproj")
) | Where-Object { Test-Path $_ }

$stale = $false
if ((Test-Path $exe) -and $sources) {
    $newest = ($sources | ForEach-Object { (Get-Item $_).LastWriteTimeUtc } | Measure-Object -Maximum).Maximum
    $stale = $newest -gt (Get-Item $exe).LastWriteTimeUtc
}

if (-not (Test-Path $exe)) { Build-Exporter }
elseif ($stale) {
    Write-Host "  exporter is out of date -- rebuilding" -ForegroundColor Cyan
    Build-Exporter
}
elseif (-not $ListMaps) { Write-Host "  exporter already built" -ForegroundColor DarkGray }

$targets = if ($Game -eq "Both") { @("ETS2", "ATS") } else { @($Game) }

# Which maps each installed game can offer, as JSON on stdout and nothing else, so the
# tray menu can build its game/map list without the user having to know the names.
if ($ListMaps) {
    $found = [ordered]@{}
    foreach ($key in $targets) {
        $dir = Find-GameDir $GAMES[$key].Title
        if (-not $dir) { continue }
        $arguments = @("--game", $dir, "--list-maps")
        if (-not $NoMods) {
            foreach ($mod in (Get-ActiveMods $GAMES[$key].Title)) { $arguments += @("--mod", $mod) }
        }
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $names = & $exe @arguments 2>&1 |
                ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ } } |
                Where-Object { $_ -notmatch "\|\s+(Debug|Error|Info)\]" -and $_ -match "\S" }
        } finally { $ErrorActionPreference = $previousPreference }
        $found[$key] = @($names | ForEach-Object { $_.Trim() })
    }
    $found | ConvertTo-Json -Compress -Depth 3
    exit 0
}
$done = 0

foreach ($key in $targets) {
    $title = $GAMES[$key].Title
    Write-Host ""
    Write-Host "  $title" -ForegroundColor Cyan

    $dir = Find-GameDir $title
    if (-not $dir) { Write-Host "  not installed -- skipping" -ForegroundColor Yellow; continue }

    $arguments = @("--game", $dir, "--out", (Join-Path $PSScriptRoot "web\maps\$($GAMES[$key].Out)"))
    if ($Map) { $arguments += @("--map", $Map) }
    if ($Preview) { $arguments += @("--png", (Join-Path $tools "mapexport\preview-$($GAMES[$key].Out).png")) }
    if (-not $NoMods) {
        foreach ($mod in (Get-ActiveMods $title)) { $arguments += @("--mod", $mod) }
    }

    # The reader is chatty about missing company logos and the like; none of that
    # affects the roads, so only the summary lines are worth showing.
    #
    # 2>&1 on a native command wraps every stderr line in an ErrorRecord, which under
    # $ErrorActionPreference = "Stop" aborts the script on the first one. Drop back to
    # Continue for the call and flatten those records to plain strings so the filter
    # below still sees text.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $exe @arguments 2>&1 |
            ForEach-Object {
                if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
            } |
            Where-Object { $_ -notmatch "\|\s+(Debug|Error|Info)\]" }
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "  export failed" -ForegroundColor Red } else { $done++ }
}

Write-Host ""
if ($done) {
    Write-Host "  Done. The panel picks the new map up on its next load." -ForegroundColor Green
} else {
    Write-Host "  Nothing was exported." -ForegroundColor Yellow
}
Write-Host ""
