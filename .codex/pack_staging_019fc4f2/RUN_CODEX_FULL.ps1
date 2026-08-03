[CmdletBinding()]
param(
    [string]$RepoPath = "D:\ALL ABOUT PROJECT\PROJECT\P-208",
    [string]$Profile = "full-machine",
    [switch]$SkipGeminiVerification
)

$ErrorActionPreference = "Stop"
Set-Location $RepoPath

$requiredFiles = @(
    "AGENTS.md",
    "CODEX_MASTER_IMPLEMENTATION_PROMPT.md",
    "PROJECT_IMPLEMENTATION_SPEC.md",
    "GEMINI_MODEL_ROUTING_POLICY.md",
    "DATA_INGESTION_SPEC.md",
    "ACCEPTANCE_CRITERIA.md",
    ".env.vmec.example",
    "data\source\VMEC_FULL_DATA_DEVELOPMENT_READY.zip",
    "data\source\VMEC_FULL_DATA_RESEARCH_MASTER.zip",
    "data\source\VMEC_GLOBAL_SOURCE_LEDGER.csv.gz",
    "data\source\VMEC_FULL_DATA_MASTER_INDEX.xlsx"
)
foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) { throw "Missing required file: $file" }
}

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw "Codex CLI is not available in PATH." }
if (-not $env:GEMINI_API_KEY) { throw "GEMINI_API_KEY is missing. Configure it without printing the value." }

if (-not $SkipGeminiVerification) {
    & ".\VERIFY_GEMINI_MODELS.ps1"
}

$branch = (git branch --show-current).Trim()
if (-not $branch) { throw "Unable to determine current Git branch." }
if ($branch -in @("main", "master")) {
    $targetBranch = "codex/vmec-production-implementation"
    $exists = git branch --list $targetBranch
    if ($exists) { git switch $targetBranch } else { git switch -c $targetBranch }
    if ($LASTEXITCODE -ne 0) { throw "Unable to switch/create feature branch." }
}

New-Item -ItemType Directory -Force -Path ".codex\runs" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = ".codex\runs\full_$stamp.log"

Write-Host "Starting Codex implementation with profile '$Profile'."
Write-Host "Log: $log"

Get-Content ".\CODEX_MASTER_IMPLEMENTATION_PROMPT.md" -Raw |
    codex exec --profile $Profile --strict-config - 2>&1 |
    Tee-Object -FilePath $log

if ($LASTEXITCODE -ne 0) {
    throw "Codex exited with code $LASTEXITCODE. Review $log, resolve only genuine external blockers, then run RUN_CODEX_CONTINUE.ps1."
}
