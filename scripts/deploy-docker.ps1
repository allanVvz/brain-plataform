param(
  [switch]$NoBuild,
  [switch]$SkipDashboardEnv
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Path -LiteralPath ".env.compose")) {
  throw ".env.compose not found. Create it before deploying the Docker stack."
}

if (-not $SkipDashboardEnv) {
  & (Join-Path $PSScriptRoot "set-dashboard-env.ps1") -Target docker
}

$composeArgs = @("compose", "--env-file", ".env.compose", "up", "-d")
if (-not $NoBuild) {
  $composeArgs += "--build"
}
$composeArgs += @("db", "kong", "rest", "storage", "api", "workers")

Write-Host "[deploy-docker] docker $($composeArgs -join ' ')"
& docker @composeArgs

Write-Host "[deploy-docker] health checks"
& docker compose --env-file .env.compose ps
Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080/health" | Select-Object StatusCode,Content
