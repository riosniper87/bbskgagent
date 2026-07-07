# QA Loop — one-shot eval (optional rebuild)
# Usage: .\scripts\qa_loop.ps1 -AsOf 2026-06-17 -NCases 30
param(
    [Parameter(Mandatory = $true)][string]$AsOf,
    [int]$NCases = 10,
    [int]$Seed = 42,
    [switch]$RebuildLlmwiki,
    [switch]$RebuildKg,
    [switch]$NoJudge,
    [switch]$Promote,
    [switch]$CacheOnly
)

$root = Split-Path -Parent $PSScriptRoot
$args = @(
    "scripts/qa_loop.py",
    "--as-of", $AsOf,
    "-n", $NCases,
    "--seed", $Seed
)
if ($RebuildLlmwiki) { $args += "--rebuild-llmwiki" }
if ($RebuildKg) { $args += "--rebuild-kg" }
if ($NoJudge) { $args += "--no-judge" }
if ($Promote) { $args += "--promote" }
if ($CacheOnly) { $args += "--cache-only" }

Push-Location $root
try {
    python @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
