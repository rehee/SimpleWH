# Exercise script orchestration without starting containers or touching real data.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('simplewh-script-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
foreach ($name in @('.env', 'compose.yaml', 'compose.build.yaml')) {
    Set-Content -LiteralPath (Join-Path $testRoot $name) -Value ''
}
$global:DeploymentCalls = [Collections.Generic.List[string]]::new()
$global:DeploymentFailure = ''
function global:docker {
    $command = $args -join ' '
    $global:DeploymentCalls.Add($command)
    $global:LASTEXITCODE = if ($global:DeploymentFailure -and $command -match $global:DeploymentFailure) { 17 } else { 0 }
}
function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Invoke-Deployment([string]$Name, [hashtable]$Flags = @{}) {
    $path = Join-Path $projectRoot $Name
    $tokens = $null
    $parseErrors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
    Assert-True ($parseErrors.Count -eq 0) "Syntax errors in $Name"
    & $path -ProjectDirectory $testRoot @Flags
}
try {
    $originalLocation = (Get-Location).Path
    Invoke-Deployment 'up.ps1'
    Assert-True ($global:DeploymentCalls.Count -eq 2) 'Local startup should build then start.'
    Assert-True ($global:DeploymentCalls[0] -match 'compose.build.yaml.*build --pull app$') 'Local startup must rebuild the app.'
    Assert-True ($global:DeploymentCalls[1] -match 'up -d --no-build --wait') 'Local startup must wait for health.'
    Assert-True ((Get-Location).Path -eq $originalLocation) 'Script must restore the working directory.'

    $global:DeploymentCalls.Clear()
    Invoke-Deployment 'up_image.ps1' @{ Tunnel = $true }
    Assert-True ($global:DeploymentCalls.Count -eq 2) 'Registry startup should pull then start.'
    Assert-True ($global:DeploymentCalls[0] -match '--profile tunnel pull$') 'Tunnel profile must apply to pulls.'
    Assert-True ($global:DeploymentCalls[1] -match 'up -d --no-build --pull never --wait') 'Registry startup must never rebuild.'
    Assert-True (-not (($global:DeploymentCalls -join ' ') -match 'compose.build.yaml')) 'Registry startup must not load the build override.'

    $global:DeploymentCalls.Clear()
    Invoke-Deployment 'down.ps1'
    Assert-True ($global:DeploymentCalls.Count -eq 1) 'Shutdown should call Docker once.'
    Assert-True ($global:DeploymentCalls[0] -match '--profile tunnel down$') 'Shutdown must include tunnel containers.'
    Assert-True (-not ($global:DeploymentCalls[0] -match '(--volumes|\s-v(\s|$))')) 'Shutdown must preserve volumes.'

    foreach ($case in @(@{ Name = 'up.ps1'; Failure = '\sbuild\s' }, @{ Name = 'up_image.ps1'; Failure = '\spull$' })) {
        $global:DeploymentCalls.Clear()
        $global:DeploymentFailure = $case.Failure
        $failed = $false
        try { Invoke-Deployment $case.Name } catch { $failed = $_.Exception.Message -match 'failed.*17' }
        Assert-True $failed "Failure must be reported by $($case.Name)."
        Assert-True ($global:DeploymentCalls.Count -eq 1) 'Failed build/pull must not start containers.'
        Assert-True ((Get-Location).Path -eq $originalLocation) 'Failed command must restore the working directory.'
    }
    $global:DeploymentFailure = ''
    # Dotfiles are hidden on Linux and require -Force in PowerShell.
    Remove-Item -LiteralPath (Join-Path $testRoot '.env') -Force
    $global:DeploymentCalls.Clear()
    $failed = $false
    try { Invoke-Deployment 'up.ps1' } catch { $failed = $_.Exception.Message -match '\.env' }
    Assert-True $failed 'Missing .env must be reported.'
    Assert-True ($global:DeploymentCalls.Count -eq 0) 'Missing configuration must not call Docker.'
    Write-Host 'Deployment script checks passed.'
} finally {
    Remove-Item -LiteralPath Function:\docker
    Remove-Variable DeploymentCalls, DeploymentFailure -Scope Global
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTestRoot.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedTestRoot) -like 'simplewh-script-test-*') {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
