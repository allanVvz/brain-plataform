param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("local-qa", "docker", "vercel")]
  [string]$Target,

  [string]$BackendUrl = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$dashboardDir = Join-Path $repoRoot "dashboard"
$envPath = Join-Path $dashboardDir ".env.local"

function Read-EnvFile([string]$Path) {
  $values = @{}
  if (-not (Test-Path -LiteralPath $Path)) {
    return $values
  }
  foreach ($line in Get-Content -LiteralPath $Path) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
      continue
    }
    $idx = $trimmed.IndexOf("=")
    $key = $trimmed.Substring(0, $idx).Trim()
    $value = $trimmed.Substring($idx + 1).Trim()
    $values[$key] = $value
  }
  return $values
}

$existing = Read-EnvFile $envPath

switch ($Target) {
  "local-qa" {
    $backend = if ($BackendUrl) { $BackendUrl } else { "http://127.0.0.1:8001" }
    $label = "Local dashboard against the QA backend running on the host."
  }
  "docker" {
    $backend = if ($BackendUrl) { $BackendUrl } else { "http://localhost:8080" }
    $label = "Local dashboard against the Docker backend."
  }
  "vercel" {
    if (-not $BackendUrl) {
      throw "BackendUrl is required for vercel. Pass a public backend URL, for example: -BackendUrl https://api.example.com"
    }
    if ($BackendUrl -match "localhost|127\.0\.0\.1|0\.0\.0\.0") {
      throw "Vercel cannot use a localhost backend URL. Pass the public URL of the Docker backend."
    }
    $backend = $BackendUrl.TrimEnd("/")
    $label = "Vercel dashboard build target. Backend must be publicly reachable."
  }
}

$apiBase = $existing["NEXT_PUBLIC_API_BASE_URL"]
if (-not $apiBase) { $apiBase = "/api-brain" }

$lines = @(
  "# $label",
  "API_INTERNAL_BASE_URL=$backend",
  "NEXT_PUBLIC_API_BASE_URL=$apiBase"
)

Set-Content -LiteralPath $envPath -Value $lines -Encoding UTF8
Write-Host "[dashboard-env] $Target -> API_INTERNAL_BASE_URL=$backend"
Write-Host "[dashboard-env] wrote $envPath"
