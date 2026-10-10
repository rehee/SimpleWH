param(
    [switch]$Tunnel,
    [string]$ProjectDirectory = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectDirectory) { $ProjectDirectory = (Get-Location).Path }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is not installed.' }
Push-Location -LiteralPath $ProjectDirectory
try {
    if (-not (Test-Path -LiteralPath '.env')) { throw 'Create .env from .env.example and configure passwords first.' }
    if (-not (Test-Path -LiteralPath 'compose.yaml')) { throw 'Project Compose file is missing.' }
    $composeArgs = @('compose', '-f', 'compose.yaml')
    if ($Tunnel) { $composeArgs += @('--profile', 'tunnel') }

    & docker @composeArgs pull
    if ($LASTEXITCODE -ne 0) { throw "Image pull failed (exit $LASTEXITCODE). Check image availability and GHCR login. Containers were not started." }
    & docker @composeArgs up -d --no-build --pull never --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw "Container startup failed (exit $LASTEXITCODE). Check docker compose logs." }
    Write-Host 'Registry images pulled; containers are running and healthy.'
} finally {
    Pop-Location
}
