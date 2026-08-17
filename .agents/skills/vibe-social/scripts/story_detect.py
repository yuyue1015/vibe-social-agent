#!/usr/bin/env python3
"""Find privacy-reviewed development-story leads from recent Git traces."""

from __future__ import annotations

import argparse
import json
import os
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
    MAX_GIT_OUTPUT_BYTES,
    SafetyError,
    bounded_subprocess,
    is_reparse_point,
    safe_join,
    validate_scan_root,
)


COMMIT_MARKER = "__VIBESOCIAL_STORY_COMMIT__"
SENSITIVE_PATH = re.compile(
    r"(?:^|/)(?:\.env(?:\.|$)|credentials?|secrets?|tokens?|private|customer|personal|users?|logs?|dump|backup)(?:/|$)|"
    r"(?:password|api[_-]?key|oauth|cookie|private[_-]?key|credential)",
    re.IGNORECASE,
)
UNPUBLISHED_PLAN = re.compile(r"(?:roadmap|strategy|policy|phase|handoff|architecture|design)", re.IGNORECASE)
DATA_OR_BINARY = re.compile(r"(?:\.zip$|\.7z$|\.rar$|\.dll$|\.pyc$|(?:^|/)data/)", re.IGNORECASE)
SUMMARY_NAME = re.compile(
    r"(?:^changelog(?:[-_. ].*)?$|^release[-_. ]?notes?|^dev(?:elopment)?[-_. ]?(?:log|notes?)|"
    r"^progress(?:[-_. ]?(?:summary|log|notes?))?|^milestone(?:[-_. ].*)?$|^status[-_. ]?report|"
    r"^notes?|^audit|^review|^report|^summary|^benchmark|^validation|^feedback|"
    r"^test[-_ ]?(?:result|report|output)|^.*[-_ ](?:test|dev|development|progress|milestone)[-_ ]?(?:result|report|notes?|log)?$)",
    re.IGNORECASE,
)
SKIP_DIRS = {".git", ".vibesocial", "node_modules", "__pycache__", "dist", "build", "output", "asset", "data"}
SUMMARY_EXTENSIONS = {".md", ".txt", ".rst", ".log", ".json"}
ARTIFACT_DIRECTORIES = ("docs", "doc", "documentation", "reports", "reviews", "tests", "notes", "milestones", "progress")
RECENT_EVIDENCE = re.compile(
    r"(?:\b(?:unreleased|latest|recent|current|today|yesterday|this week|implemented|added|fixed|changed|"
    r"completed|passed|validated|released|working tree)\b|最近|近期|当前|本轮|完成|新增|修复|修改|通过|验证|发布|未提交|"
    r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})",
    re.IGNORECASE,
)
JOURNEY_STAGES = ("origin", "discovery", "prototype", "refinement", "validation", "release_growth")
JOURNEY_STATE_NAME = "story-journey-state.md"
PUBLISH_READINESS_STATUSES = ("ready", "hold", "skip")
COMPLETION_LEVELS = ("complete", "validated", "exploring", "unknown")
READINESS_ORDER = {"ready": 0, "hold": 1, "skip": 2}
MAX_FILE_BYTES = 512 * 1024
MAX_FILE_CHARS = 64_000
MAX_DOCUMENT_CHARS = 400_000
MAX_SCAN_FILES = 10_000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def journey_stage_for(event: dict[str, Any]) -> str:
    """Map a coarse event to a public-story stage without reading source code."""
    event_type = str(event.get("event_type", "")).lower()
    text = " ".join(str(event.get(key, "")) for key in ("event", "technical_change", "evidence", "source"))
    if re.search(r"为什么开始|最初|灵感|起点|why .*start|inspiration|origin", text, re.IGNORECASE):
        return "origin"
    if event_type == "failed_attempt" or re.search(r"第一次遇到|预期外|数据困难|规则复杂|旧方法|不够用|failed|unexpected", text, re.IGNORECASE):
        return "discovery"
    if event_type == "user_feedback" or (event_type in {"experiment", "milestone"} and re.search(r"测试|验证|对比|benchmark|validation|golden|实际使用|real use|review", text, re.IGNORECASE)):
        return "validation"
    if event_type == "milestone" or re.search(r"第一次跑|首次运行|第一个可运行|prototype|first run|first result", text, re.IGNORECASE):
        return "prototype"
    if event_type in {"bug_fix", "performance", "ux_change", "architecture_change"}:
        return "refinement"
    if event_type == "feature":
        return "release_growth"
    if event_type == "experiment":
        return "validation" if re.search(r"测试|验证|对比|benchmark|结果", text, re.IGNORECASE) else "discovery"
    return "discovery"


def _state_value(value: str) -> Any:
    value = value.strip()
    if value in {"", "null", "~"}:
        return None
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return [] if value.startswith("[") else {}
    return value.strip('"\'')


def read_journey_state(path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return state
    for line in lines:
        if not line or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        state[key.strip()] = _state_value(value)
    return state


def published_story_records(output_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    directory = safe_join(output_root, ".vibesocial/social-commits")
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") != "PUBLISHED" or not isinstance(record.get("publish"), dict):
            continue
        publish = record["publish"]
        title = clean_text(str(record.get("title") or "未命名已发布故事"), 80)
        event_type = str(record.get("story_type") or "").strip()
        if not event_type:
            event_types = [str(item.get("event_type")) for item in record.get("events", []) if isinstance(item, dict) and item.get("event_type")]
            event_type = event_types[0] if event_types else "development"
        event = {"event": title, "technical_change": title, "event_type": event_type, "source": "published"}
        records.append({
            "series": record.get("series") or publish.get("series"),
            "stage": journey_stage_for(event),
            "story_type": event_type,
            "topic": title,
            "published_at": publish.get("published_at") or record.get("published_at"),
            "social_commit_id": record.get("id") or record.get("social_commit_id") or path.stem,
        })
    return records


def _next_stage(stage: str | None) -> str:
    if stage not in JOURNEY_STAGES:
        return "origin"
    index = JOURNEY_STAGES.index(stage)
    return JOURNEY_STAGES[min(index + 1, len(JOURNEY_STAGES) - 1)]


def write_journey_state(output_root: Path, published: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    path = safe_join(output_root, f".vibesocial/{JOURNEY_STATE_NAME}")
    existing = read_journey_state(path)
    published = published if published is not None else published_story_records(output_root)
    latest = published[-1] if published else None
    state = {
        "series": (latest or {}).get("series") or existing.get("series"),
        "current_stage": (latest or {}).get("stage") or existing.get("current_stage"),
        "published_story_types": [item.get("story_type") for item in published[-20:]],
        "recent_story_types": [item.get("story_type") for item in published[-3:]],
        "recent_topics": [item.get("topic") for item in published[-3:]],
        "last_story_date": (latest or {}).get("published_at") or existing.get("last_story_date"),
        "avoid_repeat": existing.get("avoid_repeat") if isinstance(existing.get("avoid_repeat"), list) else [],
        "next_preferred_stage": _next_stage((latest or {}).get("stage") or existing.get("current_stage")),
    }
    if not published and not existing:
        state["next_preferred_stage"] = "origin"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Story journey state", ""]
    for key in ("series", "current_stage", "published_story_types", "recent_story_types", "recent_topics", "last_story_date", "avoid_repeat", "next_preferred_stage"):
        value = state[key]
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else ('null' if value is None else value)}")
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)
    return state


def assess_journey(candidate: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    stage = journey_stage_for(candidate)
    current = state.get("current_stage")
    next_stage = state.get("next_preferred_stage") or "origin"
    recent_topics = state.get("recent_topics") if isinstance(state.get("recent_topics"), list) else []
    if not current:
        if stage == "origin":
            fit, reason = "suitable_now", "没有已发布历史，origin 适合作为公开开场。"
        elif stage in {"discovery", "prototype"}:
            fit, reason = "wait_for_origin", "没有已发布起点，建议先补 origin，再进入这一阶段。"
        else:
            fit, reason = "needs_published_history", "没有已发布历史，不能仅凭 APPROVED 或历史范例推断公开节奏。"
    elif stage == next_stage:
        fit, reason = "suitable_now", f"它接在最近的 {current} 之后，符合下一阶段 {next_stage}。"
    elif stage == current or any(topic and topic == candidate.get("event") for topic in recent_topics):
        fit, reason = "avoid_repeat", "与最近公开阶段或主题重复，除非有明确的新结果。"
    elif stage in JOURNEY_STAGES and next_stage in JOURNEY_STAGES and JOURNEY_STAGES.index(stage) > JOURNEY_STAGES.index(next_stage):
        fit, reason = "too_early", f"它会跳过当前建议的 {next_stage}，先补齐读者上下文。"
    else:
        fit, reason = "suitable_after_context", f"它可以讲，但当前优先顺序仍是 {next_stage}。"
    result = dict(candidate)
    result.update({
        "journey_stage": stage,
        "journey_fit": fit,
        "journey_reason": reason,
        "journey_suggestion": reason if candidate.get("public_status") == "适合进入候选" else f"先处理公开安全：{candidate.get('publish_suggestion', '需要人工确认。')}",
    })
    return result


def apply_journey(candidates: list[dict[str, Any]], output_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state = write_journey_state(output_root)
    published = published_story_records(output_root)
    assessed = [assess_journey(candidate, state) for candidate in candidates]
    assessed = [assess_publish_readiness(candidate, state, published) for candidate in assessed]
    assessed.sort(key=lambda item: (
        READINESS_ORDER.get(item["publish_readiness"]["status"], 2),
        -int(item.get("story_score", 0)),
        str(item.get("source", "")),
    ))
    return assessed, state


def _normalized_topic(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").lower())


def completion_for(candidate: dict[str, Any]) -> str:
    if candidate.get("evidence_level") != "strong":
        return "unknown"
    explicit = str(candidate.get("completion") or "").strip().lower()
    if explicit in COMPLETION_LEVELS:
        return explicit
    event_type = str(candidate.get("event_type") or "").lower()
    combined = " ".join(str(candidate.get(key, "")) for key in ("event", "technical_change", "evidence"))
    if event_type in {"housekeeping", "dependency_upgrade"}:
        return "unknown"
    if event_type == "experiment":
        return "validated" if candidate.get("explicit_result") else "exploring"
    if event_type == "failed_attempt" and re.search(r"失败|结果|验证|failed|result|validated", combined, re.IGNORECASE):
        return "validated"
    if candidate.get("explicit_result"):
        return "complete" if event_type in {"feature", "bug_fix", "ux_change", "milestone"} else "validated"
    return "unknown"


def assess_publish_readiness(
    candidate: dict[str, Any],
    state: dict[str, Any],
    published: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess release timing separately from reader-value ranking."""
    published = published or []
    event = str(candidate.get("event") or "")
    combined = " ".join(str(candidate.get(key, "")) for key in ("event", "technical_change", "source", "evidence"))
    completion = completion_for(candidate)
    topic = _normalized_topic(event)
    duplicate = bool(candidate.get("already_published")) or any(
        topic and topic == _normalized_topic(item.get("topic"))
        for item in published
    )
    public_status = candidate.get("public_status")
    event_type = str(candidate.get("event_type") or "").lower()
    score = int(candidate.get("story_score", 0))

    if duplicate:
        status, reason = "skip", "与已发布内容重复，不建议再次单独发布。"
    elif public_status != "适合进入候选":
        status, reason = "skip", "当前事实或公开许可不足，不能安全形成独立 Social Commit。"
    elif completion == "unknown":
        status, reason = "skip", "缺少足够事实证据，暂时无法判断是否已经形成可公开结果。"
    elif event_type in {"housekeeping", "dependency_upgrade"} or re.search(
        r"依赖升级|整理文件|目录整理|格式整理|dependency upgrade|housekeeping|format only",
        combined,
        re.IGNORECASE,
    ):
        status, reason = "skip", "属于内部整理或 housekeeping，缺少独立读者价值。"
    elif score < 4 or (not candidate.get("reader_angle") and not candidate.get("why_people_care")):
        status, reason = "skip", "故事价值或读者可理解的实际变化不足。"
    elif completion == "exploring":
        status, reason = "hold", "仍处于探索阶段，结果可能变化，适合作为后续记录。"
    else:
        current = state.get("current_stage")
        journey_fit = candidate.get("journey_fit")
        early_result = bool(re.search(r"1\.0\.0|首个可用|第一个可用|首次可用|first usable|first solution", combined, re.IGNORECASE))
        if not current and completion == "complete" and early_result and event_type in {"feature", "bug_fix", "milestone", "ux_change"}:
            status, reason = "ready", "已形成明确且验证过的阶段结果，适合作为系列起点。"
        elif journey_fit == "suitable_now" or (not current and early_result):
            status, reason = "ready", "已形成明确结果并通过验证，符合当前系列位置。"
        else:
            status, reason = "hold", "有故事价值，但当前系列位置或发布时机更适合作为后续内容。"

    result = dict(candidate)
    result["completion"] = completion
    result["publish_readiness"] = {
        "status": status,
        "completion": completion,
        "reason": reason,
    }
    return result


def run_git(git_root: Path, scope: str | None, limit: int) -> tuple[int, str, str]:
    command = [
        "git", "-C", str(git_root), "log", f"-n{limit}", "--date=short",
        f"--format={COMMIT_MARKER}%n%h%n%ad%n%s", "--name-status",
    ]
    if scope and scope != ".":
        command.extend(["--", scope])
    try:
        result = bounded_subprocess(command, timeout=DEFAULT_SUBPROCESS_TIMEOUT, max_output_bytes=MAX_GIT_OUTPUT_BYTES)
    except OSError as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def run_git_status(git_root: Path, scope: str | None) -> tuple[int, str, str]:
    command = [
        "git", "-C", str(git_root), "status", "--porcelain=v1", "-z", "--untracked-files=all",
    ]
    if scope and scope != ".":
        command.extend(["--", scope])
    try:
        result = bounded_subprocess(command, timeout=DEFAULT_SUBPROCESS_TIMEOUT, max_output_bytes=MAX_GIT_OUTPUT_BYTES)
    except OSError as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def parse_working_tree(text: str) -> list[dict[str, str]]:
    """Parse bounded porcelain output without retaining diffs or source content."""
    entries: list[dict[str, str]] = []
    fields = text.split("\0")
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record or len(record) < 4:
            continue
        status = record[:2]
        path = record[3:]
        if not path:
            continue
        entries.append({"status": status, "path": path.replace("\\", "/")})
        if status[0] in {"R", "C"} and index < len(fields):
            index += 1
        if len(entries) >= MAX_SCAN_FILES:
            break
    return entries


def git_root_for(source_root: Path) -> Path:
    result = bounded_subprocess(
        ["git", "-C", str(source_root), "rev-parse", "--show-toplevel"],
        timeout=DEFAULT_SUBPROCESS_TIMEOUT,
        max_output_bytes=64 * 1024,
    )
    if result.returncode != 0:
        raise RuntimeError("Git history is unavailable")
    return Path(result.stdout.strip()).resolve()


def scope_for(source_root: Path, git_root: Path) -> str | None:
    try:
        relative = source_root.resolve().relative_to(git_root)
    except ValueError:
        return None
    return relative.as_posix() or None


def working_tree_paths(source_root: Path, git_root: Path, scope: str | None) -> tuple[list[dict[str, str]], str | None]:
    """Inspect current changes while keeping the selected project as the boundary."""
    code, output, _ = run_git_status(git_root, scope)
    if code != 0:
        return [], "无法读取 Git 工作树；继续检查项目内开发 artifact。"
    paths: list[dict[str, str]] = []
    source_resolved = source_root.resolve()
    for entry in parse_working_tree(output):
        raw_path = entry["path"]
        try:
            resolved = safe_join(git_root, raw_path)
            relative = resolved.resolve().relative_to(source_resolved).as_posix()
        except (OSError, SafetyError, ValueError):
            continue
        first_part = relative.split("/", 1)[0]
        if first_part in SKIP_DIRS or first_part.startswith(".tmp-vibesocial-"):
            continue
        if resolved.exists() and is_reparse_point(resolved):
            continue
        paths.append({"status": entry["status"], "path": relative})
    return paths, None


def working_tree_event(entries: list[dict[str, str]]) -> dict[str, Any] | None:
    """Create only a cautious lead for tracked changes; untracked source alone is insufficient."""
    if not entries or not any(entry["status"][0] != "?" for entry in entries):
        return None
    paths = [entry["path"] for entry in entries]
    areas, sensitive, plan_like = area_labels(paths)
    status, privacy_note = public_status(
        {"subject": "当前工作树存在未提交开发变更", "paths": paths}, sensitive, plan_like,
    )
    return rank_event({
        "event": "当前工作树存在未提交开发变更",
        "event_type": "architecture_change",
        "source": "working-tree",
        "technical_change": "当前项目范围内存在已跟踪但尚未提交的文件变化；具体事实和用户效果仍需人工核实。",
        "reader_angle": "未提交变化只能说明开发正在进行，不能单独证明某个用户结果。",
        "why_people_care": "它提示有当前开发活动，但还没有足够细节形成读者故事。",
        "evidence": "、".join(areas),
        "areas": areas,
        "public_status": status if status != "适合进入候选" else "待人工确认",
        "privacy_note": privacy_note,
        "user_visible": False,
        "explicit_result": False,
        "source_count": 1,
        "evidence_level": "strong",
    })


def parse_history(text: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line == COMMIT_MARKER:
            if current:
                commits.append(current)
            current = {"hash": None, "date": None, "subject": "", "paths": []}
            continue
        if current is None:
            continue
        if current["hash"] is None:
            current["hash"] = line.strip()
        elif current["date"] is None:
            current["date"] = line.strip()
        elif not current["subject"]:
            current["subject"] = line.strip()
        elif line.strip():
            match = re.match(r"^[A-Z0-9]+\s+(.+)$", line)
            if match:
                current["paths"].append(match.group(1).strip().replace("\\", "/"))
    if current:
        commits.append(current)
    return commits


def subject_kind(subject: str) -> tuple[str, str]:
    lowered = subject.lower()
    if re.search(r"\b(?:fix|fixed|bug|修复|错误|故障|回滚|revert)\b", lowered):
        return "bug修复", "结果不对或流程出错，修复后用户能少遇到一次失败。"
    if re.search(r"\b(?:fail|failed|failure|尝试|失败|实验)\b", lowered):
        return "失败尝试", "一次没有达到预期的尝试，能帮助用户理解为什么要换方案。"
    if re.search(r"\b(?:first|initial|run|working|success|pass|成功|首次|第一次|跑通|可用)\b", lowered):
        return "第一次成功运行", "从不能运行到第一次得到可用结果，用户能看到功能何时真正成立。"
    if re.search(r"\b(?:feedback|user|customer|反馈|用户)\b", lowered):
        return "用户反馈", "用户遇到的具体问题推动了改变，能说明这不是为了技术而技术。"
    if re.search(r"\b(?:roadmap|decision|policy|strategy|phase|架构|重构|设计|决策|规划)\b", lowered):
        return "重要决策", "开发者在多个方向之间做了取舍，用户能理解后续体验为何这样发展。"
    if re.search(r"\b(?:refactor|architecture|render|performance|optim\w*|engine|model|架构|性能|优化|重构)\b", lowered):
        return "架构调整", "底层实现或性能被调整，用户可能感受到更快、更稳或更容易扩展。"
    if re.search(r"\b(?:add|new|feature|implement|support|create|增加|新增|功能|支持|实现)\b", lowered):
        return "新功能", "新增能力改变了用户能做什么，适合从实际使用场景解释。"
    return "开发进展", "提交记录显示项目发生了变化，但还需要人工补充用户可感知的结果。"


def area_labels(paths: list[str]) -> tuple[list[str], bool, bool]:
    areas: set[str] = set()
    sensitive = False
    plan_like = False
    for path in paths:
        normalized = path.lstrip("./")
        if SENSITIVE_PATH.search(normalized):
            sensitive = True
        if DATA_OR_BINARY.search(normalized):
            areas.add("数据或二进制产物")
            sensitive = True
        if UNPUBLISHED_PLAN.search(normalized):
            plan_like = True
        if re.search(r"(?:test|spec|qa|golden|测试)", normalized, re.IGNORECASE):
            areas.add("测试")
        if re.search(r"(?:ui|frontend|view|screen|界面)", normalized, re.IGNORECASE):
            areas.add("界面")
        if re.search(r"(?:docs?|readme|handoff)", normalized, re.IGNORECASE):
            areas.add("文档")
        if re.search(r"(?:data|model|engine|core|architecture|计算|模型)", normalized, re.IGNORECASE):
            areas.add("数据或核心逻辑")
        if re.search(r"(?:script|app|src|application|runtime)", normalized, re.IGNORECASE):
            areas.add("实现")
    return sorted(areas), sensitive, plan_like


def public_status(commit: dict[str, Any], sensitive: bool, plan_like: bool) -> tuple[str, str]:
    subject = str(commit.get("subject", ""))
    if re.search(r"(?:[A-Za-z]:[\\/]|/(?:home|Users|var|etc)/|(?:token|secret|password|api[_-]?key|cookie))", subject, re.IGNORECASE):
        return "不建议公开", "提交摘要本身触发了敏感信息拦截；不保存或转述该摘要。"
    if sensitive and plan_like:
        return "不建议公开", "变更包含疑似未公开规划或设计文档，同时含数据/产物路径；不自动提炼细节。"
    if sensitive:
        return "待人工确认", "提交涉及数据、导出物或二进制文件；只能核实后的用户可感知结果进入 Social Commit。"
    if plan_like:
        return "待人工确认", "提交涉及规划、策略或设计文档；需要确认这些内容已经允许公开。"
    if not subject.strip():
        return "待人工确认", "没有可靠的提交摘要，不能从文件变化猜故事。"
    return "适合进入候选", "提交摘要和变更区域暂未触发自动隐私拦截，仍需人工核实事实和公开许可。"


def event_type_for(subject: str) -> str:
    lowered = subject.lower()
    if re.search(r"\b(?:performance|optim\w*|benchmark|性能|优化)\b", lowered):
        return "performance"
    if re.search(r"\b(?:ux|ui|render|screen|界面|交互|渲染)\b", lowered):
        return "ux_change"
    if re.search(r"\b(?:experiment|prototype|试验|实验)\b", lowered):
        return "experiment"
    kind, _ = subject_kind(subject)
    return {
        "新功能": "feature",
        "bug修复": "bug_fix",
        "架构调整": "architecture_change",
        "失败尝试": "failed_attempt",
        "第一次成功运行": "milestone",
        "用户反馈": "user_feedback",
    }.get(kind, "architecture_change")


def human_title(subject: str) -> str:
    title = clean_text(subject).rstrip("。！!") or "未命名开发变化"
    return title


def clean_text(value: str, limit: int = 160) -> str:
    value = re.sub(r"[A-Za-z]:[\\/][^\s]+", "[path hidden]", value)
    value = re.sub(r"/(?:home|Users|var|etc)/[^\s]+", "[path hidden]", value)
    value = re.sub(r"(?:token|secret|password|api[_-]?key|cookie)\s*[=:]\s*[^\s]+", "[sensitive value hidden]", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit].rstrip()


def reader_fields(event_type: str) -> tuple[str, str, bool]:
    fields = {
        "feature": ("用户可以直接多做一件事，或少绕一个步骤。", "新增能力是否改变了用户实际能完成的事情？", True),
        "bug_fix": ("用户原本会遇到错误、卡住或得到错误结果，修复后体验会变得可靠。", "这次修复是否改变了用户能看到的结果？", True),
        "performance": ("用户在等待、卡顿或处理大量内容时，能否更快得到结果。", "性能变化需要真实的前后结果，不能只凭实现名称判断。", True),
        "ux_change": ("界面或交互更接近用户的实际操作方式。", "读者需要知道具体哪个操作变得更容易。", True),
        "failed_attempt": ("失败过程能解释为什么最后没有继续沿用原方案。", "需要补充失败表现和重新选择方案的原因。", True),
        "milestone": ("一个功能从设想变成第一次真正可运行、可验证的结果。", "读者关心它是否已经稳定解决一个具体问题，而不是只停留在计划里。", True),
        "user_feedback": ("如果反馈确实来自真实使用者，它能解释改变从何而来。", "当前只确认存在反馈记录，具体用户问题和公开许可仍未确认。", False),
        "experiment": ("一次试验可以帮助读者理解哪些方向值得继续、哪些方向被放弃。", "需要有结果或失败原因，不能只描述做过实验。", True),
    }
    return fields.get(event_type, ("只有在它改变用户体验或解释重要取舍时，普通读者才会关心。", "当前没有明确的用户可见后果。", False))


def rank_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = event.get("event_type", "architecture_change")
    combined = " ".join(str(event.get(key, "")) for key in ("event", "technical_change", "source", "evidence"))
    reader_angle = str(event.get("reader_angle", "")).strip()
    why = str(event.get("why_people_care", "")).strip()
    user_score = 3 if event.get("user_visible") and event_type in {"bug_fix", "performance", "ux_change", "feature"} else 2 if event.get("user_visible") else 1 if event_type in {"milestone", "failed_attempt", "user_feedback", "experiment"} else 0
    turning_score = 3 if event_type == "failed_attempt" or re.search(r"失败|返工|回滚|重新|改方案|retry|rollback", combined, re.IGNORECASE) else 2 if event_type in {"bug_fix", "architecture_change", "experiment"} else 1
    explain_score = 3 if event_type in {"bug_fix", "feature", "ux_change", "milestone"} else 2 if event_type in {"performance", "failed_attempt", "user_feedback", "experiment"} else 1
    concrete_score = (
        (2 if re.search(r"\d", combined) else 0)
        + (2 if re.search(
            r"before|after|from|to|error|result|test|endpoint|cache|export|接口|文件|模块|功能|用户|案例|页面|按钮|结果|请求|输出|验证",
            combined,
            re.IGNORECASE,
        ) else 0)
        + (1 if event.get("areas") else 0)
    )
    score = user_score + turning_score + explain_score + min(concrete_score, 5)
    if re.search(r"纯文件整理|整理文件|file organization|dependency|依赖升级|upgrade dependencies", combined, re.IGNORECASE):
        score -= 3
    if re.search(r"变量重命名|rename variable|rename-only", combined, re.IGNORECASE):
        score -= 2
    if event_type == "architecture_change" and not event.get("user_visible"):
        score -= 2
    if event_type in {"performance", "ux_change"} and not event.get("user_visible") and not event.get("explicit_result"):
        score -= 2
    if not reader_angle or not why or re.search(r"没有明确|未确认|尚未确认|不确定|需要确认", reader_angle + why):
        score -= 2
    if event_type == "user_feedback" and not event.get("explicit_result"):
        score -= 2
    score = max(0, min(10, score))
    status = event.get("public_status", "待人工确认")
    if status == "不建议公开":
        suggestion = "不建议转为故事"
    elif status == "待人工确认":
        suggestion = "等待公开许可和用户可见效果确认后再写"
    elif score >= 7:
        suggestion = "可以进入 Social Commit 前的人工核实"
    elif score >= 4:
        suggestion = "补充用户可见结果或验证后再写"
    else:
        suggestion = "不建议转为故事"
    confidence = "high" if event.get("source_count", 1) > 1 and event.get("explicit_result") else "medium" if event.get("source") else "low"
    if status != "适合进入候选":
        confidence = "low" if status == "不建议公开" else "medium"
    result = dict(event)
    result.update({"story_score": score, "confidence": confidence, "publish_suggestion": suggestion})
    return result


def candidate_for(commit: dict[str, Any]) -> dict[str, Any]:
    subject = str(commit.get("subject", "")).strip() or "未命名开发变化"
    event_type = event_type_for(subject)
    areas, sensitive, plan_like = area_labels(list(commit.get("paths", [])))
    status, privacy_note = public_status(commit, sensitive, plan_like)
    reader_angle, why, _ = reader_fields(event_type)
    user_visible = bool(re.search(r"(?:\buser\b|\bux\b|用户|体验|卡顿|加载|等待|点击错误|操作|请求|输出|结果)", subject, re.IGNORECASE))
    technical = f"围绕“{human_title(subject)}”调整" + ("、".join(areas) if areas else "开发实现") + "；具体用户效果仍需人工核实。"
    return rank_event({
        "event": human_title(subject),
        "event_type": event_type,
        "source": f"git:{commit.get('hash') or 'unknown'} ({commit.get('date') or 'unknown'})",
        "technical_change": technical,
        "reader_angle": reader_angle,
        "why_people_care": why,
        "evidence": "、".join(areas),
        "areas": areas,
        "public_status": status,
        "privacy_note": privacy_note,
        "user_visible": user_visible,
        "explicit_result": bool(re.search(r"成功|通过|pass|benchmark|验证|结果", subject, re.IGNORECASE)),
        "source_count": 1,
        "evidence_level": "strong",
    })


def artifact_evidence_level(content: str) -> str:
    """Use textual recency markers; never use filesystem mtime as development evidence."""
    return "strong" if RECENT_EVIDENCE.search(content) else "supporting"


def summary_candidates(source_root: Path, budget: dict[str, int] | None = None) -> list[Path]:
    candidates: list[Path] = []
    seen = 0
    for path in source_root.iterdir() if source_root.exists() else []:
        if seen >= MAX_SCAN_FILES:
            return candidates
        if path.is_file() and SUMMARY_NAME.search(path.name):
            candidates.append(path)
            seen += 1
    for directory_name in ARTIFACT_DIRECTORIES:
        directory = source_root / directory_name
        if not directory.is_dir():
            continue
        for current, directories, filenames in os.walk(directory, topdown=True, followlinks=False):
            directories[:] = [
                name for name in directories
                if name not in SKIP_DIRS and not is_reparse_point(Path(current) / name)
            ]
            for name in filenames:
                seen += 1
                if seen >= MAX_SCAN_FILES:
                    return candidates
                path = Path(current) / name
                if is_reparse_point(path):
                    if budget is not None:
                        budget["skipped_files"] += 1
                    continue
                if Path(name).suffix.lower() not in SUMMARY_EXTENSIONS:
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        if budget is not None:
                            budget["skipped_files"] += 1
                            budget["skipped_bytes"] += path.stat().st_size
                        continue
                except OSError:
                    continue
                if SUMMARY_NAME.search(path.name):
                    candidates.append(path)
                if len(candidates) >= 80:
                    return candidates
    return candidates


def summary_event(path: Path, source_root: Path, budget: dict[str, int] | None = None) -> dict[str, Any] | None:
    try:
        if is_reparse_point(path):
            return None
        resolved = path.resolve()
        relative = resolved.relative_to(source_root.resolve()).as_posix()
        if budget is not None and budget["files"] >= MAX_SCAN_FILES:
            budget["skipped_files"] += 1
            return None
        raw = path.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            if budget is not None:
                budget["skipped_files"] += 1
                budget["skipped_bytes"] += len(raw)
            return None
        remaining = MAX_DOCUMENT_CHARS - (budget["chars"] if budget is not None else 0)
        if remaining <= 0:
            if budget is not None:
                budget["skipped_files"] += 1
                budget["skipped_bytes"] += len(raw)
            return None
        content = raw.decode("utf-8", errors="replace")[: min(MAX_FILE_CHARS, remaining)]
        if budget is not None:
            budget["files"] += 1
            budget["chars"] += len(content)
    except (OSError, ValueError):
        return None
    areas, sensitive, plan_like = area_labels([relative])
    filename = path.name.lower()
    evidence_level = artifact_evidence_level(content)
    if "feedback" in filename or "review" in filename:
        event_type, subject = "user_feedback", "已有用户反馈或评审记录"
    elif "benchmark" in filename or "validation" in filename or "test" in filename:
        event_type, subject = ("performance", "已有性能验证记录") if "benchmark" in filename else ("milestone", "已有测试或验证记录")
    elif "audit" in filename:
        event_type, subject = "architecture_change", "已有审计记录"
    elif "comparison" in filename:
        event_type, subject = "experiment", "已有方案对比记录"
    elif "calculation" in filename:
        event_type, subject = "milestone", "已有计算验证记录"
    elif any(token in filename for token in ("roadmap", "strategy", "policy", "design")):
        event_type, subject = "architecture_change", "已有规划或设计记录"
    else:
        event_type, subject = event_type_for(content[:500]), path.stem.replace("_", " ").replace("-", " ")
    headline = next((clean_text(line.lstrip("#- ")) for line in content.splitlines() if line.lstrip().startswith("#") and clean_text(line.lstrip("#- "))), None)
    if headline and not plan_like and event_type not in {"user_feedback", "performance", "milestone"}:
        subject = headline
    reader_angle, why, user_visible = reader_fields(event_type)
    status = "待人工确认" if sensitive or plan_like or event_type == "user_feedback" else "适合进入候选"
    note = "来源于项目内开发 artifact，只提取摘要线索；需要人工核实事实和公开范围。"
    if plan_like:
        note = "来源涉及规划、策略或设计文档，不自动公开正文内容。"
    if evidence_level != "strong":
        note = "当前能验证文件存在或功能描述，但没有明确近期标记；不能据此证明近期发生。"
    return rank_event({
        "event": clean_text(subject),
        "event_type": event_type,
        "source": f"summary:{relative}",
        "technical_change": f"从摘要文件中识别到“{clean_text(subject)}”；没有保存正文。",
        "reader_angle": reader_angle,
        "why_people_care": why,
        "evidence": "、".join(areas),
        "areas": areas,
        "public_status": status,
        "privacy_note": note,
        "user_visible": user_visible and event_type in {"feature", "bug_fix", "performance", "ux_change"},
        "explicit_result": bool(re.search(r"结果|通过|成功|验证|benchmark|tested|pass", content, re.IGNORECASE)),
        "source_count": 1,
        "evidence_level": evidence_level,
    })


def user_summary_event(summary: str) -> dict[str, Any] | None:
    if not isinstance(summary, str) or not summary.strip():
        return None
    content = summary[:MAX_FILE_CHARS]
    subject = next((clean_text(line.lstrip("#- ")) for line in content.splitlines() if line.strip()), "用户当前提供的开发摘要")
    event_type = event_type_for(content[:500])
    areas, sensitive, plan_like = area_labels(["user-summary"])
    status, privacy_note = public_status(
        {"subject": subject, "paths": []}, sensitive, plan_like,
    )
    reader_angle, why, user_visible = reader_fields(event_type)
    return rank_event({
        "event": subject,
        "event_type": event_type,
        "source": "user:current-summary",
        "technical_change": "用户当前提供了开发摘要；未保存摘要原文。",
        "reader_angle": reader_angle,
        "why_people_care": why,
        "evidence": "、".join(areas),
        "areas": areas,
        "public_status": status,
        "privacy_note": privacy_note,
        "user_visible": user_visible,
        "explicit_result": bool(re.search(r"结果|通过|成功|验证|tested|passed|fixed|implemented", content, re.IGNORECASE)),
        "source_count": 1,
        "evidence_level": "strong",
    })


def collect_events(source_root: Path, limit: int, user_summary: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    source_root = validate_scan_root(source_root)
    evidence: list[dict[str, Any]] = []
    supporting: list[dict[str, Any]] = []
    notes: list[str] = []
    git_root: Path | None = None
    scope: str | None = None
    try:
        git_root = git_root_for(source_root)
    except (OSError, RuntimeError):
        notes.append("未检测到可用 Git 仓库，继续检查项目内开发 artifact。")
    if git_root is not None:
        scope = scope_for(source_root, git_root)
        if scope is None and source_root.resolve() != git_root.resolve():
            return [], "扫描目录不在批准的 Git 范围内"
        code, output, _ = run_git(git_root, scope, limit)
        if code == 0:
            history = [candidate_for(commit) for commit in parse_history(output)]
            evidence.extend(history)
        else:
            notes.append("Git 历史为空或不可用，继续检查当前工作树。")
        paths, working_note = working_tree_paths(source_root, git_root, scope)
        if working_note:
            notes.append(working_note)
        working = working_tree_event(paths)
        if working:
            evidence.append(working)
        elif paths:
            notes.append("已检查当前工作树；仅未跟踪源码文件不足以证明近期开发事件。")
    budget = {"files": 0, "chars": 0, "skipped_files": 0, "skipped_bytes": 0}
    for path in summary_candidates(source_root, budget):
        event = summary_event(path, source_root, budget)
        if event:
            (evidence if event.get("evidence_level") == "strong" else supporting).append(event)
    if user_summary:
        event = user_summary_event(user_summary)
        if event:
            evidence.append(event)
    if budget["skipped_files"]:
        notes.append(f"资源限制：跳过 {budget['skipped_files']} 个摘要文件，未读取内容 {budget['skipped_bytes']} 字节。")
    if evidence:
        return evidence, "；".join(notes) if notes else None
    if supporting:
        notes.append("当前能验证功能存在，但无法证明这是近期开发变化。")
    else:
        notes.append("未发现可验证的近期开发证据；如需继续，请补充当前开发 artifact 或摘要。")
    return [], "；".join(notes)


def merge_and_rank(events: list[dict[str, Any]], max_candidates: int) -> list[dict[str, Any]]:
    ranked = [rank_event(event) for event in events]
    ranked.sort(key=lambda item: (-item["story_score"], item.get("source", "")))
    selected: list[dict[str, Any]] = []
    prefixes = sorted({item.get("source", "").split(":", 1)[0] for item in ranked})
    for prefix in prefixes:
        item = next((candidate for candidate in ranked if candidate.get("source", "").split(":", 1)[0] == prefix), None)
        if item:
            selected.append(item)
        if len(selected) >= max_candidates:
            return selected[:max_candidates]
    for item in ranked:
        if item not in selected:
            selected.append(item)
        if len(selected) >= max_candidates:
            break
    return selected


def render(source_root: Path, candidates: list[dict[str, Any]], error: str | None = None, journey_state: dict[str, Any] | None = None) -> str:
    generated = now()
    journey_state = journey_state or {}
    if candidates and any("publish_readiness" not in item for item in candidates):
        candidates = [
            item if "publish_readiness" in item else assess_publish_readiness(item, journey_state, [])
            for item in candidates
        ]
        candidates.sort(key=lambda item: (
            READINESS_ORDER.get(item["publish_readiness"]["status"], 2),
            -int(item.get("story_score", 0)),
            str(item.get("source", "")),
        ))
    lines = [
        "# Development story candidates",
        "",
        f"- generated_at: {generated}",
        f"- source_scope: {source_root.name or 'project'}",
        "- purpose: reader-value discovery only; not a Weibo draft, Writing Memory, Performance Learning, or project knowledge base",
        f"- journey_current_stage: {journey_state.get('current_stage') or 'null'}",
        f"- journey_next_preferred_stage: {journey_state.get('next_preferred_stage') or 'origin'}",
        f"- published_story_count: {len(journey_state.get('published_story_types') or [])}",
        "",
        "Candidates below are reader-value leads plus a public-sharing cadence signal. Verify the underlying work and public permission before creating a Social Commit; Journey never generates the post.",
    ]
    if error:
        lines.extend(["", "## Detection note", "", f"- {error}"])
    if not candidates:
        lines.extend(["", "No recent development trace produced a candidate."])
    else:
        groups = (("ready", "推荐下一篇"), ("hold", "稍后更适合"), ("skip", "不建议单独发布"))
        display_index = 1
        for readiness, heading in groups:
            group = [item for item in candidates if item.get("publish_readiness", {}).get("status") == readiness]
            if not group:
                continue
            lines.extend(["", f"## {heading}", ""])
            for item in group:
                readiness_data = item["publish_readiness"]
                lines.extend([
                    f"[{display_index}] {item['event']}",
                    f"    Story Value：{item['story_score']}/10",
                    f"    状态：{readiness.upper()}",
                    f"    原因：{readiness_data['reason']}",
                ])
                if item.get("source"):
                    lines.append(f"    证据来源：{item['source']}")
                display_index += 1
    lines.extend(["", "## 下一步", ""])
    if candidates:
        lines.extend([
            "[1] 采用推荐选题",
            "[2] 查看其他 READY / HOLD 候选",
            "[3] 重新指定时间范围",
            "[4] 暂不处理",
        ])
    elif error and "当前能验证功能存在" in error:
        lines.extend([
            "[1] 补充近期开发 artifact 或当前开发摘要",
            "[2] 重新扫描项目内证据",
            "[3] 暂不处理",
        ])
    else:
        lines.extend([
            "[1] 提供当前开发摘要或明确近期 artifact",
            "[2] 重新扫描项目内证据",
            "[3] 暂不处理",
        ])
    return "\n".join(lines) + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=".", help="Project whose recent Git traces should be inspected")
    parser.add_argument("--output-root", default=".", help="VibeSocial project receiving .vibesocial/story-candidates.md")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--development-summary", help="Optional current user-provided development summary")
    args = parser.parse_args()
    source_root = validate_scan_root(args.source_root)
    output_root = validate_scan_root(args.output_root)
    if args.limit < 1 or args.limit > 100 or args.max_candidates < 1 or args.max_candidates > 50:
        parser.error("--limit must be 1–100 and --max-candidates must be 1–50")
    events, error = collect_events(source_root, args.limit, args.development_summary)
    candidates = merge_and_rank(events, args.max_candidates)
    candidates, journey_state = apply_journey(candidates, output_root)
    output = safe_join(output_root, ".vibesocial/story-candidates.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(render(source_root, candidates, error, journey_state), encoding="utf-8", newline="\n")
    os.replace(temp, output)
    print(f"Wrote {output}")
    print(f"Events: {len(events)}; candidates: {len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
