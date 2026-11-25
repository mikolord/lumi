param([Parameter(Mandatory=$true)][string]$Apk)
$ErrorActionPreference = 'Stop'
$taskAapt = Join-Path $env:ANDROID_HOME 'build-tools/35.0.0/aapt2.exe'
$taskBadging = @(& $taskAapt dump badging $Apk)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect APK manifest' }
$taskApplication = $taskBadging | Where-Object { $_ -match '^application:' }
$taskLauncher = $taskBadging | Where-Object { $_ -match '^launchable-activity:' }
$taskLeanback = $taskBadging | Where-Object { $_ -match '^leanback-launchable-activity:' }
$taskResource = 'res/drawable/lumi_launcher_card.png'
foreach ($taskEntry in @($taskApplication, $taskLauncher, $taskLeanback)) {
    if (!$taskEntry -or !$taskEntry.Contains("icon='$taskResource'")) {
        throw 'Launcher regression: application and both launchers must use the full-size TV card'
    }
}
if (!$taskApplication.Contains("banner='$taskResource'") -or !$taskLeanback.Contains("banner='$taskResource'")) {
    throw 'Launcher regression: application and TV banner must use the full-size card'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$taskZip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $Apk).Path)
try {
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
Write-Output 'Launcher APK verification passed: application and both launchers use the 496x280 card'
