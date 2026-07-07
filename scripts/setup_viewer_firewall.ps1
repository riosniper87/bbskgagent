# One-time setup: allow inbound TCP 8765 for the QA viewer (run as Administrator).
# Right-click PowerShell → Run as administrator, then:
#   cd C:\Users\4250090\Documents\anaylsis\store-brief
#   .\scripts\setup_viewer_firewall.ps1

param([int]$Port = 8765)

$ruleName = "Store Brief QA Viewer (TCP $Port)"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Rule already exists: $ruleName"
    exit 0
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -Profile Domain,Private `
    -Description "Store Brief parse/Q&A viewer (serve_parse_viewer.py)"

Write-Host "Created: $ruleName (TCP $Port, Domain+Private profiles)"
