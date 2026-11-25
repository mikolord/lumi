param([string]$ToolchainRoot = "$env:USERPROFILE\.android-app-building\toolchain")
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$env:JAVA_HOME = Join-Path $ToolchainRoot 'jdk-21'
$env:ANDROID_HOME = Join-Path $ToolchainRoot 'sdk'
Push-Location $taskRoot
try {
    & .\gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug --console=plain
    if ($LASTEXITCODE -ne 0) { throw 'Build or checks failed' }
    [xml]$taskLint = Get-Content 'app/build/reports/lint-results-debug.xml'
    if (@($taskLint.issues.issue | Where-Object { $_.severity -in @('Error','Fatal') }).Count -gt 0) { throw 'Lint errors found' }
    $taskApk = Join-Path $taskRoot 'app/build/outputs/apk/debug/app-debug.apk'
    & (Join-Path $env:ANDROID_HOME 'build-tools/35.0.0/apksigner.bat') verify $taskApk
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed' }
    $taskMetadata = Get-Content 'app/build/outputs/apk/debug/output-metadata.json' | ConvertFrom-Json
    if ($taskMetadata.applicationId -ne 'club.netcraze.lumi') { throw 'Unexpected package identity' }
    $taskVersion = $taskMetadata.elements[0]
    & (Join-Path $taskRoot 'release/Test-Launcher.ps1') -Apk $taskApk
    $taskFeed = Join-Path $taskRoot 'release/tv'
    New-Item -ItemType Directory -Path $taskFeed -Force | Out-Null
    $taskPrevious = Join-Path $taskFeed 'rc-foto.apk'
    if (Test-Path -LiteralPath $taskPrevious) {
        $taskSigner = Join-Path $env:ANDROID_HOME 'build-tools/35.0.0/apksigner.bat'
        $taskOldCert = (& $taskSigner verify --print-certs $taskPrevious | Select-String 'certificate SHA-256 digest').ToString()
        $taskNewCert = (& $taskSigner verify --print-certs $taskApk | Select-String 'certificate SHA-256 digest').ToString()
        if (!$taskOldCert -or $taskOldCert -ne $taskNewCert) { throw 'Signing certificate changed; update would not be compatible' }
    }
    Copy-Item -LiteralPath $taskApk -Destination (Join-Path $taskFeed 'rc-foto.apk') -Force
    $taskHash = (Get-FileHash -LiteralPath $taskApk -Algorithm SHA256).Hash.ToLowerInvariant()
    $taskImmutableName = "lumi-$($taskVersion.versionCode)-$taskHash.apk"
    Copy-Item -LiteralPath $taskApk -Destination (Join-Path $taskFeed $taskImmutableName) -Force
    $taskInfo = [ordered]@{versionCode=$taskVersion.versionCode;versionName=$taskVersion.versionName;url="/tv/$taskImmutableName";sha256=$taskHash;notes='Универсальный Lumi для телефонов, планшетов и ТВ: мобильный интерфейс, фоновая очередь и автозагрузка'}
    $taskJson = $taskInfo | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $taskFeed 'version.json.new'), $taskJson, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath (Join-Path $taskFeed 'version.json.new') -Destination (Join-Path $taskFeed 'version.json') -Force
    Write-Output "Ready: lumi $($taskVersion.versionName) — release/tv/rc-foto.apk"
} finally { Pop-Location }
