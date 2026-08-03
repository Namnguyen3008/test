[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

if (-not $env:GEMINI_API_KEY) {
    throw "GEMINI_API_KEY is missing. Configure it without printing the value."
}

$required = @(
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-embedding-2",
    "gemini-embedding-001"
)

$headers = @{ "x-goog-api-key" = $env:GEMINI_API_KEY }
$response = Invoke-RestMethod `
    -Method Get `
    -Uri "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000" `
    -Headers $headers

$available = @{}
foreach ($model in $response.models) {
    $id = ($model.name -replace '^models/', '')
    $available[$id] = $model
}

$missing = @()
foreach ($id in $required) {
    if ($available.ContainsKey($id)) {
        Write-Host "AVAILABLE: $id"
    } else {
        Write-Host "MISSING:   $id"
        $missing += $id
    }
}

if ($missing.Count -gt 0) {
    throw "The configured Gemini project cannot see all required models: $($missing -join ', ')"
}

Write-Host "All required Gemini model IDs are available. API key value was not displayed."
