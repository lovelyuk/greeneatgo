$ErrorActionPreference = 'Stop'
Set-Location 'D:\projects\greeneatGo\apps\customer'

$envFile = 'D:\projects\greeneatGo\apps\admin\.env'
$envs = @{}
Get-Content $envFile | ForEach-Object {
  if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
    $envs[$matches[1].Trim()] = $matches[2].Trim()
  }
}

if (-not $envs['VITE_API_BASE_URL']) {
  throw 'apps/admin/.env must contain VITE_API_BASE_URL'
}

& 'D:\dev\flutter\bin\flutter.bat' clean
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& 'D:\dev\flutter\bin\flutter.bat' pub get
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$buildArgs = @(
  'build', 'apk',
  "--dart-define=API_BASE_URL=$($envs['VITE_API_BASE_URL'])"
)
$firebaseConfigPath = 'D:\projects\greeneatGo\apps\customer\android\app\google-services.json'
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

& 'D:\dev\flutter\bin\flutter.bat' @buildArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
