#!/usr/bin/env python3
"""Guard project scan boundaries and estimate first-analysis cost without reading source contents."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from safe_io import (
    DEFAULT_SUBPROCESS_TIMEOUT,
    MAX_GIT_OUTPUT_BYTES,
    bounded_subprocess,
    is_reparse_point,
    validate_scan_root,
)


SKIP_DIRS = {
    ".git",
    ".vibesocial",
    ".venv",
    ".cache",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "output",
    "asset",
    "data",
    "target",
}
DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".adoc"}
DOC_NAMES = {"readme", "changelog", "license", "notice"}
SCOPE_REQUIRED = 3
CONFIRMATION_REQUIRED = 4
MAX_SCAN_FILES = 10_000
MAX_FILE_BYTES = 512 * 1024


@dataclass(frozen=True)
class TreeMetrics:
    file_count: int
    document_count: int
    skipped_files: int = 0
    skipped_bytes: int = 0


@dataclass(frozen=True)
class GitMetrics:
    root: str | None
    commit_count: int
    file_count: int
    scope: str | None


@dataclass(frozen=True)
class TokenEstimate:
    low: int
    high: int
    duration_low_minutes: int
    duration_high_minutes: int


def resolve_project_root(value: str) -> Path:
    return validate_scan_root(value)


def same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def git_root_for(project_root: Path) -> Path | None:
    result = bounded_subprocess(
        ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
        timeout=DEFAULT_SUBPROCESS_TIMEOUT,
        max_output_bytes=64 * 1024,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def relative_scope(project_root: Path, git_root: Path) -> str | None:
    try:
        relative = project_root.resolve().relative_to(git_root.resolve())
    except ValueError:
        return None
    return relative.as_posix() or None


def count_tree(root: Path) -> TreeMetrics:
    files = 0
    documents = 0
    skipped_files = 0
    skipped_bytes = 0
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [
            name for name in directories
            if name not in SKIP_DIRS
            and not name.startswith(".tmp-vibesocial-")
            and not is_reparse_point(Path(current) / name)
        ]
        for name in filenames:
            path = Path(current) / name
            if is_reparse_point(path):
                skipped_files += 1
                continue
            try:
                size = path.stat().st_size
            except OSError:
                skipped_files += 1
                continue
            if size > MAX_FILE_BYTES or files >= MAX_SCAN_FILES:
                skipped_files += 1
                skipped_bytes += max(0, size)
                continue
            files += 1
            stem = Path(name).stem.lower()
            if Path(name).suffix.lower() in DOC_SUFFIXES or stem in DOC_NAMES:
                documents += 1
    return TreeMetrics(file_count=files, document_count=documents, skipped_files=skipped_files, skipped_bytes=skipped_bytes)


def run_git_count(command: list[str]) -> int:
    result = bounded_subprocess(command, timeout=DEFAULT_SUBPROCESS_TIMEOUT, max_output_bytes=64 * 1024)
    if result.returncode != 0:
        return 0
    try:
        return max(0, int(result.stdout.strip() or "0"))
    except ValueError:
        return 0


def count_git_files(git_root: Path, scope: str | None) -> int:
    command = [
        "git", "-C", str(git_root), "ls-files", "-z",
        "--cached", "--others", "--exclude-standard",
    ]
    if scope:
        command.extend(["--", scope])
    result = bounded_subprocess(command, timeout=DEFAULT_SUBPROCESS_TIMEOUT, max_output_bytes=MAX_GIT_OUTPUT_BYTES)
    if result.returncode != 0:
        return 0
    return min(MAX_SCAN_FILES, result.stdout.count("\0"))


def collect_git_metrics(project_root: Path, git_root: Path | None, selected_scope: str) -> GitMetrics:
    if git_root is None:
        return GitMetrics(root=None, commit_count=0, file_count=0, scope=None)

    scope = None if selected_scope == "workspace" else relative_scope(project_root, git_root)
    command = ["git", "-C", str(git_root), "rev-list", "--count", "--all"]
    if scope:
        command.extend(["--", scope])
    return GitMetrics(
        root=str(git_root),
        commit_count=run_git_count(command),
        file_count=count_git_files(git_root, scope),
        scope=scope,
    )


def estimate_tokens(tree: TreeMetrics, git: GitMetrics) -> TokenEstimate:
    """Estimate metadata and bounded-summary input, not raw source-code tokens."""
    low = 1_500 + tree.file_count * 8 + tree.document_count * 120 + git.file_count * 4 + git.commit_count * 40
    high = 5_000 + tree.file_count * 32 + tree.document_count * 500 + git.file_count * 16 + git.commit_count * 160
    high = max(high, low)
    return TokenEstimate(
        low=low,
        high=high,
        duration_low_minutes=max(1, math.ceil(low / 40_000)),
        duration_high_minutes=max(1, math.ceil(high / 10_000)),
    )


def build_result(project_root: Path, scope: str | None, confirm_large_scan: bool) -> dict[str, Any]:
    git_root = git_root_for(project_root)
    if git_root is not None and not same_path(git_root, project_root) and scope not in {"project", "workspace"}:
        return {
            "status": "scope_required",
            "project_root": str(project_root),
            "git_root": str(git_root),
            "message": "检测到父级 Git 工作区。",
            "options": [
                "[1] 只分析当前项目目录（默认）",
                "[2] 分析整个工作区",
                "[3] 取消",
            ],
        }

    selected_scope = scope or "project"
    if git_root is None and selected_scope == "workspace":
        selected_scope = "project"
    scan_root = git_root if selected_scope == "workspace" and git_root is not None else project_root
    tree = count_tree(scan_root)
    git = collect_git_metrics(project_root, git_root, selected_scope)
    estimate = estimate_tokens(tree, git)
    confirmation_required = estimate.high > 100_000 and not confirm_large_scan
    warning = None
    if estimate.high > 100_000:
        warning = "预计首次分析超过 100k tokens，必须获得用户明确确认后才能继续。"
    elif estimate.high > 50_000:
        warning = "预计首次分析超过 50k tokens，请提醒用户确认分析规模和耗时。"

    return {
        "status": "confirmation_required" if confirmation_required else "ready",
        "project_root": str(project_root),
        "scan_root": str(scan_root),
        "scope": selected_scope,
        "tree": asdict(tree),
        "git": asdict(git),
        "estimate": asdict(estimate),
        "warning": warning,
        "confirmation_required": confirmation_required,
        "note": "实际结果根据模型、网络速度和项目规模变化。",
    }


def format_number(value: int) -> str:
    return f"{value:,}"


def render_human(result: dict[str, Any]) -> str:
    if result["status"] == "scope_required":
        return "\n".join([
            "检测到父级 Git 工作区。",
            f"用户选择目录：{result['project_root']}",
            f"Git 根目录：{result['git_root']}",
            "",
            "请选择扫描范围：",
            *result["options"],
        ])

    tree = result["tree"]
    git = result["git"]
    estimate = result["estimate"]
    lines = [
        "项目规模：",
        f"- 用户选择目录：{result['project_root']}",
        f"- 实际扫描目录：{result['scan_root']}",
        f"- 文件数量：{format_number(tree['file_count'])}",
        f"- 文档数量：{format_number(tree['document_count'])}",
        "",
        "Git规模：",
        f"- Git根目录：{git['root'] or '未检测到 Git 仓库'}",
        f"- 提交数量：{format_number(git['commit_count'])}",
        f"- Git文件数量：{format_number(git['file_count'])}",
        f"- 当前范围：{'整个工作区' if result['scope'] == 'workspace' else '当前项目目录'}",
        "",
        "估算：",
        f"- Token范围：{format_number(estimate['low'])}–{format_number(estimate['high'])}",
        f"- 预计耗时：{estimate['duration_low_minutes']}–{estimate['duration_high_minutes']} 分钟",
        "",
        f"说明：{result['note']}",
    ]
    if tree.get("skipped_files"):
        lines.insert(5, f"- 安全跳过：{format_number(tree['skipped_files'])} 个文件，{format_number(tree.get('skipped_bytes', 0))} 字节")
    if result.get("warning"):
        lines.extend(["", f"提醒：{result['warning']}"])
    if result["status"] == "ready":
        lines.extend(["", "首次分析前置检查通过，可以继续。"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight", help="检查项目边界并估算首次分析规模")
    preflight.add_argument("--project-root", required=True)
    preflight.add_argument("--scope", choices=("project", "workspace"))
    preflight.add_argument("--confirm-large-scan", action="store_true")
    preflight.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        project_root = resolve_project_root(args.project_root)
        result = build_result(project_root, args.scope, args.confirm_large_scan)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_human(result))
    if result["status"] == "scope_required":
        return SCOPE_REQUIRED
    if result["status"] == "confirmation_required":
        return CONFIRMATION_REQUIRED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
