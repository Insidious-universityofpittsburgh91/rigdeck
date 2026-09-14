<#
    Builds the tablet app.

        .\build_apk.ps1            # release APK -> dist\RigDeck.apk
        .\build_apk.ps1 -Install   # ...and push it to a tablet on adb
        .\build_apk.ps1 -Clean     # start from scratch

    Neither the JDK nor the Android SDK is on PATH on this machine, so both are found
    here and handed to Gradle for the run only. Nothing is installed and no environment
    variable outlives the script.
#>

param(
    [switch]$Install,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$root = Join-Path $PSScriptRoot 'android'

# -- the toolchain ---------------------------------------------------------------
$jdk = @(
    'C:\Program Files\Android\Android Studio\jbr',
    'C:\Program Files\Android\Android Studio\jre'
) | Where-Object { Test-Path (Join-Path $_ 'bin\java.exe') } | Select-Object -First 1

$sdk = @(
    $env:ANDROID_HOME,
    $env:ANDROID_SDK_ROOT,
    "$env:LOCALAPPDATA\Android\Sdk",
    'C:\Android\Sdk',
    'D:\Android\Sdk'
) | Where-Object { $_ -and (Test-Path (Join-Path $_ 'platform-tools')) } | Select-Object -First 1

if (-not $jdk) { throw 'No JDK found. Android Studio ships one in its jbr folder.' }
if (-not $sdk) { throw 'No Android SDK found. Open Android Studio once and let it install one.' }

Write-Host "  JDK  $jdk"
Write-Host "  SDK  $sdk"

$env:JAVA_HOME = $jdk
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
"sdk.dir=$($sdk -replace '\\', '\\')" | Set-Content (Join-Path $root 'local.properties') -Encoding ascii

# -- signing ---------------------------------------------------------------------
# The app is sideloaded onto one tablet, never published, so a key generated here is
# enough. It only has to stay the same between builds or Android refuses the upgrade.
$keyDir = Join-Path $root 'keystore'
$keyStore = Join-Path $keyDir 'rigdeck.jks'
$keyProps = Join-Path $keyDir 'keystore.properties'

if (-not (Test-Path $keyStore)) {
    Write-Host '  generating a signing key (one time)'
    New-Item -ItemType Directory -Force $keyDir | Out-Null
    $pass = -join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    # keytool narrates onto stderr even when it succeeds, which PowerShell would otherwise
    # treat as a failure.
    $prev, $ErrorActionPreference = $ErrorActionPreference, 'Continue'
    & (Join-Path $jdk 'bin\keytool.exe') -genkeypair `
        -keystore $keyStore -alias rigdeck -keyalg RSA -keysize 2048 -validity 10950 `
        -storepass $pass -keypass $pass -dname 'CN=Rig Deck, OU=Local, O=Rig Deck, C=HR'
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0) { throw "keytool failed ($code)" }
    @(
        'storeFile=keystore/rigdeck.jks',
        "storePassword=$pass",
        'keyAlias=rigdeck',
        "keyPassword=$pass"
    ) | Set-Content $keyProps -Encoding ascii
}

# -- build -----------------------------------------------------------------------
Push-Location $root
try {
    $tasks = @()
    if ($Clean) { $tasks += 'clean' }
    $tasks += 'assembleRelease'
    & (Join-Path $root 'gradlew.bat') --no-daemon @tasks
    if ($LASTEXITCODE -ne 0) { throw "gradle failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}

$built = Join-Path $root 'app\build\outputs\apk\release\app-release.apk'
if (-not (Test-Path $built)) { throw "the build reported success but $built is missing" }

$dist = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Force $dist | Out-Null
$out = Join-Path $dist 'RigDeck.apk'
Copy-Item $built $out -Force
$size = [math]::Round((Get-Item $out).Length / 1KB)
Write-Host ""
Write-Host "  $out  ($size KB)"

# -- optional install ------------------------------------------------------------
if ($Install) {
    $adb = Join-Path $sdk 'platform-tools\adb.exe'
    $devices = & $adb devices | Select-String "\tdevice$"
    if (-not $devices) { throw 'No tablet on adb. Enable USB debugging and plug it in.' }
    & $adb install -r $out
    if ($LASTEXITCODE -ne 0) { throw 'adb install failed' }
    Write-Host '  installed'
}

Write-Host ""
Write-Host "  Copy it to the tablet and open it, or run with -Install over USB."
Write-Host ""
