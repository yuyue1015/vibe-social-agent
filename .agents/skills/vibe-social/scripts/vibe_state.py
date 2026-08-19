#!/usr/bin/env python3
"""Deterministic local state manager for the VibeSocial V0.1 workflow."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from safe_io import SafetyError, safe_error, safe_join, safe_state_record_path, validate_scan_root, validate_social_commit_id, validate_social_pr_id
except ModuleNotFoundError:  # Loaded by the independent weibo-publish script.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from safe_io import SafetyError, safe_error, safe_join, safe_state_record_path, validate_scan_root, validate_social_commit_id, validate_social_pr_id


VERSION = 1
PRESETS = {"default", "casual-weibo", "developer-log", "storytelling", "product-update", "technical-explainer"}
MEMORY_FILES = (
    "writing-style.md",
    "anti-ai-patterns.md",
    "approved-examples.md",
    "feedback-log.md",
    "series-state.md",
)
PERFORMANCE_FILES = (
    "performance-log.jsonl",
    "performance-insights.md",
    "performance-baseline.json",
)
EVENT_REQUIRED = {"type", "summary", "problem", "change", "user_value", "public_safe"}
EVENT_ALLOWED = EVENT_REQUIRED | {"evidence"}
PUBLISH_READINESS_STATUSES = {"ready", "hold", "skip"}
COMPLETION_LEVELS = {"complete", "validated", "exploring", "unknown"}
FACTUAL_EDIT_REQUEST = re.compile(
    r"(?:事实|数字|数值|准确|核实|重新扫描|查一下源码|源码|这个事实不对|"
    r"verify|fact|number|accurate|rescan|source code)",
    re.IGNORECASE,
)
NUMBER_TOKEN = re.compile(r"(?<![\w.])\d+(?:\.\d+)?%?")
FORBIDDEN_KEYS = re.compile(r"(?:token|secret|password|passwd|cookie|api[_-]?key|credential|private[_-]?key)", re.I)
FORBIDDEN_TEXT = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/\S+", re.I),
    re.compile(r"\b[A-Za-z]:\\(?:[^\s\\]+\\)+[^\s]*"),
    re.compile(r"(?<![\w.])/(?:home|Users|var|etc|srv|opt)/[^\s]+"),
]


class StateError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(f"Missing state file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StateError(f"Invalid JSON in {path}: {exc}") from exc


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.rstrip() + "\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def memory_source_root() -> Path:
    return Path(__file__).resolve().parents[1] / "references"


def ensure_memory_files(root: Path) -> None:
    memory_root = safe_join(root, ".vibesocial")
    memory_root.mkdir(parents=True, exist_ok=True)
    for name in MEMORY_FILES:
        target = safe_join(root, f".vibesocial/{name}")
        if target.exists():
            continue
        source = memory_source_root() / name
        if source.exists():
            atomic_text(target, source.read_text(encoding="utf-8"))
        else:
            atomic_text(target, f"# {name.removesuffix('.md')}\n")


def ensure_performance_files(root: Path) -> None:
    """Create empty, explicitly observation-only performance state."""
    performance_root = safe_join(root, ".vibesocial")
    performance_root.mkdir(parents=True, exist_ok=True)
    log_path = safe_join(root, ".vibesocial/performance-log.jsonl")
    if not log_path.exists():
        atomic_text(log_path, "")
    insights_path = safe_join(root, ".vibesocial/performance-insights.md")
    if not insights_path.exists():
        atomic_text(insights_path, """# Performance insights

status: OBSERVATION_ONLY
minimum_posts: 5

No performance pattern is inferred until at least 5 distinct published posts have usable snapshots.
Performance signals are reference-only and never override Writing CORE, series planning, or factuality.
""")
    baseline_path = performance_root / "performance-baseline.json"
    if not baseline_path.exists():
        atomic_json(baseline_path, {
            "schema_version": 1,
            "minimum_posts": 5,
            "minimum_snapshots": 5,
            "status": "OBSERVATION_ONLY",
            "post_count": 0,
            "snapshot_count": 0,
            "metric_keys": [],
        })


def memory_path(root: Path, name: str) -> Path:
    if name not in MEMORY_FILES:
        raise StateError(f"Unknown memory file: {name}")
    ensure_memory_files(root)
    return safe_join(root, f".vibesocial/{name}")


def append_memory(path: Path, block: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    separator = "\n" if existing.rstrip() else ""
    atomic_text(path, existing.rstrip() + separator + block.strip())


def read_learning_entries(path_value: str) -> list[dict[str, Any]]:
    raw = read_json(Path(path_value))
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise StateError("Learning file must contain an object or array")
    allowed = {
        "original_text", "original_sentence", "user_feedback", "final_text", "replacement",
        "inferred_rule", "rule_key", "scope", "confidence", "target", "tags", "promote_core",
        "series", "series_number",
    }
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise StateError(f"Learning entry {index} must be an object")
        extra = set(entry) - allowed
        if extra:
            raise StateError(f"Learning entry {index} has unsupported fields: {', '.join(sorted(extra))}")
        required = {"inferred_rule", "rule_key", "scope"}
        missing = required - set(entry)
        if missing:
            raise StateError(f"Learning entry {index} missing fields: {', '.join(sorted(missing))}")
        if entry["scope"] not in {"GLOBAL_STYLE", "SERIES_STYLE", "POST_SPECIFIC"}:
            raise StateError(f"Learning entry {index}.scope is invalid")
        if not isinstance(entry["inferred_rule"], str) or not entry["inferred_rule"].strip():
            raise StateError(f"Learning entry {index}.inferred_rule must be non-empty")
        if not isinstance(entry["rule_key"], str) or not entry["rule_key"].strip():
            raise StateError(f"Learning entry {index}.rule_key must be non-empty")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise StateError(f"Learning entry {index}.tags must be a list of strings")
        inspect_public(entry, f"learning[{index}]")
        entries.append(entry)
    return entries


def existing_rule_count(path: Path, rule_key: str) -> tuple[int, str | None]:
    if not path.exists():
        return 0, None
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n## ", text)
    matching = [block for block in blocks if re.search(rf"- rule_key: {re.escape(rule_key)}\s*$", block, flags=re.MULTILINE)]
    count = len(matching)
    status_match = [status for block in matching for status in re.findall(r"- status: (OBSERVED|REPEATED|CORE)", block)]
    return count, ("CORE" if "CORE" in status_match else "REPEATED" if "REPEATED" in status_match else "OBSERVED" if "OBSERVED" in status_match else None)


def existing_rule_variants(path: Path, rule_key: str) -> set[str]:
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n## ", text)
    variants: set[str] = set()
    for block in blocks:
        if re.search(rf"- rule_key: {re.escape(rule_key)}\s*$", block, flags=re.MULTILINE):
            match = re.search(r"- inferred_rule: ([^\n]+)", block)
            if match:
                variants.add(match.group(1).strip())
    return variants


def inferred_status(entry: dict[str, Any], count: int, previous_status: str | None) -> str:
    feedback = str(entry.get("user_feedback", ""))
    explicit = bool(entry.get("promote_core")) or any(token in feedback for token in ("以后都不要", "以后都要", "记住", "固定"))
    if previous_status == "CORE" or explicit or count >= 3:
        return "CORE"
    if count >= 2:
        return "REPEATED"
    return "OBSERVED"


def append_rule_if_core(root: Path, entry: dict[str, Any], status: str) -> None:
    if status != "CORE" or entry["scope"] == "POST_SPECIFIC":
        return
    target = entry.get("target")
    if target not in {"writing-style", "anti-ai-patterns", "series-state"}:
        target = "anti-ai-patterns" if entry["rule_key"].startswith("anti_ai.") else "writing-style"
    path = memory_path(root, f"{target}.md")
    marker = f"- [{entry['rule_key']}] {entry['inferred_rule']}"
    if marker not in path.read_text(encoding="utf-8"):
        append_memory(path, f"\n## Learned CORE rule\n\n{marker}")


def append_feedback(root: Path, commit_id: str, entry: dict[str, Any], count: int, status: str, conflict: str | None = None) -> None:
    path = memory_path(root, "feedback-log.md")
    timestamp = now()
    lines = [
        f"\n## Feedback — {commit_id} — {timestamp}",
        f"- Social Commit ID: {commit_id}",
        f"- timestamp: {timestamp}",
        f"- original_text / original_sentence: {entry.get('original_sentence') or entry.get('original_text') or 'not supplied'}",
        f"- user_feedback: {entry.get('user_feedback') or 'manual revision detected; no explicit note supplied'}",
        f"- final_text / replacement: {entry.get('replacement') or entry.get('final_text') or 'not supplied'}",
        f"- inferred_rule: {entry['inferred_rule']}",
        f"- rule_key: {entry['rule_key']}",
        f"- scope: {entry['scope']}",
        f"- count: {count}",
        f"- confidence: {entry.get('confidence', 'medium')}",
        f"- status: {status}",
    ]
    if conflict:
        lines.append(f"- conflict: {conflict}")
    append_memory(path, "\n".join(lines))


def update_series_state(root: Path, commit_id: str, series: str | None, series_number: int | None) -> None:
    path = memory_path(root, "series-state.md")
    text = path.read_text(encoding="utf-8")
    if series:
        text = re.sub(r"^series:.*$", f"series: {series}", text, flags=re.MULTILINE)
    if series_number is not None:
        text = re.sub(r"^current_number:.*$", f"current_number: {series_number:02d}", text, flags=re.MULTILINE)
    approved_match = re.search(r"^approved:\s*(.*)$", text, flags=re.MULTILINE)
    approved = []
    if approved_match and approved_match.group(1).strip() not in {"", "[]"}:
        approved = [item.strip() for item in approved_match.group(1).strip("[]").split(",") if item.strip()]
    if commit_id not in approved:
        approved.append(commit_id)
    replacement = "approved: [" + ", ".join(approved) + "]"
    if approved_match:
        text = text[:approved_match.start()] + replacement + text[approved_match.end():]
    else:
        text += f"\n{replacement}\n"
    atomic_text(path, text)


def append_manual_distribution_log(root: Path, commit_id: str, platform: str, published_at: str) -> None:
    path = safe_join(root, ".vibesocial/published-log.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "social_commit_id": commit_id,
            "platform": platform,
            "distribution_type": "manual",
            "published_at": published_at,
        }, ensure_ascii=False) + "\n")


def append_approved_example(root: Path, commit: dict[str, Any], pr: dict[str, Any], tags: list[str], series: str | None, series_number: int | None) -> None:
    path = memory_path(root, "approved-examples.md")
    existing = path.read_text(encoding="utf-8")
    if f"- Social Commit ID: {commit['id']}" in existing:
        return
    example = [
        f"\n## Approved example — {commit['id']}",
        f"- Social Commit ID: {commit['id']}",
        f"- series: {series or pr.get('series') or 'unassigned'}",
        f"- number: {series_number if series_number is not None else pr.get('series_number') or 'unassigned'}",
        f"- final_text: {pr['body']}",
        f"- approved_at: {pr.get('approved_at') or commit.get('approved_at') or now()}",
        f"- published_at: {commit.get('publish', {}).get('published_at', 'not published')}",
        f"- tags: {', '.join(tags or ['unclassified'])}",
    ]
    append_memory(path, "\n".join(example))


def basic_learning_entry(pr: dict[str, Any]) -> dict[str, Any] | None:
    first = pr.get("first_draft")
    final = pr.get("body")
    if not isinstance(first, str) or not isinstance(final, str) or first == final:
        return None
    diff = list(difflib.ndiff(first.splitlines(), final.splitlines()))
    removed = " ".join(line[2:] for line in diff if line.startswith("- "))
    added = " ".join(line[2:] for line in diff if line.startswith("+ "))
    feedback = "；".join(
        revision["feedback"] for revision in pr.get("revisions", [])
        if isinstance(revision, dict) and isinstance(revision.get("feedback"), str) and revision["feedback"].strip()
    )
    return {
        "original_text": first,
        "original_sentence": removed or first,
        "replacement": added or final,
        "final_text": final,
        "user_feedback": feedback or "Manual revision detected; no explicit semantic note was supplied.",
        "inferred_rule": "Prefer the approved replacement for this post; do not generalize without repeated evidence.",
        "rule_key": f"post_edit.{pr['id']}",
        "scope": "POST_SPECIFIC",
        "confidence": "low",
        "tags": [],
    }


def apply_learning(root: Path, commit: dict[str, Any], pr: dict[str, Any], learning_file: str | None) -> list[dict[str, Any]]:
    entries = read_learning_entries(learning_file) if learning_file else []
    if learning_file is None and not entries:
        fallback = basic_learning_entry(pr)
        entries = [fallback] if fallback else []
    applied: list[dict[str, Any]] = []
    log_path = memory_path(root, "feedback-log.md")
    for entry in entries:
        count, previous_status = existing_rule_count(log_path, entry["rule_key"])
        new_count = count + 1
        status = inferred_status(entry, new_count, previous_status)
        variants = existing_rule_variants(log_path, entry["rule_key"])
        conflict = None
        if variants and entry["inferred_rule"] not in variants:
            conflict = "Existing rule kept visible; latest explicit feedback wins for the current draft."
        append_feedback(root, commit["id"], entry, new_count, status, conflict)
        append_rule_if_core(root, entry, status)
        applied.append({"rule_key": entry["rule_key"], "scope": entry["scope"], "count": new_count, "status": status})
    return applied


def sentence_list(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?\n]+", text) if part.strip()]


def cmd_critique(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    text = Path(args.text_file).read_text(encoding="utf-8").strip()
    anti_path = memory_path(root, "anti-ai-patterns.md")
    anti_lines = [line[2:].strip().strip("`‘’“”\"") for line in anti_path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
    examples_path = memory_path(root, "approved-examples.md")
    approved_texts = re.findall(r"- final_text: ([^\n]+)", examples_path.read_text(encoding="utf-8"))
    series_text = memory_path(root, "series-state.md").read_text(encoding="utf-8")
    sentences = sentence_list(text)
    issues: list[dict[str, str]] = []
    if len(text) < 120 or len(text) > 240:
        issues.append({"key": "length", "message": "Draft is outside the approximate 150–200 character target."})
    if len(sentences) >= 3 and any(sentence in {"其实", "总之", "可以说", "值得一提的是"} for sentence in sentences):
        issues.append({"key": "deletable_sentence", "message": "A likely filler transition should be tested for deletion."})
    for pattern in anti_lines:
        normalized = pattern.replace("A", "").replace("B", "").replace("……", "").strip()
        if normalized and normalized in text:
            issues.append({"key": "anti_ai_pattern", "message": f"Review possible anti-AI pattern: {pattern}"})
    subjectless = [sentence for sentence in sentences if re.match(r"^(修复|完善|推进|优化|打通|增加|调整|完成|实现|继续)", sentence)]
    if subjectless:
        issues.append({"key": "missing_subject", "message": "Some task-like sentences may need an explicit actor."})
    if not re.search(
        r"\d|Bug|bug|测试|验证|结果|错误|公式|框架|审计|界面|按钮|页面|接口|命令|请求|输出|文件|模块|缓存|导出|用户动作|功能",
        text,
        re.IGNORECASE,
    ):
        issues.append({"key": "concrete_detail", "message": "No obvious concrete development detail was found."})
    if re.search(r"推进|完善|打通|赋能|结构化表达|工程化|显性化|持续优化|进一步提升", text):
        issues.append({"key": "report_voice", "message": "Draft may read like a project report instead of a concrete note."})
    if re.search(r"才发现|原来|第一次意识到|惊讶|意外的是", text):
        issues.append({"key": "invented_emotion", "message": "Check whether a discovery or surprise is factual rather than a story device."})
    jargon = re.findall(r"\b[A-Za-z][A-Za-z0-9_.-]{3,}\b", text)
    if len(jargon) >= 4:
        issues.append({"key": "developer_to_machine", "message": "Several technical tokens may need translation into reader-facing meaning."})
    if approved_texts:
        current_chars = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text))
        overlaps = []
        for example in approved_texts:
            chars = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", example))
            if current_chars and chars:
                overlaps.append(len(current_chars & chars) / max(1, len(current_chars | chars)))
        if overlaps and max(overlaps) >= 0.45:
            issues.append({"key": "repetition", "message": "Draft shares substantial vocabulary with an approved example; check series progression."})
    plan_lines = [line.strip(" -") for line in series_text.splitlines() if re.match(r"\d{1,2}[.)]", line.strip())]
    if plan_lines and any(line and line in text for line in plan_lines):
        issues.append({"key": "plan_leakage", "message": "Draft may be consuming a planned item without checking the current series number."})
    if re.search(r"所以|这意味着|总之|归根结底|最终我们", sentences[-1] if sentences else ""):
        issues.append({"key": "abstract_ending", "message": "Check whether the ending is forcing a summary or uplift."})
    return {"text_length": len(text), "issues": issues, "rewrite_required": bool(issues)}


def cmd_memory_context(args: argparse.Namespace) -> dict[str, Any]:
    root = validate_scan_root(args.root)
    ensure_performance_files(root)
    result = {name.removesuffix(".md"): memory_path(root, name).read_text(encoding="utf-8") for name in MEMORY_FILES}
    result["performance-insights"] = (root / ".vibesocial" / "performance-insights.md").read_text(encoding="utf-8")
    return result


def cmd_learn(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    require_initialized(root)
    _, pr = load_pr(root, args.pr)
    if pr.get("status") != "APPROVED":
        raise StateError("Learning requires an APPROVED Social PR")
    commit = read_json(safe_state_record_path(root / "social-commits", pr["social_commit_id"], validate_social_commit_id))
    learning = apply_learning(root.parent, commit, pr, args.learning_file)
    update_series_state(root.parent, commit["id"], args.series, args.series_number)
    return {"social_commit_id": commit["id"], "learning": learning}


def cmd_backfill_memory(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    require_initialized(root)
    ensure_memory_files(root.parent)
    examples = 0
    series_updates = 0
    for path in sorted(safe_join(root, "social-prs").glob("spr-*.json")):
        pr = read_json(path)
        if pr.get("status") != "APPROVED":
            continue
        commit_path = safe_state_record_path(root / "social-commits", pr["social_commit_id"], validate_social_commit_id)
        if not commit_path.exists():
            continue
        commit = read_json(commit_path)
        before = memory_path(root.parent, "approved-examples.md").read_text(encoding="utf-8")
        append_approved_example(root.parent, commit, pr, [], pr.get("series"), pr.get("series_number"))
        after = memory_path(root.parent, "approved-examples.md").read_text(encoding="utf-8")
        examples += int(before != after)
        update_series_state(root.parent, commit["id"], pr.get("series"), pr.get("series_number"))
        series_updates += 1
    return {"approved_examples_added": examples, "series_records_seen": series_updates}


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def cmd_backfill_history(args: argparse.Namespace) -> dict[str, Any]:
    """Backfill user-supplied historical facts without rewriting their text."""
    root = state_root(args.root)
    require_initialized(root)
    source = read_json(Path(args.history_file))
    if not isinstance(source, dict):
        raise StateError("History backfill must be an object")
    series = source.get("series")
    fixed_title = source.get("fixed_title")
    fixed_tags = source.get("fixed_tags")
    approved = source.get("approved")
    draft = source.get("draft")
    if not isinstance(series, str) or not series.strip():
        raise StateError("History backfill requires series")
    if not isinstance(fixed_title, str) or not fixed_title.strip():
        raise StateError("History backfill requires fixed_title")
    if not isinstance(fixed_tags, list) or any(not isinstance(tag, str) for tag in fixed_tags):
        raise StateError("History backfill requires fixed_tags")
    if not isinstance(approved, list) or not approved:
        raise StateError("History backfill requires approved entries")
    inspect_public(source, "history_backfill")
    ensure_memory_files(root.parent)
    ensure_performance_files(root.parent)

    examples_path = memory_path(root.parent, "approved-examples.md")
    examples_added = 0
    for item in approved:
        if not isinstance(item, dict) or not isinstance(item.get("number"), str) or not isinstance(item.get("final_text"), str):
            raise StateError("Each approved history entry needs string number and final_text")
        number = item["number"]
        marker = f"- Social Commit ID: historical-{number}"
        if marker in examples_path.read_text(encoding="utf-8"):
            continue
        tags = item.get("tags", fixed_tags)
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise StateError(f"Invalid tags for approved history entry {number}")
        block = "\n".join([
            f"\n## Approved historical example — historical-{number}",
            marker,
            f"- series: {series}",
            f"- number: {number}",
            "- final_text: " + item["final_text"],
            "- approved_at: historical confirmation; original timestamp not supplied",
            "- published_at: not supplied",
            "- tags: " + ", ".join(tags),
        ])
        append_memory(examples_path, block)
        examples_added += 1

    feedback_path = memory_path(root.parent, "feedback-log.md")
    feedback_added = 0
    for item in source.get("feedback", []):
        if not isinstance(item, dict):
            raise StateError("Each backfilled feedback entry must be an object")
        required = {"rule_key", "scope", "inferred_rule", "user_feedback"}
        if not required.issubset(item):
            raise StateError("Backfilled feedback is missing required fields")
        if item["scope"] not in {"GLOBAL_STYLE", "SERIES_STYLE", "POST_SPECIFIC"}:
            raise StateError("Invalid backfilled feedback scope")
        core_entry = dict(item)
        if "target" not in core_entry and core_entry["scope"] == "SERIES_STYLE":
            core_entry["target"] = "series-state"
        append_rule_if_core(root.parent, core_entry, item.get("status", "CORE"))
        commit_id = str(item.get("social_commit_id", "BACKFILL-HISTORY"))
        marker = f"- rule_key: {item['rule_key']}"
        if marker in feedback_path.read_text(encoding="utf-8") and f"- Social Commit ID: {commit_id}" in feedback_path.read_text(encoding="utf-8"):
            continue
        block = "\n".join([
            f"\n## Backfilled feedback — {commit_id} — 2026-08-15",
            f"- Social Commit ID: {commit_id}",
            "- timestamp: 2026-08-15 (backfill recorded now; original timestamp not supplied)",
            f"- original_text / original_sentence: {item.get('original_sentence', 'not supplied')}",
            f"- user_feedback: {item['user_feedback']}",
            f"- final_text / replacement: {item.get('replacement', 'not supplied')}",
            f"- inferred_rule: {item['inferred_rule']}",
            f"- rule_key: {item['rule_key']}",
            f"- scope: {item['scope']}",
            f"- count: {item.get('count', 1)}",
            f"- confidence: {item.get('confidence', 'high')}",
            f"- status: {item.get('status', 'CORE')}",
        ])
        append_memory(feedback_path, block)
        feedback_added += 1

    state_path = memory_path(root.parent, "series-state.md")
    plan = source.get("plan", {})
    if not isinstance(plan, dict):
        raise StateError("series plan must be an object keyed by article number")
    plan_lines = []
    for number in range(1, 51):
        key = f"{number:02d}"
        item = plan.get(key)
        if isinstance(item, dict):
            topic = item.get("topic")
            status = item.get("status")
        else:
            topic = item
            status = None
        plan_lines.append(f"  - number: {key}\n    topic: {_yaml_scalar(topic)}\n    status: {_yaml_scalar(status)}")
    approved_numbers = source.get("approved_numbers", [item.get("number") for item in approved])
    state_text = "\n".join([
        "# Series state",
        "",
        "series: " + series,
        "current_number: " + _yaml_scalar(source.get("current_number")),
        "approved: [" + ", ".join(str(item) for item in approved_numbers) + "]",
        "draft: " + _yaml_scalar(draft),
        "plan_complete: " + _yaml_scalar(source.get("plan_complete", False)),
        "fixed_title: " + fixed_title,
        "fixed_tags: [" + ", ".join(fixed_tags) + "]",
        "plan:",
        *plan_lines,
        "",
        "Notes:",
        "- This state was backfilled from user-supplied historical material.",
        "- Missing plan topics remain null; do not infer a next topic from the previous body.",
        "- The current draft is not an approved example until the user approves it.",
    ])
    atomic_text(state_path, state_text)
    return {
        "approved_examples_added": examples_added,
        "feedback_entries_added": feedback_added,
        "series": series,
        "current_number": source.get("current_number"),
        "draft": draft,
        "plan_slots": 50,
        "plan_topics_supplied": sum(1 for number in plan if plan[number] is not None),
    }


def state_root(value: str) -> Path:
    return safe_join(validate_scan_root(value), ".vibesocial")


def require_initialized(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config = read_json(safe_join(root, "config.json", must_exist=True))
    state = read_json(safe_join(root, "state.json", must_exist=True))
    if config.get("schema_version") != VERSION or state.get("schema_version") != VERSION:
        raise StateError("Unsupported VibeSocial state version")
    return config, state


def inspect_public(value: Any, trail: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if FORBIDDEN_KEYS.search(str(key)):
                raise StateError(f"Forbidden sensitive field at {trail}.{key}")
            inspect_public(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            inspect_public(item, f"{trail}[{index}]")
    elif isinstance(value, str):
        for pattern in FORBIDDEN_TEXT:
            if pattern.search(value):
                raise StateError(f"Potential sensitive content at {trail}")


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    config_path = safe_join(root, "config.json")
    state_path = safe_join(root, "state.json")
    if config_path.exists() or state_path.exists():
        require_initialized(root)
        return {"result": "already_initialized", "root": str(root)}
    if args.style not in PRESETS:
        raise StateError(f"Unknown style preset: {args.style}")
    root.mkdir(parents=True, exist_ok=True)
    safe_join(root, "social-commits").mkdir(exist_ok=True)
    safe_join(root, "social-prs").mkdir(exist_ok=True)
    ensure_memory_files(root.parent)
    ensure_performance_files(root.parent)
    atomic_json(config_path, {
        "schema_version": VERSION,
        "project_name": args.project_name,
        "style": {"kind": "preset", "name": args.style},
        "publishing_enabled": False,
    })
    atomic_json(state_path, {
        "schema_version": VERSION,
        "last_scanned_ref": None,
        "last_social_commit_number": 0,
        "last_social_pr_number": 0,
    })
    return {"result": "initialized", "root": str(root)}


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    config, state = require_initialized(root)
    ensure_memory_files(root.parent)
    ensure_performance_files(root.parent)
    prs = []
    for path in sorted(safe_join(root, "social-prs").glob("spr-*.json")):
        item = read_json(path)
        prs.append({"id": item["id"], "status": item["status"], "title": item["title"], "revision": item["revision"]})
    return {"config": config, "state": state, "social_prs": prs}


def validate_events(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise StateError("Events file must contain a non-empty JSON array")
    events: list[dict[str, Any]] = []
    for index, event in enumerate(raw, start=1):
        if not isinstance(event, dict):
            raise StateError(f"Event {index} must be an object")
        missing = EVENT_REQUIRED - event.keys()
        extra = event.keys() - EVENT_ALLOWED
        if missing:
            raise StateError(f"Event {index} missing fields: {', '.join(sorted(missing))}")
        if extra:
            raise StateError(f"Event {index} has unsupported fields: {', '.join(sorted(extra))}")
        if event["public_safe"] is not True:
            raise StateError(f"Event {index} is not explicitly public-safe")
        for field in EVENT_REQUIRED - {"public_safe"}:
            if not isinstance(event[field], str) or not event[field].strip():
                raise StateError(f"Event {index}.{field} must be a non-empty string")
        evidence = event.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(item, str) or not item.strip() for item in evidence):
            raise StateError(f"Event {index}.evidence must be a list of non-empty strings")
        inspect_public(event, f"event[{index}]")
        events.append(event)
    return events


def cmd_commit(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    _, state = require_initialized(root)
    events = validate_events(read_json(Path(args.events_file)))
    readiness = None
    readiness_override = None
    if args.candidate_file:
        candidate = read_json(Path(args.candidate_file))
        if not isinstance(candidate, dict):
            raise StateError("Candidate file must contain one ranked candidate object")
        readiness = candidate.get("publish_readiness")
        if not isinstance(readiness, dict):
            raise StateError("Candidate is missing publish_readiness")
        status = readiness.get("status")
        completion = readiness.get("completion")
        reason = readiness.get("reason")
        if status not in PUBLISH_READINESS_STATUSES or completion not in COMPLETION_LEVELS or not isinstance(reason, str) or not reason.strip():
            raise StateError("Invalid publish_readiness contract")
        if status != "ready":
            if not args.override_readiness:
                raise StateError(f"Publish Readiness is {status}; explicit --override-readiness is required")
            readiness_override = {
                "status": status,
                "reason": reason,
                "requested_at": now(),
            }
    number = state["last_social_commit_number"] + 1
    commit_id = f"sc-{number:04d}"
    enriched = [{"id": f"{commit_id}-evt-{i:02d}", **event} for i, event in enumerate(events, start=1)]
    record = {
        "schema_version": VERSION,
        "id": commit_id,
        "status": "SOCIAL_COMMIT",
        "version": 1,
        "revision_of": None,
        "title": args.title,
        "created_at": now(),
        "from_ref": args.from_ref,
        "to_ref": args.to_ref,
        "events": enriched,
    }
    if readiness is not None:
        record["publish_readiness"] = dict(readiness)
    if readiness_override is not None:
        record["publish_readiness_override"] = readiness_override
    inspect_public(record)
    atomic_json(safe_join(root / "social-commits", f"{commit_id}.json"), record)
    state["last_social_commit_number"] = number
    state["last_scanned_ref"] = args.to_ref
    atomic_json(root / "state.json", state)
    return record


def load_commit(root: Path, commit_id: str) -> dict[str, Any]:
    path = safe_state_record_path(root / "social-commits", commit_id, validate_social_commit_id)
    record = read_json(path)
    if record.get("status") != "SOCIAL_COMMIT":
        raise StateError(f"Invalid Social Commit: {commit_id}")
    return record


def record_version(record: dict[str, Any]) -> int:
    value = record.get("version", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StateError(f"Invalid content version for {record.get('id', 'record')}")
    return value


def revision_exists(root: Path, source_pr_id: str, source_commit_id: str) -> bool:
    for path in sorted(safe_join(root, "social-prs").glob("spr-*.json")):
        record = read_json(path)
        if (
            record.get("status") == "SOCIAL_PR"
            and (
                record.get("revision_of") == source_pr_id
                or record.get("source_approved_commit_id") == source_commit_id
            )
        ):
            return True
    for path in sorted(safe_join(root, "social-commits").glob("sc-*.json")):
        record = read_json(path)
        if record.get("status") == "SOCIAL_COMMIT" and record.get("revision_of") == source_commit_id:
            return True
    return False


def read_public_text(path_value: str, label: str) -> str:
    text = Path(path_value).read_text(encoding="utf-8").strip()
    if not text:
        raise StateError(f"{label} cannot be empty")
    inspect_public(text, label)
    return text


def draft_edit_requires_evidence(
    previous_body: str,
    new_body: str,
    feedback: str | None,
    previous_title: str = "",
    new_title: str = "",
) -> bool:
    """Keep ordinary wording edits local; require evidence for factual changes."""
    if feedback and FACTUAL_EDIT_REQUEST.search(feedback):
        return True
    previous_text = f"{previous_title}\n{previous_body}"
    new_text = f"{new_title}\n{new_body}"
    return sorted(NUMBER_TOKEN.findall(previous_text)) != sorted(NUMBER_TOKEN.findall(new_text))


def added_edit_numbers(previous_body: str, new_body: str, previous_title: str = "", new_title: str = "") -> set[str]:
    previous_text = f"{previous_title}\n{previous_body}"
    new_text = f"{new_title}\n{new_body}"
    return set(NUMBER_TOKEN.findall(new_text)) - set(NUMBER_TOKEN.findall(previous_text))


def full_draft_view(record: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(record.get("title") or ""),
        "body": str(record.get("body") or ""),
        "status": "DRAFT",
    }


def cmd_create_pr(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    _, state = require_initialized(root)
    commit = load_commit(root, args.commit)
    body = read_public_text(args.body_file, "draft body")
    number = state["last_social_pr_number"] + 1
    pr_id = f"spr-{number:04d}"
    timestamp = now()
    record = {
        "schema_version": VERSION,
        "id": pr_id,
        "status": "SOCIAL_PR",
        "version": record_version(commit),
        "revision_of": None,
        "source_approved_commit_id": commit.get("source_approved_commit_id"),
        "social_commit_id": args.commit,
        "publish_readiness": commit.get("publish_readiness"),
        "title": args.title,
        "direction": args.direction,
        "body": body,
        "first_draft": body,
        "revisions": [],
        "series": args.series,
        "series_number": args.series_number,
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
        "approved_at": None,
    }
    inspect_public(record)
    atomic_json(safe_join(root / "social-prs", f"{pr_id}.json"), record)
    state["last_social_pr_number"] = number
    atomic_json(root / "state.json", state)
    output = dict(record)
    output.update({
        "current_state": "DRAFT",
        "completed": "已生成内容草稿。",
        "next": ["修改内容", "审核通过并存入草稿箱（Approve）", "换一个选题", "暂不处理"],
    })
    return output


def cmd_create_revision(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    _, state = require_initialized(root)
    _, source_pr = load_pr(root, args.pr)
    if source_pr["status"] != "APPROVED":
        raise StateError("Revision source must be an APPROVED Social PR")

    source_commit_id = source_pr["social_commit_id"]
    source_commit_path = safe_state_record_path(root / "social-commits", source_commit_id, validate_social_commit_id)
    source_commit = read_json(source_commit_path)
    if source_commit.get("status") != "APPROVED":
        raise StateError("Revision source must reference an APPROVED Social Commit")
    if revision_exists(root, source_pr["id"], source_commit_id):
        raise StateError("This APPROVED version already has an unapproved revision")

    version = max(record_version(source_pr), record_version(source_commit)) + 1
    timestamp = now()
    commit_number = state["last_social_commit_number"] + 1
    commit_id = f"sc-{commit_number:04d}"
    events = []
    for index, event in enumerate(source_commit.get("events", []), start=1):
        copied_event = dict(event)
        copied_event["id"] = f"{commit_id}-evt-{index:02d}"
        events.append(copied_event)
    commit = {
        "schema_version": VERSION,
        "id": commit_id,
        "status": "SOCIAL_COMMIT",
        "version": version,
        "revision_of": source_commit_id,
        "source_approved_commit_id": source_commit_id,
        "title": source_commit["title"],
        "created_at": timestamp,
        "from_ref": source_commit.get("from_ref"),
        "to_ref": source_commit.get("to_ref"),
        "events": events,
    }

    pr_number = state["last_social_pr_number"] + 1
    pr_id = f"spr-{pr_number:04d}"
    pr = {
        "schema_version": VERSION,
        "id": pr_id,
        "status": "SOCIAL_PR",
        "version": version,
        "revision_of": source_pr["id"],
        "source_approved_commit_id": source_commit_id,
        "social_commit_id": commit_id,
        "publish_readiness": source_commit.get("publish_readiness"),
        "title": source_pr["title"],
        "direction": source_pr["direction"],
        "body": source_pr["body"],
        "first_draft": source_pr["body"],
        "revisions": [],
        "series": source_pr.get("series"),
        "series_number": source_pr.get("series_number"),
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
        "approved_at": None,
    }
    inspect_public(commit)
    inspect_public(pr)
    atomic_json(root / "social-commits" / f"{commit_id}.json", commit)
    atomic_json(root / "social-prs" / f"{pr_id}.json", pr)
    state["last_social_commit_number"] = commit_number
    state["last_social_pr_number"] = pr_number
    atomic_json(root / "state.json", state)

    output = dict(pr)
    output.update({
        "current_state": "DRAFT",
        "completed": f"已从 {source_pr['id']} 创建第 {version} 版草稿。原 APPROVED 版本保持不变。",
        "next": ["修改内容", "审核通过并存入草稿箱（Approve）", "暂不处理"],
    })
    return output


def load_pr(root: Path, pr_id: str) -> tuple[Path, dict[str, Any]]:
    path = safe_state_record_path(root / "social-prs", pr_id, validate_social_pr_id)
    record = read_json(path)
    if record.get("status") not in {"SOCIAL_PR", "APPROVED"}:
        raise StateError(f"Invalid Social PR: {pr_id}")
    return path, record


def cmd_revise_pr(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    require_initialized(root)
    path, record = load_pr(root, args.pr)
    if record["status"] == "APPROVED":
        raise StateError("Approved Social PRs are immutable; create a new PR")
    if args.body_file is None and args.title is None:
        raise StateError("Provide --body-file or --title for a draft edit")
    previous_body = record["body"]
    previous_title = record["title"]
    new_body = read_public_text(args.body_file, "draft body") if args.body_file else previous_body
    new_title = args.title.strip() if args.title is not None else previous_title
    if not new_title:
        raise StateError("draft title cannot be empty")
    inspect_public(new_title, "draft title")
    feedback = read_public_text(args.feedback_file, "feedback") if args.feedback_file else None
    requires_evidence = draft_edit_requires_evidence(previous_body, new_body, feedback, previous_title, new_title)
    evidence_checked = False
    if requires_evidence:
        if not args.evidence_file:
            raise StateError("这个修改涉及事实数字，需要重新核实证据。请先提供 --evidence-file。")
        evidence = read_public_text(args.evidence_file, "evidence")
        added_numbers = added_edit_numbers(previous_body, new_body, previous_title, new_title)
        if added_numbers and not added_numbers.issubset(set(NUMBER_TOKEN.findall(evidence))):
            raise StateError("当前 evidence 不支持修改后的事实数字，不能保存这次修改。")
        evidence_checked = True
    record["title"] = new_title
    record["body"] = new_body
    record["revision"] += 1
    record["updated_at"] = now()
    record.setdefault("revisions", []).append({
        "revision": record["revision"],
        "previous_body": previous_body,
        "previous_title": previous_title,
        "feedback": feedback,
        "edit_path": "FACT_CHECK" if requires_evidence else "DRAFT_FAST_PATH",
        "evidence_checked": evidence_checked,
        "updated_at": record["updated_at"],
    })
    atomic_json(path, record)
    output = dict(record)
    output.update({
        "current_state": "DRAFT",
        "action": "PULL",
        "edit_path": "FACT_CHECK" if requires_evidence else "DRAFT_FAST_PATH",
        "scan_performed": False,
        "evidence_checked": evidence_checked,
        "full_draft": full_draft_view(record),
        "draft_render": "已修改，当前完整草稿：",
        "completed": "已提交本轮自然语言修改，当前版本仍是草稿。",
        "next": ["提交以上修改（Pull）", "继续修改", "放弃这些修改"],
    })
    return output


def current_draft_pr(root: Path) -> tuple[str, dict[str, Any]]:
    drafts: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(safe_join(root, "social-prs").glob("spr-*.json")):
        record = read_json(path)
        if record.get("status") == "SOCIAL_PR":
            drafts.append((record.get("id") or path.stem, record))
    if len(drafts) != 1:
        raise StateError(f"Expected exactly one current DRAFT Social PR; found {len(drafts)}")
    return drafts[0]


def cmd_draft_edit(args: argparse.Namespace) -> dict[str, Any]:
    """Apply one exact replacement to the only current DRAFT in one command."""
    root = state_root(args.root)
    require_initialized(root)
    old = args.replace_old
    new = args.replace_new
    if not old:
        raise StateError("--replace-old cannot be empty")
    pr_id, record = current_draft_pr(root)
    title = str(record.get("title") or "")
    body = str(record.get("body") or "")
    if old not in title and old not in body:
        raise StateError("Exact replacement text was not found in the current DRAFT title or body")

    updated_title = title.replace(old, new)
    updated_body = body.replace(old, new)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", suffix=".draft.md", delete=False,
    ) as handle:
        handle.write(updated_body.rstrip() + "\n")
        body_file = handle.name
    try:
        revise_args = argparse.Namespace(
            root=args.root,
            pr=pr_id,
            body_file=body_file,
            title=updated_title,
            feedback_file=None,
            evidence_file=None,
        )
        output = cmd_revise_pr(revise_args)
    finally:
        try:
            os.unlink(body_file)
        except FileNotFoundError:
            pass
    output["command"] = "draft-edit"
    return output


def cmd_approve(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    require_initialized(root)
    path, record = load_pr(root, args.pr)
    if record["status"] == "APPROVED":
        output = dict(record)
        output.update({
            "current_state": "APPROVED",
            "completed": "当前版本已经审核通过并保存为草稿。",
            "next": ["发布到微博", "手动发布其他平台", "仅保存", "继续修改"],
        })
        return output
    record["status"] = "APPROVED"
    record["approved_at"] = now()
    record["updated_at"] = record["approved_at"]
    atomic_json(path, record)

    # Keep editorial approval on the PR while exposing the approved
    # publication payload on the related Social Commit. The publishing Skill
    # owns all external writes; this is only local state synchronization.
    commit_path = safe_state_record_path(root / "social-commits", record["social_commit_id"], validate_social_commit_id)
    commit = read_json(commit_path)
    if commit.get("status") not in {"SOCIAL_COMMIT", "APPROVED"}:
        raise StateError(f"Cannot approve Social Commit: {record['social_commit_id']}")
    commit["status"] = "APPROVED"
    commit["final_text"] = record["body"]
    commit["approved_at"] = record["approved_at"]
    atomic_json(commit_path, commit)
    learning: list[dict[str, Any]] = []
    record["learning_status"] = "pending"
    atomic_json(path, record)
    try:
        ensure_memory_files(root.parent)
        tags = [tag.strip() for tag in (args.tags or "").split(",") if tag.strip()]
        series = args.series or record.get("series")
        series_number = args.series_number if args.series_number is not None else record.get("series_number")
        learning = apply_learning(root.parent, commit, record, args.learning_file)
        append_approved_example(root.parent, commit, record, tags, series, series_number)
        update_series_state(root.parent, commit["id"], series, series_number)
        record["learning_status"] = "saved" if learning else "no_new_preference"
    except Exception:
        record["learning_status"] = "failed"
        record["learning_error"] = safe_error("LEARNING_SAVE_FAILED", "学习记录未能保存")
    record["learning"] = learning
    atomic_json(path, record)
    output = dict(record)
    output.update({
        "current_state": "APPROVED",
        "completed": "已审核通过并保存为草稿；学习偏好处理不会影响审核结果。",
        "next": ["发布到微博", "手动发布其他平台", "仅保存", "继续修改"],
    })
    return output


def cmd_record_manual_distribution(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    require_initialized(root)
    path = safe_state_record_path(root / "social-commits", args.commit, validate_social_commit_id)
    commit = read_json(path)
    if commit.get("status") != "APPROVED":
        raise StateError("Manual distribution requires an APPROVED Social Commit")
    platform = args.platform.strip()
    if not platform:
        raise StateError("Platform name cannot be empty")
    if platform.casefold() in {"weibo", "微博"}:
        raise StateError("微博发布必须使用独立的 weibo-publish Skill")
    inspect_public(platform, "platform")
    published_at = now()
    commit["status"] = "PUBLISHED"
    commit["publish"] = {
        "platform": platform,
        "status": "manual",
        "published_at": published_at,
    }
    append_manual_distribution_log(root.parent, commit["id"], platform, published_at)
    atomic_json(path, commit)
    return {
        "social_commit_id": commit["id"],
        "current_state": "PUBLISHED",
        "completed": f"已记录你在{platform}完成的手动发布。",
        "next": ["查看分发记录", "开始处理下一篇", "暂停"],
        "status": commit["status"],
        "platform": platform,
    }


def cmd_set_style(args: argparse.Namespace) -> dict[str, Any]:
    root = state_root(args.root)
    config, _ = require_initialized(root)
    if bool(args.preset) == bool(args.profile_file):
        raise StateError("Choose exactly one of --preset or --profile-file")
    if args.preset:
        if args.preset not in PRESETS:
            raise StateError(f"Unknown style preset: {args.preset}")
        config["style"] = {"kind": "preset", "name": args.preset}
    else:
        profile = read_public_text(args.profile_file, "style profile")
        (root / "style-profile.md").write_text(profile + "\n", encoding="utf-8", newline="\n")
        config["style"] = {"kind": "profile", "path": ".vibesocial/style-profile.md"}
    atomic_json(root / "config.json", config)
    return config["style"]


def build_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", default=".", help="Project root (default: current directory)")
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--project-name", required=True)
    init.add_argument("--style", default="casual-weibo")
    init.set_defaults(run=cmd_init)
    status = sub.add_parser("status")
    status.set_defaults(run=cmd_status)
    commit = sub.add_parser("commit")
    commit.add_argument("--title", required=True)
    commit.add_argument("--events-file", required=True)
    commit.add_argument("--from-ref", default="START")
    commit.add_argument("--to-ref", required=True)
    commit.add_argument("--candidate-file")
    commit.add_argument("--override-readiness", action="store_true")
    commit.set_defaults(run=cmd_commit)
    create_pr = sub.add_parser("create-pr")
    create_pr.add_argument("--commit", required=True)
    create_pr.add_argument("--title", required=True)
    create_pr.add_argument("--direction", required=True)
    create_pr.add_argument("--body-file", required=True)
    create_pr.add_argument("--series")
    create_pr.add_argument("--series-number", type=int)
    create_pr.set_defaults(run=cmd_create_pr)
    revise_pr = sub.add_parser("revise-pr")
    revise_pr.add_argument("--pr", required=True)
    revise_pr.add_argument("--body-file")
    revise_pr.add_argument("--title")
    revise_pr.add_argument("--feedback-file")
    revise_pr.add_argument("--evidence-file")
    revise_pr.set_defaults(run=cmd_revise_pr)
    draft_edit = sub.add_parser("draft-edit")
    draft_edit.add_argument("--replace-old", required=True)
    draft_edit.add_argument("--replace-new", required=True)
    draft_edit.set_defaults(run=cmd_draft_edit)
    create_revision = sub.add_parser("create-revision")
    create_revision.add_argument("--pr", required=True)
    create_revision.set_defaults(run=cmd_create_revision)
    approve = sub.add_parser("approve")
    approve.add_argument("--pr", required=True)
    approve.add_argument("--learning-file")
    approve.add_argument("--tags", default="")
    approve.add_argument("--series")
    approve.add_argument("--series-number", type=int)
    approve.set_defaults(run=cmd_approve)
    manual = sub.add_parser("record-manual-distribution")
    manual.add_argument("--commit", required=True)
    manual.add_argument("--platform", required=True)
    manual.set_defaults(run=cmd_record_manual_distribution)
    critique = sub.add_parser("critique")
    critique.add_argument("--text-file", required=True)
    critique.set_defaults(run=cmd_critique)
    memory_context = sub.add_parser("memory-context")
    memory_context.set_defaults(run=cmd_memory_context)
    learn = sub.add_parser("learn")
    learn.add_argument("--pr", required=True)
    learn.add_argument("--learning-file")
    learn.add_argument("--series")
    learn.add_argument("--series-number", type=int)
    learn.set_defaults(run=cmd_learn)
    backfill = sub.add_parser("backfill-memory")
    backfill.set_defaults(run=cmd_backfill_memory)
    history = sub.add_parser("backfill-history")
    history.add_argument("--history-file", required=True)
    history.set_defaults(run=cmd_backfill_history)
    style = sub.add_parser("set-style")
    style.add_argument("--preset")
    style.add_argument("--profile-file")
    style.set_defaults(run=cmd_set_style)
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        output = args.run(args)
    except (StateError, SafetyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
