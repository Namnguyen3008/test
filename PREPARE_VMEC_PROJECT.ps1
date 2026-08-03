[CmdletBinding()]
param(
    [string]$RepoPath = "D:\ALL ABOUT PROJECT\PROJECT\P-208",
    [Parameter(Mandatory = $true)]
    [string]$SourceDataDir
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RepoPath)) { throw "Repository path does not exist: $RepoPath" }
if (-not (Test-Path (Join-Path $RepoPath ".git"))) { throw "Not a Git repository: $RepoPath" }
if (-not (Test-Path $SourceDataDir)) { throw "Source data directory does not exist: $SourceDataDir" }

$required = @(
    "VMEC_FULL_DATA_RESEARCH_MASTER.zip",
    "VMEC_FULL_DATA_DEVELOPMENT_READY.zip",
    "VMEC_GLOBAL_SOURCE_LEDGER.csv.gz",
    "VMEC_FULL_DATA_MASTER_INDEX.xlsx"
)

$target = Join-Path $RepoPath "data\source"
New-Item -ItemType Directory -Force -Path $target | Out-Null

$manifest = @()
foreach ($name in $required) {
    $source = Join-Path $SourceDataDir $name
    if (-not (Test-Path $source)) { throw "Missing required data file: $source" }

    $sourceHash = (Get-FileHash -Algorithm SHA256 $source).Hash.ToLowerInvariant()
    $dest = Join-Path $target $name

    if (Test-Path $dest) {
        $destHash = (Get-FileHash -Algorithm SHA256 $dest).Hash.ToLowerInvariant()
        if ($sourceHash -ne $destHash) {
            throw "A different immutable file exists at $dest. Refusing to overwrite it."
        }
        Write-Host "Already present and hash matches: $name"
    } else {
        Copy-Item -LiteralPath $source -Destination $dest
        Write-Host "Copied immutable source: $name"
    }

    $item = Get-Item $dest
    $manifest += [pscustomobject]@{
        filename = $name
        sha256 = $sourceHash
        size_bytes = $item.Length
    }
}

$manifestPath = Join-Path $target "SOURCE_ARTIFACT_MANIFEST.local.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $manifestPath

$gitignore = Join-Path $RepoPath ".gitignore"
$rules = @(
    "",
    "# VMEC private/immutable data and generated runtime artifacts",
    "data/source/*",
    "!data/source/.gitkeep",
    "data/staging/",
    "data/reports/",
    "var/",
    ".env",
    ".env.*.local",
    ".codex/runs/"
)
$current = if (Test-Path $gitignore) { Get-Content $gitignore -Raw } else { "" }
if ($current -notmatch [regex]::Escape("data/source/*")) {
    Add-Content -Path $gitignore -Value ($rules -join [Environment]::NewLine)
}

Set-Location $RepoPath
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw "Codex CLI is not available in PATH." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is not available in PATH." }
if ($env:GEMINI_API_KEY) {
    Write-Host "GEMINI_API_KEY: configured (value hidden)"
} else {
    Write-Warning "GEMINI_API_KEY is not configured in this PowerShell environment."
}

Write-Host "Repository prepared: $RepoPath"
Write-Host "Immutable data directory: $target"
Write-Host "Local data manifest: $manifestPath"
Write-Host "Next: run .\VERIFY_GEMINI_MODELS.ps1, then .\RUN_CODEX_FULL.ps1"
