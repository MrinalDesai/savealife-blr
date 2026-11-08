# wxo_import_agent.ps1
# Import the savealife_dispatch native agent definition into watsonx Orchestrate,
# then list all registered agents to confirm the import succeeded.
#
# Prerequisites:
#   - `orchestrate` CLI installed and authenticated (run `orchestrate login` first)
#
# Usage:
#   .\scripts\wxo_import_agent.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "==> Importing dispatch agent into watsonx Orchestrate..."
orchestrate agents import -f orchestrate/dispatch_agent.yaml

Write-Host ""
Write-Host "==> Listing registered agents..."
orchestrate agents list
