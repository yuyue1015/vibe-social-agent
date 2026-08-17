[CmdletBinding()]
param(
    [string]$TargetRoot = (Get-Location).Path,
    [int]$Mode = 0,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path)
}

function Assert-Target([string]$Root, [string]$Candidate, [string]$Label) {
    $rootFull = (Get-FullPath $Root).TrimEnd('\')
    $candidateFull = Get-FullPath $Candidate
    $prefix = $rootFull + '\'
    if ($candidateFull -ne $rootFull -and -not $candidateFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label is outside the target project root."
    }
    if ($candidateFull -eq $rootFull -or $candidateFull -eq (Split-Path $rootFull -Parent)) {
        throw "Refusing to operate on a project root or its parent."
    }
    return $candidateFull
}

function Assert-NotReparsePoint([string]$Path, [string]$Label) {
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to remove a reparse-point target: $Label"
        }
    }
}

$target = Get-FullPath $TargetRoot
if (-not (Test-Path -LiteralPath $target -PathType Container)) {
    throw "Target project root does not exist or is not a directory."
}
Assert-NotReparsePoint $target "Target project root"

if ($Mode -eq 0) {
    Write-Host "[1] Remove both installed Skills and keep .vibesocial data"
    Write-Host "[2] Remove both Skills and .vibesocial data (requires a second confirmation)"
    Write-Host "[3] Cancel"
    $choice = Read-Host "Choose 1, 2, or 3"
    if ($choice -eq "1") { $Mode = 1 }
    elseif ($choice -eq "2") { $Mode = 2 }
    else { Write-Host "Cancelled."; exit 0 }
}

$skillRoot = Assert-Target $target (Join-Path $target ".agents\skills") "Skill directory"
Assert-NotReparsePoint (Join-Path $target ".agents") "Target .agents directory"
Assert-NotReparsePoint $skillRoot "Target Skill directory"
$targets = @(
    (Assert-Target $skillRoot (Join-Path $skillRoot "vibe-social") "vibe-social Skill"),
    (Assert-Target $skillRoot (Join-Path $skillRoot "weibo-publish") "weibo-publish Skill")
)
$dataPath = Assert-Target $target (Join-Path $target ".vibesocial") ".vibesocial data"
if ($Mode -eq 2) {
    $confirm = Read-Host "Type DELETE to include .vibesocial data"
    if ($confirm -cne "DELETE") { Write-Host "Cancelled."; exit 0 }
    $targets += $dataPath
}

foreach ($path in $targets) {
    Assert-NotReparsePoint $path $path
}
if ($Mode -eq 2) {
    Write-Host "这是完整删除模式。"
    Write-Host ".vibesocial/ 中的个人数据将永久删除，包括可能存在的："
    Write-Host "- 草稿"
    Write-Host "- Writing Memory"
    Write-Host "- 审核/状态记录"
    Write-Host "- 系列状态"
    Write-Host "- 发布记录"
    Write-Host "删除后不会自动恢复。"
}
if (-not $Apply) {
    Write-Host "准备卸载 Vibe Social。"
    Write-Host "将删除："
    Write-Host "- .agents/skills/vibe-social/"
    Write-Host "- .agents/skills/weibo-publish/"
    if ($Mode -eq 2) {
        Write-Host "- .vibesocial/"
    }
    if ($Mode -eq 1) {
        Write-Host "将保留："
        Write-Host "- .vibesocial/"
    }
    Write-Host "不会删除："
    Write-Host "- .agents/"
    Write-Host "- .agents/skills/"
    Write-Host "- 其他 Skill"
    Write-Host "- 项目源码"
    Write-Host "- Git 历史"
    Write-Host "DRY RUN：未修改任何文件。"
    Write-Host "请使用 -Apply 执行卸载。"
    exit 0
}

Write-Host "正在卸载 Vibe Social。"
foreach ($path in $targets) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
Write-Host "已删除："
Write-Host "- .agents/skills/vibe-social/"
Write-Host "- .agents/skills/weibo-publish/"
if ($Mode -eq 1) {
    Write-Host "已保留："
    Write-Host "- .vibesocial/"
}
else {
    Write-Host "已删除："
    Write-Host "- .vibesocial/"
}
Write-Host "卸载完成。"
