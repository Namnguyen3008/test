[CmdletBinding()]
param(
    [string]$RepoPath = "D:\ALL ABOUT PROJECT\PROJECT\P-208",
    [string]$Profile = "full-machine",
    [switch]$SkipGeminiVerification
)

$ErrorActionPreference = "Stop"
Set-Location $RepoPath

if (-not (Test-Path ".\CODEX_CONTINUE_IMPLEMENTATION_PROMPT.md")) {
    throw "Missing CODEX_CONTINUE_IMPLEMENTATION_PROMPT.md"
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw "Codex CLI is not available in PATH." }
if (-not $env:GEMINI_API_KEY) { throw "GEMINI_API_KEY is missing. Configure it without printing the value." }

if (-not $SkipGeminiVerification) {
    & ".\VERIFY_GEMINI_MODELS.ps1"
}

if (-not (Test-Path ".\docs\IMPLEMENTATION_STATUS.md")) {
    Write-Warning "docs/IMPLEMENTATION_STATUS.md is missing. Codex must reconstruct status from Git and repository files."
}

New-Item -ItemType Directory -Force -Path ".codex\runs" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = ".codex\runs\continue_$stamp.log"

Write-Host "Continuing Codex implementation with profile '$Profile'."
Write-Host "Log: $log"

Get-Content ".\CODEX_CONTINUE_IMPLEMENTATION_PROMPT.md" -Raw |
    codex exec --profile $Profile --strict-config - 2>&1 |
    Tee-Object -FilePath $log

if ($LASTEXITCODE -ne 0) {
    throw "Codex exited with code $LASTEXITCODE. Review $log."
}
