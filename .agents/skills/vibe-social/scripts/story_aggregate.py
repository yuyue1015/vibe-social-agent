#!/usr/bin/env python3
"""Aggregate related real Stories into stage-based material and inspiration candidates."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VIBE_SCRIPTS = Path(__file__).resolve().parent
if str(VIBE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VIBE_SCRIPTS))
from safe_io import MAX_FILE_BYTES, safe_input_path, safe_join, safe_output_path, validate_scan_root  # noqa: E402


ALLOWED_COMMIT_STATUSES = {"APPROVED", "PUBLISHED"}
STAGES = ("origin", "discovery", "prototype", "refinement", "validation", "release_growth")
STAGE_RANK = {stage: index for index, stage in enumerate(STAGES)}
GENERIC_TERMS = {
    "开发", "记录", "故事", "验证", "测试", "结果", "项目", "功能", "系统", "已有", "变化", "调整", "实现",
    "用户", "玩家", "数据", "过程", "内容", "方案", "配置", "报告", "the", "story", "feature", "test",
}


class AggregationError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[A-Za-z]:[\\/][^\s]+", "[path hidden]", text)
    text = re.sub(r"/(?:home|Users|var|etc)/[^\s]+", "[path hidden]", text)
    return text[:limit].rstrip()


def story_terms(text: str) -> set[str]:
    text = text.casefold()
    terms = set(re.findall(r"[a-z][a-z0-9_-]{2,}", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for size in (2, 3):
            terms.update(run[index:index + size] for index in range(len(run) - size + 1))
    return {
        term for term in terms
        if term not in GENERIC_TERMS and not any(generic in term or term in generic for generic in GENERIC_TERMS if len(generic) > 1)
    }


def safe_status(status: str) -> bool:
    return status in ALLOWED_COMMIT_STATUSES or status in {"STORY", "DETECTED"}


def event_type_from(record: dict[str, Any]) -> str:
    if record.get("event_type"):
        return clean(record["event_type"], 40)
    events = record.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and event.get("event_type"):
                return clean(event["event_type"], 40)
    return "development"


def stage_from(record: dict[str, Any]) -> str:
    stage = clean(record.get("stage") or record.get("journey_stage"), 40)
    if stage in STAGES:
        return stage
    text = " ".join(clean(record.get(key, ""), 180) for key in ("title", "event", "summary", "topic"))
    if re.search(r"起点|开始|灵感|origin", text, re.IGNORECASE):
        return "origin"
    if re.search(r"第一次|跑通|prototype|首次", text, re.IGNORECASE):
        return "prototype"
    if re.search(r"反馈|对比|验证|测试|validation|review", text, re.IGNORECASE):
        return "validation"
    if re.search(r"失败|返工|bug|修复|调整|优化|重构|refinement", text, re.IGNORECASE):
        return "refinement"
    return "discovery"


def roles_from(record: dict[str, Any], stage: str) -> set[str]:
    explicit = record.get("arc_roles")
    if isinstance(explicit, list):
        return {clean(item, 30) for item in explicit if clean(item, 30)}
    return {
        "origin": {"origin"},
        "discovery": {"problem"},
        "prototype": {"adjustment"},
        "refinement": {"adjustment"},
        "validation": {"result"},
        "release_growth": {"result"},
    }.get(stage, set())


def normalize_story(record: dict[str, Any], fallback_id: str) -> dict[str, Any] | None:
    status = clean(record.get("status") or record.get("source_status") or "STORY", 30).upper()
    if not safe_status(status):
        return None
    story_id = clean(record.get("id") or record.get("social_commit_id") or fallback_id, 100)
    title = clean(record.get("title") or record.get("event") or "未命名 Story", 160)
    events = record.get("events") if isinstance(record.get("events"), list) else []
    event_summaries = [clean(item.get("summary") or item.get("event") or item.get("title"), 180) for item in events if isinstance(item, dict)]
    summary = clean(record.get("summary") or "；".join(item for item in event_summaries if item), 260)
    topic = clean(record.get("topic") or record.get("feature_chain") or title, 120)
    stage = stage_from(record)
    return {
        "id": story_id,
        "status": status,
        "title": title,
        "summary": summary,
        "topic": topic,
        "feature_chain": clean(record.get("feature_chain"), 100),
        "series": clean(record.get("series"), 100),
        "event_type": event_type_from(record),
        "stage": stage,
        "arc_roles": roles_from(record, stage),
        "has_before_after": bool(record.get("has_before_after") or record.get("before_after")),
        "has_screenshot": bool(record.get("has_screenshot") or record.get("screenshot") or record.get("image_count")),
        "stage_complete": bool(record.get("stage_complete") or re.search(r"完成|稳定|可用|收尾|complete|stable", summary, re.IGNORECASE)),
        "source_kind": clean(record.get("source_kind") or ("social_commit" if status in ALLOWED_COMMIT_STATUSES else "story"), 30),
    }


def load_json_records(path: Path) -> list[dict[str, Any]]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise AggregationError("Story 输入超过安全大小限制")
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AggregationError(f"无法读取 Story 输入：{path}") from exc
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict) and isinstance(parsed.get("stories"), list):
            return [item for item in parsed["stories"] if isinstance(item, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    records.append(item)
        return records
    raise AggregationError("Story 输入必须是 JSON 数组、对象或 JSONL")


def load_stories(root: Path, stories_file: Path | None = None) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    if stories_file:
        raw = load_json_records(stories_file)
    else:
        directory = safe_join(root, ".vibesocial/social-commits")
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                raw.append(item)
    stories: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        story = normalize_story(item, f"story-{index:04d}")
        if story:
            stories.append(story)
    return stories


def related(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("series") and left.get("series") == right.get("series"):
        return True
    left_topic = left.get("feature_chain") or left.get("topic")
    right_topic = right.get("feature_chain") or right.get("topic")
    if left_topic and right_topic:
        return bool(story_terms(str(left_topic)) & story_terms(str(right_topic)))
    overlap = story_terms(str(left.get("title", ""))) & story_terms(str(right.get("title", "")))
    return bool(overlap) and left.get("stage") == right.get("stage")


def group_stories(stories: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for story in stories:
        matches = [group for group in groups if any(related(story, existing) for existing in group)]
        if not matches:
            groups.append([story])
            continue
        first = matches[0]
        first.append(story)
        for other in matches[1:]:
            first.extend(other)
            groups.remove(other)
    return groups


def common_topic(group: list[dict[str, Any]]) -> str:
    explicit = [item.get("feature_chain") or item.get("topic") for item in group if item.get("feature_chain") or item.get("topic")]
    if explicit:
        return Counter(explicit).most_common(1)[0][0]
    terms = set.intersection(*(story_terms(item.get("title", "")) for item in group)) if group else set()
    return "、".join(sorted(terms)) or "相关开发阶段"


def build_candidate(group: list[dict[str, Any]]) -> dict[str, Any]:
    stages = sorted({item["stage"] for item in group}, key=lambda stage: STAGE_RANK.get(stage, 99))
    roles = set().union(*(item["arc_roles"] for item in group))
    arc_complete = {"origin", "problem", "adjustment", "result"}.issubset(roles)
    stage_complete = any(item["stage_complete"] for item in group)
    has_rework = any(item["event_type"] == "failed_attempt" or re.search(r"返工|重做|失败|rework|rollback", item["summary"], re.IGNORECASE) for item in group)
    has_validation = any(item["stage"] == "validation" or item["event_type"] in {"experiment", "milestone", "user_feedback"} for item in group)
    rework_validation = has_rework and has_validation
    before_after = sum(item["has_before_after"] for item in group) >= 2 and any(item["has_screenshot"] for item in group)
    count_ready = len(group) >= 4
    qualified = count_ready or stage_complete or arc_complete or rework_validation or before_after
    score = 2
    score += 2 if count_ready else 0
    score += 2 if stage_complete else 0
    score += 3 if arc_complete else 0
    score += 1 if rework_validation else 0
    score += 2 if before_after else 0
    score = min(10, score)
    topic = common_topic(group)
    missing: list[str] = []
    if "origin" not in stages:
        missing.append("缺少起点或问题背景")
    if not ({"discovery", "refinement"} & set(stages)):
        missing.append("缺少问题或调整过程")
    if "validation" not in stages and not stage_complete:
        missing.append("缺少结果闭环")
    if not any(item["has_before_after"] for item in group):
        missing.append("缺少前后对比")
    if not any(item["has_screenshot"] for item in group):
        missing.append("缺少可展示截图")
    if len(group) < 4:
        missing.append("相关 Story 少于 4 条")
    if score < 7:
        recommendation = "继续积累素材"
    elif score <= 8:
        recommendation = "已具备阶段性内容灵感"
    else:
        recommendation = "可作为未来小红书选题素材"
    arc_names = {"origin": "起点", "discovery": "问题", "prototype": "第一次跑通", "refinement": "调整", "validation": "结果", "release_growth": "扩展"}
    narrative = " → ".join(arc_names[stage] for stage in stages)
    return {
        "title_direction": f"从{topic}的起点，到问题、调整和结果",
        "included_story_ids": [item["id"] for item in group],
        "stage_summary": f"{len(group)} 条相关 Story，覆盖：{'、'.join(stages)}。",
        "narrative_arc": narrative or "相关主题积累",
        "why_now": "已经形成同一主题下的连续开发足迹。" if qualified else "主题有关联，但阶段材料还没有形成完整闭环。",
        "missing_material": missing or ["暂无明显缺口，仍需人工确认事实和展示素材"],
        "readiness_score": score,
        "recommendation": recommendation,
        "_qualified": qualified,
    }


def aggregate(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for group in group_stories(stories):
        if len(group) < 2:
            continue
        candidate = build_candidate(group)
        candidate.pop("_qualified", None)
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["readiness_score"], item["included_story_ids"][0]))
    return candidates


def render(root: Path, stories: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> str:
    lines = [
        "# Story aggregation candidates",
        "",
        f"- generated_at: {now()}",
        f"- story_count: {len(stories)}",
        "- purpose: 阶段性素材聚合 / 灵感候选",
        "",
    ]
    if not candidates:
        lines.append("No related Story group is ready for aggregation.")
        return "\n".join(lines) + "\n"
    for index, candidate in enumerate(candidates, start=1):
        lines.extend([
            f"## Aggregation candidate {index}",
            "",
            f"- title_direction: {candidate['title_direction']}",
            f"- included_story_ids: {json.dumps(candidate['included_story_ids'], ensure_ascii=False)}",
            f"- stage_summary: {candidate['stage_summary']}",
            f"- narrative_arc: {candidate['narrative_arc']}",
            f"- why_now: {candidate['why_now']}",
            f"- missing_material: {'；'.join(candidate['missing_material'])}",
            f"- readiness_score: {candidate['readiness_score']}/10",
            f"- recommendation: {candidate['recommendation']}",
            "",
        ])
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=".", help="VibeSocial root containing .vibesocial/social-commits")
    parser.add_argument("--stories-file", help="Optional JSON/JSONL file containing real Story records")
    parser.add_argument("--output", default=".vibesocial/aggregation-candidates.md")
    args = parser.parse_args()
    root = validate_scan_root(args.source_root)
    stories_file = safe_input_path(root, args.stories_file) if args.stories_file else None
    try:
        stories = load_stories(root, stories_file)
        candidates = aggregate(stories)
        output = safe_output_path(root, args.output, "aggregation-candidates.md")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        temp.write_text(render(root, stories, candidates), encoding="utf-8", newline="\n")
        os.replace(temp, output)
    except AggregationError as exc:
        parser.error(str(exc))
    except OSError as exc:
        parser.error(f"无法写入聚合候选：{exc}")
    print(f"Wrote {output}")
    print(f"Stories: {len(stories)}; aggregation candidates: {len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
