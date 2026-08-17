#!/usr/bin/env python3
"""Read-only environment diagnostics for the Vibe Social Agent bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_REFERENCES = (
    "getting-started.md",
    "scan-boundary.md",
    "privacy-policy.md",
    "workflow.md",
    "interaction-flow.md",
    "data-contracts.md",
    "development-story.md",
    "story-ranking.md",
    "story-journey.md",
    "series-state.md",
    "writing-memory.md",
    "performance-learning.md",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a Vibe Social Agent installation.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Target project root")
    return parser.parse_args()


def check_skill(skill_root: Path, name: str) -> tuple[bool, dict[str, str]]:
    skill_dir = skill_root / name
    skill_file = skill_dir / "SKILL.md"
    agent_file = skill_dir / "agents" / "openai.yaml"
    checks: dict[str, str] = {
        "directory": "PASS" if skill_dir.is_dir() else "FAIL",
        "SKILL.md": "PASS" if skill_file.is_file() else "FAIL",
        "agents/openai.yaml": "PASS" if agent_file.is_file() else "FAIL",
    }
    if skill_file.is_file():
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        checks["frontmatter"] = "PASS" if text.startswith("---\n") else "FAIL"
        checks["name_matches_directory"] = (
            "PASS" if f"name: {name}" in text else "WARN"
        )
    if name == "vibe-social" and skill_dir.is_dir():
        refs = skill_dir / "references"
        checks["required_references"] = (
            "PASS"
            if all((refs / reference).is_file() for reference in REQUIRED_REFERENCES)
            else "FAIL"
        )
    return all(value == "PASS" for value in checks.values() if value != "WARN"), checks


def writable_state(root: Path) -> str:
    state = root / ".vibesocial"
    probe = state if state.exists() else root
    return "PASS" if probe.is_dir() and os.access(probe, os.W_OK) else "FAIL"


def weibo_check() -> tuple[str, dict[str, str]]:
    checks: dict[str, str] = {}
    cli = shutil.which("weibo-cli") or shutil.which("weibo-cli.ps1")
    if not cli:
        checks["weibo-cli"] = "WARN_MISSING_OPTIONAL_DEPENDENCY"
        return "WARN", checks

    checks["weibo-cli"] = "PASS"
    cli_path = Path(cli)
    command: list[str]
    if cli_path.suffix.lower() == ".ps1":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            checks["powershell_for_ps1"] = "FAIL"
            return "FAIL", checks
        checks["powershell_for_ps1"] = "PASS"
        command = [shell, "-NoProfile", "-File", str(cli_path), "doctor"]
    else:
        command = [str(cli_path), "doctor"]

    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        checks["credential_environment"] = "WARN_UNAVAILABLE"
        return "WARN", checks
    checks["credential_environment"] = "PASS" if result.returncode == 0 else "WARN_UNAVAILABLE"
    return ("PASS" if result.returncode == 0 else "WARN"), checks


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(json.dumps({"overall": "FAIL", "error": "target root is not a directory"}))
        return 1

    skill_root = root / ".agents" / "skills"
    core_checks: dict[str, str] = {
        "python_3_11_or_newer": "PASS"
        if sys.version_info >= (3, 11)
        else "FAIL",
        "git": "PASS" if shutil.which("git") else "FAIL",
        "state_writable": writable_state(root),
    }
    skill_results = {}
    for name in ("vibe-social", "weibo-publish"):
        ok, checks = check_skill(skill_root, name)
        skill_results[name] = {"status": "PASS" if ok else "FAIL", "checks": checks}
    core_ok = all(value == "PASS" for value in core_checks.values()) and all(
        result["status"] == "PASS" for result in skill_results.values()
    )
    weibo_status, weibo_checks = weibo_check()
    result = {
        "overall": "PASS" if core_ok and weibo_status == "PASS" else ("WARN" if core_ok else "FAIL"),
        "core": {"status": "PASS" if core_ok else "FAIL", "checks": core_checks},
        "skills": skill_results,
        "weibo": {"status": weibo_status, "checks": weibo_checks},
        "notes": [
            "Diagnostics are read-only.",
            "The core Skill does not require weibo-cli.",
            "Production publishing uses shell=False; Git Bash and ANSI-C quoting are not required.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if core_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
