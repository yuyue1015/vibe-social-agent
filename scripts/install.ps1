[CmdletBinding()]
param(
    [string]$TargetRoot = (Get-Location).Path,
    [switch]$Apply,
    [switch]$Update
)

$ErrorActionPreference = "Stop"

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path)
}

function Assert-Directory([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label does not exist or is not a directory: $Path"
    }
}

function Assert-Within([string]$Root, [string]$Candidate, [string]$Label) {
    $rootFull = (Get-FullPath $Root).TrimEnd('\')
    $candidateFull = Get-FullPath $Candidate
    $prefix = $rootFull + '\'
    if ($candidateFull -ne $rootFull -and -not $candidateFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label is outside the target root."
    }
    return $candidateFull
}

function Assert-NotReparsePoint([string]$Path, [string]$Label) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to replace a reparse-point target: $Label"
        }
    }
}

function Copy-SkillWithoutPythonCache([string]$Source, [string]$Destination) {
    $files = Get-ChildItem -LiteralPath $Source -Recurse -Force -File | Where-Object {
        $relative = $_.FullName.Substring($Source.Length).TrimStart('\')
        $parts = $relative.Split('\')
        $parts -notcontains '__pycache__' -and $_.Extension.ToLowerInvariant() -notin @('.pyc', '.pyo')
    }
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($Source.Length).TrimStart('\')
        $destinationFile = Join-Path $Destination $relative
        $destinationParent = Split-Path -Parent $destinationFile
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destinationFile -Force
    }
}

$repoRoot = Get-FullPath (Split-Path -Parent $PSScriptRoot)
$target = Get-FullPath $TargetRoot
Assert-Directory $repoRoot "Repository root"
Assert-Directory $target "Target project root"
Assert-NotReparsePoint $target "Target project root"

$sourceRoot = Join-Path $repoRoot ".agents\skills"
$sourceSkills = @("vibe-social", "weibo-publish")
foreach ($skillName in $sourceSkills) {
    Assert-Directory (Join-Path $sourceRoot $skillName) "Source Skill $skillName"
}

$targetSkillsRoot = Assert-Within $target (Join-Path $target ".agents\skills") "Skill destination root"
Assert-NotReparsePoint (Join-Path $target ".agents") "Target .agents directory"
Assert-NotReparsePoint $targetSkillsRoot "Target Skill directory"
$destinations = @{}
foreach ($skillName in $sourceSkills) {
    $destinations[$skillName] = Assert-Within $targetSkillsRoot (Join-Path $targetSkillsRoot $skillName) "Skill destination $skillName"
}

$operation = if ($Update) { "safe update" } else { "install" }
Write-Host "Vibe Social Agent $operation"
Write-Host "Target: project root (personal paths are not persisted by this script)"
Write-Host "The following Skill directories will be copied: vibe-social, weibo-publish"
Write-Host "Preserved: .vibesocial, source files, Git history, and unrelated Skills"
if (-not $Apply) {
    Write-Host "DRY RUN: no files changed. Re-run with -Apply to continue."
    exit 0
}

New-Item -ItemType Directory -Path $targetSkillsRoot -Force | Out-Null
foreach ($skillName in $sourceSkills) {
    $source = Join-Path $sourceRoot $skillName
    $destination = $destinations[$skillName]
    Assert-NotReparsePoint $destination "Skill destination $skillName"
    if (Test-Path -LiteralPath $destination) {
        Remove-Item -LiteralPath $destination -Recurse -Force
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-SkillWithoutPythonCache $source $destination
}

Write-Host "Installed/updated both Skills. Existing .vibesocial data was not touched."
