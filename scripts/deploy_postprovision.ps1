#!/usr/bin/env pwsh
# Runs after ``azd provision`` succeeds. Uses azd env outputs to
# smoke-test the deployment. Non-fatal — the full verification is in
# ``docs/deployment.md``.

$ErrorActionPreference = 'Stop'

Write-Host "== EGP MAF post-provision =="

$outputs = azd env get-values --output json | ConvertFrom-Json
$backendFqdn  = $outputs.BACKENDFQDN
$frontendFqdn = $outputs.FRONTENDFQDN

if ($backendFqdn) {
    Write-Host "Backend FQDN:  $backendFqdn"
    try {
        $r = Invoke-WebRequest "https://$backendFqdn/health" -TimeoutSec 15 -UseBasicParsing
        Write-Host "Backend /health: $($r.StatusCode)"
    } catch {
        Write-Warning "Backend /health probe failed: $_"
    }
} else {
    Write-Warning "No BACKENDFQDN in azd env — provisioning outputs missing?"
}

if ($frontendFqdn) {
    Write-Host "Frontend FQDN: $frontendFqdn"
}

Write-Host "Done. See docs/deployment.md for full verification."
