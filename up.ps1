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
    if (-not (Test-Path -LiteralPath 'compose.yaml') -or -not (Test-Path -LiteralPath 'compose.build.yaml')) { throw 'Project Compose files are missing.' }
    $composeArgs = @('compose', '-f', 'compose.yaml', '-f', 'compose.build.yaml')
    if ($Tunnel) { $composeArgs += @('--profile', 'tunnel') }

    & docker @composeArgs build --pull app
    if ($LASTEXITCODE -ne 0) { throw "Image build failed (exit $LASTEXITCODE). Containers were not started." }
    & docker @composeArgs up -d --no-build --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw "Container startup failed (exit $LASTEXITCODE). Check docker compose logs." }
    Write-Host 'Local image rebuilt; containers are running and healthy.'
} finally {
    Pop-Location
}
