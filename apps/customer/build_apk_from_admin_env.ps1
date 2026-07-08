$ErrorActionPreference = 'Stop'
Set-Location 'D:\projects\greeneatGo\apps\customer'

$envFile = 'D:\projects\greeneatGo\apps\admin\.env'
$envs = @{}
Get-Content $envFile | ForEach-Object {
  if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
    $envs[$matches[1].Trim()] = $matches[2].Trim()
  }
}

if (-not $envs['VITE_SUPABASE_URL'] -or -not $envs['VITE_SUPABASE_ANON_KEY'] -or -not $envs['VITE_API_BASE_URL']) {
  throw 'apps/admin/.env must contain VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_BASE_URL'
}

$authEmailRedirectTo = $envs['VITE_AUTH_EMAIL_REDIRECT_TO']
if (-not $authEmailRedirectTo) {
  $authEmailRedirectTo = 'https://greeneatgo-api.onrender.com/v1/auth/confirmed'
}

& 'D:\dev\flutter\bin\flutter.bat' clean
& 'D:\dev\flutter\bin\flutter.bat' pub get
& 'D:\dev\flutter\bin\flutter.bat' build apk `
  --dart-define="SUPABASE_URL=$($envs['VITE_SUPABASE_URL'])" `
  --dart-define="SUPABASE_ANON_KEY=$($envs['VITE_SUPABASE_ANON_KEY'])" `
  --dart-define="API_BASE_URL=$($envs['VITE_API_BASE_URL'])" `
  --dart-define="AUTH_EMAIL_REDIRECT_TO=$authEmailRedirectTo"
