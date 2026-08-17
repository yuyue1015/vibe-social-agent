#!/usr/bin/env python3
"""Read-only Weibo performance snapshots and local comparative summaries."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VIBE_SCRIPTS = Path(__file__).resolve().parent
if str(VIBE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VIBE_SCRIPTS))
from safe_io import (  # noqa: E402
    DEFAULT_SUBPROCESS_TIMEOUT,
    bounded_subprocess,
    safe_error,
    safe_join,
    validate_scan_root,
    validate_social_commit_id,
)


MINIMUM_POSTS = 5
METRIC_NAME = re.compile(r"(?:^|_)(?:count|number|num|total|views?|reads?|likes?|comments?|reposts?|attitudes?)(?:$|_)", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root_path(value: str) -> Path:
    return validate_scan_root(value)


def performance_root(root: Path) -> Path:
    target = safe_join(root, ".vibesocial")
    target.mkdir(parents=True, exist_ok=True)
    return target


def run_cli(cli: str, *args: str) -> tuple[int, str, str]:
    try:
        result = bounded_subprocess([cli, *args], timeout=DEFAULT_SUBPROCESS_TIMEOUT)
    except OSError:
        return 127, "", safe_error("CLI_START_FAILED", "性能 CLI 无法启动")["error_message_safe"]
    return result.returncode, result.stdout, result.stderr


def parse_json_output(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") and not line.startswith("["):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def load_json(path: Path, default: Any) -> Any:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def published_records(root: Path) -> list[dict[str, Any]]:
    records = []
    commits = safe_join(root, ".vibesocial/social-commits")
    for path in sorted(commits.glob("*.json")):
        record = load_json(path, {})
        publish = record.get("publish") if isinstance(record, dict) else None
        if record.get("status") != "PUBLISHED" or not isinstance(publish, dict):
            continue
        if publish.get("platform") != "weibo" or not publish.get("weibo_id"):
            continue
        record["_publish"] = publish
        for pr_path in safe_join(root, ".vibesocial/social-prs").glob("*.json"):
            pr = load_json(pr_path, {})
            if pr.get("social_commit_id") == record.get("id"):
                record["_pr"] = pr
                break
        records.append(record)
    records.sort(key=lambda item: str(item.get("_publish", {}).get("published_at", "")))
    return records


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def interval(previous: dict[str, Any] | None, current: dict[str, Any]) -> float | None:
    if not previous:
        return None
    left = parse_time(previous.get("_publish", {}).get("published_at"))
    right = parse_time(current.get("_publish", {}).get("published_at"))
    if not left or not right:
        return None
    return round((right - left).total_seconds() / 3600, 2)


def content_features(record: dict[str, Any]) -> dict[str, Any]:
    text = record.get("final_text")
    if not isinstance(text, str):
        return {}
    pr = record.get("_pr", {})
    features: dict[str, Any] = {
        "char_count": len(text),
        "has_specific_number": bool(re.search(r"\d", text)),
        "has_specific_game_object": bool(re.search(r"疾病|房间|医院|员工|机器|病人|诊断室|DLC", text)),
        "has_bug": bool(re.search(r"Bug|bug|错误|算错|偏掉|返工", text)),
        "has_formula": bool(re.search(r"公式|\+\d+%|基础值|加成|阈值", text)),
        "has_question_opening": bool(re.match(r"\s*[^\n。！？!?]{0,30}[？?]", text)),
    }
    if isinstance(pr, dict):
        for source_key, target_key in (("series", "topic"), ("series_number", "series_number")):
            if pr.get(source_key) is not None:
                features[target_key] = pr[source_key]
        images = pr.get("images")
        if isinstance(images, list):
            features["image_count"] = len(images)
    return features


def discover_metric_command(cli: str) -> tuple[str | None, dict[str, Any]]:
    doctor_code, doctor_out, doctor_err = run_cli(cli, "doctor")
    if doctor_code != 0:
        return None, {"stage": "doctor", **safe_error("CLI_DOCTOR_FAILED", "性能 CLI 环境检查失败")}
    list_code, list_out, list_err = run_cli(cli, "commands", "list", "--available")
    if list_code != 0:
        return None, {"stage": "commands-list", **safe_error("CLI_COMMAND_LIST_FAILED", "无法读取性能命令列表")}
    candidates: list[tuple[int, str, str]] = []
    for line in list_out.splitlines():
        match = re.search(r"\b(statuses)\s+([^\s]+)", line)
        if not match:
            continue
        action = match.group(2)
        if not re.search(r"count|statistic|metric|read|like|comment|repost", action, re.I):
            continue
        score = 0 if re.search(r"count_sp|statistic", action, re.I) else 1
        candidates.append((score, match.group(1), action))
    if not candidates:
        return None, {"stage": "commands-list", "error": "No available statuses metric command was identified"}
    candidates.sort()
    group, action = candidates[0][1], candidates[0][2]
    show_code, show_out, show_err = run_cli(cli, "commands", "show", group, action)
    if show_code != 0:
        return None, {"stage": "commands-show", "command": f"{group} {action}", **safe_error("CLI_SCHEMA_FAILED", "无法读取性能命令结构")}
    flags = sorted(set(re.findall(r"--([A-Za-z][A-Za-z0-9_-]*)", show_out)))
    id_flags = [flag for flag in flags if re.search(r"(?:^|[-_])(id|ids|mid|mids)(?:$|[-_])", flag, re.I)]
    if len(id_flags) != 1:
        return None, {"stage": "commands-show", "command": f"{group} {action}", "error": "Schema did not expose one unambiguous Weibo ID flag", "flags": flags}
    return f"{group} {action}", {"command": [group, action], "id_flag": id_flags[0], "schema_flags": flags, "schema_excerpt": show_out[-1200:]}


def numeric_metrics(value: Any, prefix: str = "") -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            full_key = f"{prefix}_{key}" if prefix else str(key)
            if isinstance(item, (int, float)) and not isinstance(item, bool) and (METRIC_NAME.search(str(key)) or prefix):
                if math.isfinite(float(item)):
                    result[full_key] = item
            elif isinstance(item, (dict, list)):
                result.update(numeric_metrics(item, full_key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(numeric_metrics(item, f"{prefix}_{index}" if prefix else str(index)))
    return result


def take_snapshot(cli: str, record: dict[str, Any], previous: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    command_text, discovery = discover_metric_command(cli)
    if not command_text:
        return None, discovery
    command = discovery["command"]
    code, out, err = run_cli(cli, *command, f"--{discovery['id_flag']}", str(record["_publish"]["weibo_id"]))
    if code != 0:
        return None, {"stage": "metric-command", "command": command, **safe_error("CLI_METRIC_FAILED", "性能指标命令执行失败")}
    payload = parse_json_output(out)
    metrics = numeric_metrics(payload)
    if not metrics:
        return None, {"stage": "metric-command", "command": command, "error": "Command returned no numeric metric fields"}
    published_at = parse_time(record["_publish"].get("published_at"))
    captured = utc_now()
    age = None
    if published_at:
        age = round((datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)).total_seconds() / 3600, 2)
    snapshot: dict[str, Any] = {"captured_at": captured, "metrics": metrics}
    if age is not None:
        snapshot["age_hours"] = max(0, age)
    return snapshot, {"stage": "ok", "command": command}


def append_log(path: Path, record: dict[str, Any]) -> bool:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    key = (record.get("social_commit_id"), record.get("snapshots", [{}])[-1].get("captured_at"))
    for line in existing:
        old = parse_json_output(line)
        if isinstance(old, dict) and (old.get("social_commit_id"), old.get("snapshots", [{}])[-1].get("captured_at")) == key:
            return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def cmd_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    root = root_path(args.root)
    target = performance_root(root)
    records = published_records(root)
    if args.commit:
        commit_id = validate_social_commit_id(args.commit)
        records = [item for item in records if item.get("id") == commit_id]
    log_path = target / "performance-log.jsonl"
    results = []
    for index, record in enumerate(records):
        snapshot, diagnostic = take_snapshot(args.cli, record, records[index - 1] if index else None)
        if snapshot is None:
            results.append({"social_commit_id": record.get("id"), "status": "NOT_RECORDED", "diagnostic": diagnostic})
            continue
        publish = record["_publish"]
        item: dict[str, Any] = {
            "social_commit_id": record["id"],
            "weibo_id": publish["weibo_id"],
            "content_features": content_features(record),
            "snapshots": [snapshot],
        }
        if publish.get("published_at") is not None:
            item["published_at"] = publish["published_at"]
        gap = interval(records[index - 1] if index else None, record)
        if gap is not None:
            item["interval_from_previous"] = gap
        results.append({"social_commit_id": record["id"], "status": "RECORDED" if append_log(log_path, item) else "DUPLICATE", "diagnostic": diagnostic})
    return {"records_seen": len(records), "results": results}


def read_log(path: Path) -> list[dict[str, Any]]:
    entries = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        value = parse_json_output(line)
        if isinstance(value, dict) and value.get("social_commit_id"):
            entries.append(value)
    return entries


def category_lines(entries: list[dict[str, Any]], enough: bool) -> list[str]:
    metric_keys = sorted({key for entry in entries for snapshot in entry.get("snapshots", []) for key in snapshot.get("metrics", {})})
    lines = [
        "## Reach",
        "- Observed metric fields: " + (", ".join(metric_keys) if metric_keys else "none recorded"),
        "- No reach pattern is inferred from a single post or from missing fields.",
        "",
        "## Interaction",
        "- Compare only metrics actually returned by the CLI; do not synthesize likes, comments, or reposts.",
        "",
        "## Conversation",
        "- Conversation quality requires comment records or a later human review; aggregate counts alone are insufficient.",
        "",
        "## Series Health",
        "- Compare consecutive series numbers only after enough published observations exist.",
        "",
        "## Timing",
        "- Preserve published_at and interval_from_previous when supplied; no timing recommendation is active yet.",
        "",
        "## Format",
        "- Use only locally known char_count/image_count and observed snapshots; absent fields remain absent.",
        "",
        "## Content",
        "- Compare concrete content feature flags descriptively; this does not promote a writing rule.",
        "",
        "## Guardrails",
        "- Priority is factuality > Writing CORE > series plan > de-duplication > Performance Insights > generic social advice.",
        "- Performance Insights are reference signals only and can never override Writing CORE.",
    ]
    if not enough:
        lines.insert(2, "- Status: observation only; fewer than 5 distinct published posts have been recorded.")
    else:
        lines.insert(2, "- Status: descriptive comparison enabled; this still does not alter Writing Memory automatically.")
    return lines


def cmd_analyze(args: argparse.Namespace) -> dict[str, Any]:
    root = root_path(args.root)
    target = performance_root(root)
    entries = read_log(target / "performance-log.jsonl")
    distinct = {entry.get("social_commit_id") for entry in entries}
    snapshot_count = sum(len(entry.get("snapshots", [])) for entry in entries)
    enough = len(distinct) >= MINIMUM_POSTS and snapshot_count >= MINIMUM_POSTS
    metric_keys = sorted({key for entry in entries for snapshot in entry.get("snapshots", []) for key in snapshot.get("metrics", {})})
    baseline = {
        "schema_version": 1,
        "minimum_posts": MINIMUM_POSTS,
        "minimum_snapshots": MINIMUM_POSTS,
        "status": "DESCRIPTIVE_COMPARISON" if enough else "OBSERVATION_ONLY",
        "post_count": len(distinct),
        "snapshot_count": snapshot_count,
        "metric_keys": metric_keys,
        "updated_at": utc_now(),
    }
    (target / "performance-baseline.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    insights = "# Performance insights\n\n" + "\n".join(category_lines(entries, enough)) + "\n"
    (target / "performance-insights.md").write_text(insights, encoding="utf-8")
    return baseline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--cli", default="weibo-cli")
    snapshot.add_argument("--commit")
    snapshot.set_defaults(run=cmd_snapshot)
    analyze = sub.add_parser("analyze")
    analyze.set_defaults(run=cmd_analyze)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        result = args.run(args)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
