# Restart parse/Q&A viewer for LAN access (other PCs on the same network).
#
# Usage:
#   .\scripts\serve_viewer_lan.ps1
#   .\scripts\serve_viewer_lan.ps1 -AsOf 2026-06-17 -Port 8765
#
# Opens: http://<this-pc-lan-ip>:8765/qa  (e.g. http://10.154.90.43:8765/qa)

param(
    [string]$AsOf = "2026-06-17",
    [int]$Port = 8765,
    [string]$HostBind = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ruleName = "Store Brief QA Viewer (TCP $Port)"

function Get-LanIPv4 {
    try {
        $udp = New-Object System.Net.Sockets.UdpClient
        $udp.Connect("8.8.8.8", 80)
        $ip = ($udp.Client.LocalEndPoint).Address.ToString()
        $udp.Close()
        return $ip
    } catch {
        return $null
    }
}

function Ensure-FirewallRule {
    param([int]$LocalPort, [string]$DisplayName)
    $existing = Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Firewall rule already exists: $DisplayName"
        return
    }
    try {
        New-NetFirewallRule `
            -DisplayName $DisplayName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort $LocalPort `
            -Profile Domain,Private | Out-Null
        Write-Host "Created firewall inbound rule for TCP $LocalPort"
    } catch {
        Write-Warning @"
Could not create firewall rule (admin rights may be required).
Run PowerShell as Administrator once:

  New-NetFirewallRule -DisplayName '$DisplayName' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $LocalPort -Profile Domain,Private
"@
    }
}

# Stop prior listener on the port
$pids = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($procId in $pids) {
    if ($procId) {
        Write-Host "Stopping process on port ${Port}: PID $procId"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

Ensure-FirewallRule -LocalPort $Port -DisplayName $ruleName

$lan = Get-LanIPv4
Write-Host ""
Write-Host "Starting viewer on ${HostBind}:${Port} (as_of=$AsOf)"
if ($lan) {
    Write-Host "  LAN Q&A:  http://${lan}:${Port}/qa"
}
Write-Host "  Local Q&A: http://localhost:${Port}/qa"
Write-Host ""

Push-Location $root
try {
    python scripts/serve_parse_viewer.py --host $HostBind --port $Port --as-of $AsOf
} finally {
    Pop-Location
}
