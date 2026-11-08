#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy savealife-blr to IBM Cloud Code Engine.
.DESCRIPTION
    Creates or updates the Code Engine project and application.
    Reads .env from the repo root and passes every non-empty, non-comment
    variable as --env KEY=VALUE, except IBM_CLOUD_API_KEY.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectName = 'savealife-blr'
$AppName     = 'savealife-blr'
$Region      = 'us-south'
$EnvFile     = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'

# ---------------------------------------------------------------------------
# 1. Target the right region
# ---------------------------------------------------------------------------
Write-Host "==> Targeting region $Region ..."
ibmcloud target -r $Region | Out-Null

# ---------------------------------------------------------------------------
# 2. Create or select the Code Engine project
# ---------------------------------------------------------------------------
Write-Host "==> Checking for Code Engine project '$ProjectName' ..."
$existing = ibmcloud ce project list --output json 2>$null | ConvertFrom-Json
$projectExists = $existing.projects | Where-Object { $_.name -eq $ProjectName }

if ($projectExists) {
    Write-Host "    Project exists — selecting it."
    ibmcloud ce project select --name $ProjectName
} else {
    Write-Host "    Project not found — creating it."
    ibmcloud ce project create --name $ProjectName
}

# ---------------------------------------------------------------------------
# 3. Build --env flags from .env (skip IBM_CLOUD_API_KEY and blanks)
# ---------------------------------------------------------------------------
$envFlags = @()
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { return }
        $key = ($line -split '=', 2)[0]
        if ($key -eq 'IBM_CLOUD_API_KEY') { return }
        $envFlags += '--env'
        $envFlags += $line   # KEY=VALUE
    }
}

# ---------------------------------------------------------------------------
# 4. Create or update the application
# ---------------------------------------------------------------------------
Write-Host "==> Deploying application '$AppName' ..."
$appExists = ibmcloud ce app get --name $AppName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "    App exists — updating."
    ibmcloud ce app update --name $AppName --build-source . --port 8080 `
        --min-scale 1 --max-scale 1 --cpu 0.5 --memory 1G @envFlags
} else {
    Write-Host "    App not found — creating."
    ibmcloud ce app create --name $AppName --build-source . --port 8080 `
        --min-scale 1 --max-scale 1 --cpu 0.5 --memory 1G @envFlags
}

# ---------------------------------------------------------------------------
# 5. Print the application URL
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Application URL:"
ibmcloud ce app get --name $AppName --output url
