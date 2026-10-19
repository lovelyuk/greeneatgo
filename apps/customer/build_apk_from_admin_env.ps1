$ErrorActionPreference = 'Stop'
# Flutter SDK: FLUTTER_BAT env var, else G:\dev\flutter, else D:\dev\flutter.
$flutter = @($env:FLUTTER_BAT, 'G:\dev\flutter\bin\flutter.bat', 'D:\dev\flutter\bin\flutter.bat') | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $flutter) { throw 'flutter.bat not found (set FLUTTER_BAT)' }
# Native builds (ninja/CMake for the jni plugin) fail when the pub cache or TEMP
# path contains non-ASCII characters (e.g. a Korean Windows user name). Default
# both to ASCII paths next to the Flutter SDK unless the caller already set them.
if ($env:USERPROFILE -match '[^\x00-\x7F]') {
  $asciiRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $flutter))
  if (-not $env:PUB_CACHE) { $env:PUB_CACHE = Join-Path $asciiRoot 'pub-cache' }
  # The NDK/CMake toolchain under C:\Users\<non-ASCII>\AppData\Local\Android\Sdk
  # also breaks ninja. Use an ASCII junction to the same SDK and point
  # android/local.properties at it (local file, not committed).
  $asciiSdk = Join-Path $asciiRoot 'android-sdk'
  $realSdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
  if (-not (Test-Path $asciiSdk) -and (Test-Path $realSdk)) {
    cmd /c mklink /J "$asciiSdk" "$realSdk" | Out-Null
  }
  if (Test-Path $asciiSdk) {
    $env:ANDROID_HOME = $asciiSdk; $env:ANDROID_SDK_ROOT = $asciiSdk
    $localProps = Join-Path $PSScriptRoot 'android\local.properties'
    if (Test-Path $localProps) {
      $sdkLine = 'sdk.dir=' + ($asciiSdk -replace '\\', '\\')
      $lines = Get-Content $localProps -Encoding UTF8 | Where-Object { $_ -notmatch '^sdk\.dir=' }
      Set-Content -Path $localProps -Value (@($sdkLine) + $lines) -Encoding UTF8
    }
  }
  if ($env:TEMP -match '[^\x00-\x7F]') {
    $env:TEMP = Join-Path $asciiRoot 'tmp'; $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
  }
}
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location (Join-Path $root 'apps\customer')

$envFile = Join-Path $root 'apps\admin\.env'
$envs = @{}
Get-Content $envFile | ForEach-Object {
  if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
    $envs[$matches[1].Trim()] = $matches[2].Trim()
  }
}

if (-not $envs['VITE_API_BASE_URL']) {
  throw 'apps/admin/.env must contain VITE_API_BASE_URL'
}

& $flutter clean
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $flutter pub get
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$buildArgs = @(
  'build', 'apk',
  "--dart-define=API_BASE_URL=$($envs['VITE_API_BASE_URL'])"
)
$firebaseConfigPath = Join-Path $root 'apps\customer\android\app\google-services.json'
if (Test-Path $firebaseConfigPath) {
  $firebaseConfig = Get-Content $firebaseConfigPath -Raw | ConvertFrom-Json
  $firebaseClient = $firebaseConfig.client | Where-Object { $_.client_info.android_client_info.package_name -eq 'com.greeneat.greeneatgo' } | Select-Object -First 1
  if ($firebaseClient) {
    if (-not $envs['FIREBASE_API_KEY']) { $envs['FIREBASE_API_KEY'] = $firebaseClient.api_key[0].current_key }
    if (-not $envs['FIREBASE_APP_ID']) { $envs['FIREBASE_APP_ID'] = $firebaseClient.client_info.mobilesdk_app_id }
    if (-not $envs['FIREBASE_MESSAGING_SENDER_ID']) { $envs['FIREBASE_MESSAGING_SENDER_ID'] = $firebaseConfig.project_info.project_number }
    if (-not $envs['FIREBASE_PROJECT_ID']) { $envs['FIREBASE_PROJECT_ID'] = $firebaseConfig.project_info.project_id }
  }
}

$firebaseKeys = @('FIREBASE_API_KEY', 'FIREBASE_APP_ID', 'FIREBASE_MESSAGING_SENDER_ID', 'FIREBASE_PROJECT_ID')
$firebaseValues = $firebaseKeys | Where-Object { $envs[$_] }
if ($firebaseValues.Count -ne $firebaseKeys.Count) {
  throw 'Firebase Authentication config is required. Provide google-services.json or all FIREBASE_API_KEY, FIREBASE_APP_ID, FIREBASE_MESSAGING_SENDER_ID, FIREBASE_PROJECT_ID values.'
}
$buildArgs += '--dart-define=FIREBASE_ENABLED=true'
foreach ($key in $firebaseKeys) {
  $buildArgs += "--dart-define=$key=$($envs[$key])"
}

& $flutter @buildArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
