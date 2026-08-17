#!/usr/bin/env python3
"""Check that the repository is safe to package as a public Skill release."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


TOP_LEVEL_DIRS = {".agents", ".github", "docs", "evals", "fixtures", "scripts", "tests"}
TOP_LEVEL_FILES = {
    "README.md",
    "SECURITY.md",
    "LICENSE",
    "AGENTS.md",
    ".gitignore",
    "pyproject.toml",
    "CHANGELOG.md",
}
FORBIDDEN_NAMES = {
    ".vibesocial",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    ".coverage",
    "htmlcov",
    ".venv",
}
FORBIDDEN_PACKAGE_FILES = {"README", "INSTALL", "CHANGELOG", "QUICK_REFERENCE"}
SECRET_PATTERNS = (
    re.compile("-" * 5 + r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY" + "-" * 5),
    re.compile(r"\b(?:s" + r"k|ghp|github_pat|xoxb)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password|credential)\s*[=:]\s*[\"'][^\"']{8,}[\"']"),
    re.compile("(?i)[A-Za-z]:[\\\\/]+" + "Users" + "[\\\\/]+[^\\s\\\"'/]+"),
    re.compile(
        "(?:"
        + re.escape("/" + "Users/")
        + "|"
        + re.escape("/" + "home/")
        + "|"
        + re.escape("/" + "var/")
        + r")[^\s\"'/]+"
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run release packaging checks.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="Emit JSON (default output is also JSON)")
    return parser.parse_args()


def git_root(root: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "git root could not be determined"
    actual = Path(result.stdout.strip()).resolve() if result.returncode == 0 else None
    return actual == root, "independent repository root matches project" if actual == root else "project is nested in another Git root"


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    failures: list[str] = []
    warnings: list[str] = []
    checks: dict[str, str] = {}

    boundary_ok, boundary_message = git_root(root)
    checks["independent_git_boundary"] = "PASS" if boundary_ok else "FAIL"
    if not boundary_ok:
        failures.append(boundary_message)
    checks["LICENSE"] = "PASS" if (root / "LICENSE").is_file() else "FAIL"
    if checks["LICENSE"] == "FAIL":
        failures.append("LICENSE is missing")

    for path in root.rglob("*"):
        if ".git" in path.relative_to(root).parts:
            continue
        rel = relative(path, root)
        parts = set(path.relative_to(root).parts)
        if (
            parts & FORBIDDEN_NAMES
            or path.name.startswith(".env")
            or path.suffix.lower() in {".token", ".log", ".pyc", ".pyo"}
        ):
            failures.append(f"forbidden release artifact: {rel}")
            continue
        if len(path.relative_to(root).parts) == 1 and path.is_file() and path.name not in TOP_LEVEL_FILES:
            failures.append(f"top-level file is outside release allowlist: {rel}")
        if len(path.relative_to(root).parts) == 1 and path.is_dir() and path.name not in TOP_LEVEL_DIRS:
            failures.append(f"top-level directory is outside release allowlist: {rel}")
        if rel.startswith("evals/results/") and path.name != ".gitignore":
            failures.append(f"local eval result is not releasable: {rel}")
        if rel.startswith(".agents/skills/") and path.is_file():
            stem = path.stem.upper()
            if stem in FORBIDDEN_PACKAGE_FILES:
                failures.append(f"repository document inside Skill package: {rel}")

        # Tests and eval fixtures intentionally contain fake secrets and attack paths;
        # they are not runtime or personal data and are covered by the test suite.
        scan_for_secrets = not (rel.startswith("tests/") or rel.startswith("evals/"))
        if scan_for_secrets and path.is_file() and path.stat().st_size <= 2_000_000:
            data = path.read_bytes()
            if b"\0" not in data:
                text = data.decode("utf-8", errors="replace")
                for pattern in SECRET_PATTERNS:
                    if pattern.search(text):
                        failures.append(f"possible secret or personal path in release file: {rel}")
                        break

    if not (root / ".agents" / "skills" / "vibe-social" / "SKILL.md").is_file():
        failures.append("vibe-social Skill is missing")
    if not (root / ".agents" / "skills" / "weibo-publish" / "SKILL.md").is_file():
        failures.append("weibo-publish Skill is missing")
    checks["release_allowlist_and_clean_tree"] = "PASS" if not failures else "FAIL"
    checks["skill_bundle"] = "PASS" if not any("Skill is missing" in item for item in failures) else "FAIL"

    result = {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": sorted(set(failures)),
        "warnings": warnings,
        "notes": ["Only repository-relative paths are reported."],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
