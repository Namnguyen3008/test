# Install git pre-push hook for AI log submission (Windows PowerShell).
# Run once after cloning: powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1

$ErrorActionPreference = 'Stop'

$RepoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $RepoRoot) { throw 'Not inside a Git repository.' }

$HookPath = (& git -C $RepoRoot rev-parse --git-path hooks/pre-push).Trim()
if ([IO.Path]::IsPathRooted($HookPath)) {
    $HookFile = $HookPath
} else {
    $HookFile = Join-Path $RepoRoot $HookPath
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $HookFile) | Out-Null

# Git on Windows runs hooks via Git Bash, so the hook body must be bash.
$HookBody = @'
#!/usr/bin/env bash
# Pre-push: sweep recent Antigravity / Gemini prompts, then submit AI logs.
bash scripts/_pyrun.sh scripts/log_antigravity.py --auto || true
bash scripts/_pyrun.sh scripts/submit_log.py || true
exit 0
'@

$HookBody = $HookBody -replace "`r`n", "`n"
[IO.File]::WriteAllText($HookFile, $HookBody, [Text.UTF8Encoding]::new($false))
Write-Host "[ai-log] Git pre-push hook installed."

$LogDir = Join-Path $RepoRoot '.ai-log'
$GitKeep = Join-Path $LogDir '.gitkeep'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
if (-not (Test-Path $GitKeep)) { New-Item -ItemType File -Path $GitKeep | Out-Null }

Write-Host "[ai-log] Setup complete. Configure AI_LOG_SERVER in your .env file."
