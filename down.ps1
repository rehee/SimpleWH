param(
    [string]$ProjectDirectory = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectDirectory) { $ProjectDirectory = (Get-Location).Path }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is not installed.' }
Push-Location -LiteralPath $ProjectDirectory
try {
    if (-not (Test-Path -LiteralPath '.env')) { throw 'The project .env file is required to load the Compose configuration.' }
    if (-not (Test-Path -LiteralPath 'compose.yaml')) { throw 'Project Compose file is missing.' }
    & docker compose -f compose.yaml --profile tunnel down
    if ($LASTEXITCODE -ne 0) { throw "Container shutdown failed (exit $LASTEXITCODE)." }
    Write-Host 'Containers stopped and removed. Database and photo volumes are preserved.'
} finally {
    Pop-Location
}
