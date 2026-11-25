param([Parameter(Mandatory=$true)][string]$Apk)
$ErrorActionPreference = 'Stop'
$taskAapt = Join-Path $env:ANDROID_HOME 'build-tools/35.0.0/aapt2.exe'
$taskBadging = @(& $taskAapt dump badging $Apk)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect APK manifest' }
$taskApplication = $taskBadging | Where-Object { $_ -match '^application:' }
$taskLauncher = $taskBadging | Where-Object { $_ -match '^launchable-activity:' }
$taskLeanback = $taskBadging | Where-Object { $_ -match '^leanback-launchable-activity:' }
$taskResource = 'res/drawable/lumi_launcher_card.png'
$taskPlatform = 'res/drawable/lumi_platform_icon.png'
if (!$taskApplication.Contains("icon='$taskPlatform'") -or !$taskApplication.Contains("banner='$taskResource'")) { throw 'Universal application artwork is missing' }
if (!$taskLauncher.Contains("icon='$taskPlatform'") -or !$taskLauncher.Contains('LauncherActivity')) { throw 'Adaptive mobile launcher is missing' }
if (!$taskLeanback.Contains("icon='$taskResource'") -or !$taskLeanback.Contains("banner='$taskResource'") -or !$taskLeanback.Contains('MainActivity')) { throw 'TV launcher artwork is missing' }
if ($taskBadging | Where-Object { $_ -eq "  uses-feature: name='android.software.leanback'" -or $_ -eq "  uses-feature: name='android.hardware.touchscreen'" }) { throw 'Universal APK must not require TV or touch hardware' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$taskZip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $Apk).Path)
try {
    if (!($taskZip.Entries | Where-Object { $_.FullName.Contains('finger') -and $_.FullName.EndsWith('/lumi_platform_icon.xml') })) { throw 'Touch-device adaptive icon is missing' }
    if (!($taskZip.Entries | Where-Object { $_.FullName.Contains('television') -and $_.FullName.EndsWith('/lumi_platform_icon.png') })) { throw 'TV device icon is missing' }
    $taskEntry = $taskZip.GetEntry($taskResource)
    if (!$taskEntry) { throw 'TV card image missing from APK' }
    $taskStream = $taskEntry.Open()
    try {
        $taskHeader = New-Object byte[] 24
        if ($taskStream.Read($taskHeader, 0, 24) -ne 24) { throw 'Invalid PNG header' }
        $taskWidth = $taskHeader[16]*16777216 + $taskHeader[17]*65536 + $taskHeader[18]*256 + $taskHeader[19]
        $taskHeight = $taskHeader[20]*16777216 + $taskHeader[21]*65536 + $taskHeader[22]*256 + $taskHeader[23]
        if ($taskWidth -ne 496 -or $taskHeight -ne 280) { throw 'TV card must be 496x280' }
    } finally { $taskStream.Dispose() }
} finally { $taskZip.Dispose() }
Write-Output 'Universal APK verified: adaptive touch icon, 496x280 TV art, separate mobile and TV launchers'
