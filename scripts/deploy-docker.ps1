param([switch]$NoBuild)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Path -LiteralPath ".env.compose")) {
  throw ".env.compose not found. Create it before deploying the Docker stack."
}

$composeArgs = @("compose", "--env-file", ".env.compose", "up", "-d")
if (-not $NoBuild) {
  $composeArgs += "--build"
}
$composeArgs += "--remove-orphans"

Write-Host "[deploy-docker] docker $($composeArgs -join ' ')"
& docker @composeArgs

Write-Host "[deploy-docker] health checks"
& docker compose --env-file .env.compose ps
Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080/health/ready" | Select-Object StatusCode,Content
