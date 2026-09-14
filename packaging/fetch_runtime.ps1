<#
    Downloads the Python that gets bundled into the distribution zip.

        powershell -ExecutionPolicy Bypass -File packaging\fetch_runtime.ps1

    This is the "embeddable" build from python.org: the interpreter, the standard
    library and nothing else -- no installer, no registry, no PATH, no effect on any
    Python already on the machine. Rig Deck's server is standard library only, which is
    what makes shipping it this way possible at all, and it is why the person on the
    other end has nothing to install and no version to get wrong.

    Kept out of git (it is 12 MB of someone else's binary); run this once on a fresh
    clone before packaging\make_zip.ps1.
#>

param(
    [string]$Version = '3.14.6'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$dest = Join-Path (Split-Path $PSScriptRoot -Parent) 'tools\python-embed'
$zip = Join-Path $dest "python-$Version-embed-amd64.zip"
$runtime = Join-Path $dest 'runtime'

New-Item -ItemType Directory -Force $dest | Out-Null

if (-not (Test-Path $zip)) {
    Write-Host "  downloading Python $Version (embeddable, 64-bit)..." -ForegroundColor Cyan
    Invoke-WebRequest -UseBasicParsing -OutFile $zip `
        -Uri "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"
}

if (Test-Path $runtime) { Remove-Item -Recurse -Force $runtime }
Expand-Archive $zip -DestinationPath $runtime

# The embeddable build searches only beside its own exe. Naming the server folder here
# is what lets `python.exe -m rigdeck` work from the installed layout.
$pth = Get-ChildItem $runtime -Filter 'python*._pth' | Select-Object -First 1
$lines = Get-Content $pth.FullName
if ($lines -notcontains '..\server') { ($lines + '..\server') | Set-Content $pth.FullName -Encoding ASCII }

$check = & (Join-Path $runtime 'python.exe') -c "import ctypes, mmap, socket, sqlite3; print('ok')"
Write-Host "  $runtime  ($check)" -ForegroundColor Green
