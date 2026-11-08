# wxo_import_tools.ps1
# Export the tools OpenAPI spec and import it into watsonx Orchestrate.
#
# Prerequisites:
#   - Python environment with app dependencies installed
#   - `orchestrate` CLI installed and authenticated
#
# Usage:
#   .\scripts\wxo_import_tools.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "==> Exporting OpenAPI spec..."
python scripts/export_tools_openapi.py
if (-not $?) { throw "export_tools_openapi.py failed" }

Write-Host ""
Write-Host "==> Importing tools into watsonx Orchestrate..."
orchestrate tools import -k openapi -f orchestrate/tools_openapi.json

Write-Host ""
Write-Host "==> Listing registered tools..."
orchestrate tools list
