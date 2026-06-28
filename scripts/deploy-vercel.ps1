param(
  [Parameter(Mandatory = $true)]
  [string]$BackendUrl,

  [switch]$Prod
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$dashboardDir = Join-Path $repoRoot "dashboard"

if ($BackendUrl -match "localhost|127\.0\.0\.1|0\.0\.0\.0") {
  throw "Vercel needs a public backend URL. Received: $BackendUrl"
}

& (Join-Path $PSScriptRoot "set-dashboard-env.ps1") -Target vercel -BackendUrl $BackendUrl

Set-Location $dashboardDir
& npm.cmd run env:check
& npm.cmd run build

$args = @("deploy")
if ($Prod) { $args += "--prod" }

Write-Host "[deploy-vercel] vercel $($args -join ' ')"
Write-Host "[deploy-vercel] Make sure the Vercel project has API_INTERNAL_BASE_URL=$BackendUrl"
Write-Host "[deploy-vercel] and NEXT_PUBLIC_API_BASE_URL=/api-brain configured for the same environment."
& vercel @args
