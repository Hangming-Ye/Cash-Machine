[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OutputPath,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Show-Usage {
    @'
Create a deterministic, allowlisted Cash Research release ZIP.

Usage:
  pwsh -NoProfile -File scripts/install.ps1 `
    -OutputPath <absolute-project-path>\tmp\releases\cash-research-<version>.zip

Options:
  -Root <path>        Project root. Defaults to the parent of scripts/.
  -OutputPath <path>  New .zip under <Root>/tmp/releases. Existing files are refused.
  -Help               Show this help without writing files.
'@
}

if ($Help -or [string]::IsNullOrWhiteSpace($OutputPath)) {
    Show-Usage
    return
}

function Assert-ContainedPath {
    param([string]$Path, [string]$Parent, [string]$Label)
    $parentPrefix = $Parent.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $Path.StartsWith($parentPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must remain inside the project root"
    }
}

function Assert-NoReparseRelativePath {
    param([string]$ProjectRoot, [string]$RelativePath, [string]$Label)
    $current = $ProjectRoot
    foreach ($part in $RelativePath.Replace('\', '/').Split('/')) {
        if ([string]::IsNullOrWhiteSpace($part)) { continue }
        $current = Join-Path $current $part
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label cannot contain a symlink, junction, or reparse point: $RelativePath"
            }
        }
    }
}

function Assert-TreeHasNoReparsePoint {
    param([string]$Directory, [string]$ProjectRoot, [string]$Label)
    $relativeRoot = [IO.Path]::GetRelativePath($ProjectRoot, $Directory)
    Assert-NoReparseRelativePath -ProjectRoot $ProjectRoot -RelativePath $relativeRoot -Label $Label
    $pending = [Collections.Generic.Queue[string]]::new()
    $pending.Enqueue($Directory)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        foreach ($item in Get-ChildItem -LiteralPath $current -Force) {
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label cannot contain a symlink, junction, or reparse point"
            }
            if ($item.PSIsContainer) {
                $pending.Enqueue($item.FullName)
            }
        }
    }
}

function Resolve-OrCreateDirectory {
    param([string]$Candidate, [string]$ProjectRoot, [string]$Label)
    if (Test-Path -LiteralPath $Candidate) {
        $item = Get-Item -LiteralPath $Candidate -Force
        if (-not $item.PSIsContainer) {
            throw "$Label must be a directory"
        }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label cannot be a symlink, junction, or reparse point"
        }
    }
    else {
        New-Item -ItemType Directory -Path $Candidate | Out-Null
    }
    $resolved = (Resolve-Path -LiteralPath $Candidate).Path
    Assert-ContainedPath -Path $resolved -Parent $ProjectRoot -Label $Label
    return $resolved
}

$rootItem = Get-Item -LiteralPath $Root -Force
if (-not $rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'Root must be a real project directory, not a symlink, junction, or reparse point'
}
$rootPath = (Resolve-Path -LiteralPath $Root).Path
if (-not (Test-Path -LiteralPath (Join-Path $rootPath 'pyproject.toml') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $rootPath 'uv.lock') -PathType Leaf)) {
    throw 'Root must contain pyproject.toml and uv.lock'
}

$tmpPath = Resolve-OrCreateDirectory -Candidate (Join-Path $rootPath 'tmp') -ProjectRoot $rootPath -Label 'tmp directory'
$releasePath = Resolve-OrCreateDirectory -Candidate (Join-Path $tmpPath 'releases') -ProjectRoot $rootPath -Label 'release directory'

if (-not [IO.Path]::IsPathRooted($OutputPath)) {
    throw 'OutputPath must be absolute'
}
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
if ([IO.Path]::GetExtension($outputFullPath) -ne '.zip') {
    throw 'OutputPath must end in .zip'
}
if (-not [string]::Equals([IO.Path]::GetDirectoryName($outputFullPath), $releasePath, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputPath must be directly under <Root>/tmp/releases'
}
Assert-ContainedPath -Path $outputFullPath -Parent $rootPath -Label 'OutputPath'
if (Test-Path -LiteralPath $outputFullPath) {
    throw 'OutputPath already exists; choose a new release version or filename'
}

$selected = @{}
function Add-ReleaseFile {
    param([string]$RelativePath)
    $normalized = $RelativePath.Replace('\', '/')
    if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized.StartsWith('/') -or $normalized.Split('/') -contains '..') {
        throw 'Release allowlist contains an unsafe relative path'
    }
    $candidate = Join-Path $rootPath $normalized
    Assert-NoReparseRelativePath -ProjectRoot $rootPath -RelativePath $normalized -Label 'release file'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Required release file is missing: $normalized"
    }
    $item = Get-Item -LiteralPath $candidate -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Release file cannot be a symlink or reparse point: $normalized"
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    Assert-ContainedPath -Path $resolved -Parent $rootPath -Label 'release file'
    $selected[$normalized] = $resolved
}

$requiredFiles = @(
    'pyproject.toml',
    'uv.lock',
    'config/settings.example.json',
    'scripts/install.ps1',
    'scripts/run_fixtures.py',
    'docs/deployment.md',
    'fixtures/README.md',
    'fixtures/scenarios/manifest.json',
    'bot-kit/README.md',
    'bot-kit/prompts/common.md',
    'bot-kit/prompts/chief.md',
    'bot-kit/prompts/research.md',
    'bot-kit/prompts/market.md',
    'bot-kit/prompts/quant.md',
    'bot-kit/prompts/reviewer.md',
    'bot-kit/skills/research-memory/SKILL.md',
    'bot-kit/skills/research-entry/SKILL.md',
    'bot-kit/skills/source-followup/SKILL.md',
    'bot-kit/skills/portfolio-research/SKILL.md',
    'bot-kit/templates/task-brief.md',
    'bot-kit/templates/report.md',
    'bot-kit/templates/review.md',
    'bot-kit/tasks/review.md',
    'bot-kit/tasks/retrospective.md',
    'bot-kit/tasks/event-impact.md',
    'bot-kit/tasks/valuation.md',
    'bot-kit/tasks/decision-brief.md'
)
foreach ($relative in $requiredFiles) {
    Add-ReleaseFile -RelativePath $relative
}

$sourceRoot = Join-Path $rootPath 'src/cash_research'
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw 'Required package source directory is missing: src/cash_research'
}
Assert-TreeHasNoReparsePoint -Directory $sourceRoot -ProjectRoot $rootPath -Label 'package source tree'
foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Filter '*.py') {
    if ($file.FullName -notmatch '[\\/]__pycache__[\\/]') {
        Add-ReleaseFile -RelativePath ([IO.Path]::GetRelativePath($rootPath, $file.FullName))
    }
}

$fixtureRules = [ordered]@{
    'fixtures/requests' = @('.json')
    'fixtures/scenarios' = @('.json', '.csv', '.md')
    'fixtures/memory' = @('.json', '.csv', '.md')
    'fixtures/sources' = @('.json', '.xml', '.csv', '.md')
    'fixtures/brokers' = @('.json', '.xml', '.csv', '.md')
    'fixtures/ingest' = @('.md', '.txt', '.json', '.csv')
    'fixtures/valuation' = @('.json')
    'fixtures/factors' = @('.json', '.csv')
    'fixtures/reports' = @('.json', '.md', '.txt', '.csv')
}
foreach ($rule in $fixtureRules.GetEnumerator()) {
    $directory = Join-Path $rootPath $rule.Key
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        continue
    }
    Assert-TreeHasNoReparsePoint -Directory $directory -ProjectRoot $rootPath -Label 'fixture tree'
    foreach ($file in Get-ChildItem -LiteralPath $directory -Recurse -File) {
        if ($rule.Value -contains $file.Extension.ToLowerInvariant()) {
            Add-ReleaseFile -RelativePath ([IO.Path]::GetRelativePath($rootPath, $file.FullName))
        }
    }
}

$utf8 = [Text.UTF8Encoding]::new($false)
$snapshot = @()
$relativePaths = [string[]]$selected.Keys
[Array]::Sort($relativePaths, [StringComparer]::Ordinal)
foreach ($relative in $relativePaths) {
    $bytes = [IO.File]::ReadAllBytes($selected[$relative])
    $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    $snapshot += [PSCustomObject]@{
        Path = $relative
        Bytes = $bytes
        Size = $bytes.Length
        Sha256 = $hash
    }
}

$pyproject = $snapshot | Where-Object Path -eq 'pyproject.toml'
$pyprojectText = $utf8.GetString($pyproject.Bytes)
$versionMatch = [regex]::Match($pyprojectText, '(?m)^version\s*=\s*"([^"]+)"\s*$')
$pythonMatch = [regex]::Match($pyprojectText, '(?m)^requires-python\s*=\s*"([^"]+)"\s*$')
if (-not $versionMatch.Success -or -not $pythonMatch.Success) {
    throw 'pyproject.toml must declare project version and requires-python'
}

$manifestFiles = @(
    foreach ($item in $snapshot) {
        [ordered]@{ path = $item.Path; size = $item.Size; sha256 = $item.Sha256 }
    }
)
$manifest = [ordered]@{
    schema_version = '1.0'
    package_name = 'cash-research'
    package_version = $versionMatch.Groups[1].Value
    python_requirement = $pythonMatch.Groups[1].Value
    installation = 'manual-uv-sync-locked'
    files = $manifestFiles
}
$manifestBytes = $utf8.GetBytes(($manifest | ConvertTo-Json -Depth 6) + "`n")

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$createdOutput = $false
try {
    $fileStream = [IO.File]::Open($outputFullPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $createdOutput = $true
    try {
        $archive = [IO.Compression.ZipArchive]::new($fileStream, [IO.Compression.ZipArchiveMode]::Create, $false)
        try {
            $fixedTime = [DateTimeOffset]::new(2000, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
            foreach ($item in $snapshot) {
                $entry = $archive.CreateEntry($item.Path, [IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime = $fixedTime
                $entryStream = $entry.Open()
                try { $entryStream.Write($item.Bytes, 0, $item.Bytes.Length) }
                finally { $entryStream.Dispose() }
            }
            $manifestEntry = $archive.CreateEntry('release-manifest.json', [IO.Compression.CompressionLevel]::Optimal)
            $manifestEntry.LastWriteTime = $fixedTime
            $manifestStream = $manifestEntry.Open()
            try { $manifestStream.Write($manifestBytes, 0, $manifestBytes.Length) }
            finally { $manifestStream.Dispose() }
        }
        finally { $archive.Dispose() }
    }
    finally { $fileStream.Dispose() }
}
catch {
    if ($createdOutput -and (Test-Path -LiteralPath $outputFullPath -PathType Leaf)) {
        Remove-Item -LiteralPath $outputFullPath -Force
    }
    throw
}

$bundleHash = (Get-FileHash -LiteralPath $outputFullPath -Algorithm SHA256).Hash.ToLowerInvariant()
[ordered]@{
    output_path = $outputFullPath
    package_version = $versionMatch.Groups[1].Value
    file_count = $snapshot.Count
    sha256 = $bundleHash
} | ConvertTo-Json -Compress
