#!/usr/bin/env python3
"""Generate a local, human-reviewable social draft from one story candidate."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VIBE_SCRIPTS = Path(__file__).resolve().parent
if str(VIBE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VIBE_SCRIPTS))
from safe_io import (  # noqa: E402
    DEFAULT_SUBPROCESS_TIMEOUT,
    MAX_GIT_OUTPUT_BYTES,
    bounded_subprocess,
    is_reparse_point,
    safe_join,
    safe_input_path,
    safe_output_path,
    SafetyError,
    validate_scan_root,
)


SUMMARY_EXTENSIONS = {".md", ".txt", ".rst", ".log"}
MAX_FILE_BYTES = 512 * 1024
MAX_FILE_CHARS = 64_000
SENSITIVE = re.compile(
    r"(?:password|api[_-]?key|oauth|cookie|token|secret|private[_-]?key|credential)|"
    r"(?:^|/)(?:\.env|credentials?|secrets?|private|customer|personal|users?|logs?)(?:/|$)",
    re.IGNORECASE,
)
MEMORY_FILES = ("writing-style.md", "anti-ai-patterns.md", "feedback-log.md")


class StoryGenerateError(RuntimeError):
    """A candidate cannot be safely turned into a local draft."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: str, limit: int = 240) -> str:
    value = re.sub(r"[A-Za-z]:[\\/][^\s]+", "[path hidden]", value)
    value = re.sub(r"/(?:home|Users|var|etc)/[^\s]+", "[path hidden]", value)
    value = re.sub(
        r"(?:token|secret|password|api[_-]?key|cookie)\s*[=:]\s*[^\s]+",
        "[sensitive value hidden]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit].rstrip()


def normalize_story_name(value: str) -> str:
    """Normalize shell/Markdown presentation differences for candidate lookup."""
    value = value.replace("`", "")
    return re.sub(r"\s+", " ", value).strip().casefold()


def parse_candidates(path: Path) -> list[dict[str, str]]:
    """Parse the stable key/value portion of story-candidates.md."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise StoryGenerateError("候选文件超过安全大小限制")
        text = path.read_text(encoding="utf-8")[:MAX_FILE_CHARS]
    except OSError as exc:
        raise StoryGenerateError(f"无法读取候选文件：{path}") from exc
    blocks = re.split(r"(?=^## Candidate \d+)", text, flags=re.MULTILINE)
    candidates: list[dict[str, str]] = []
    for block in blocks:
        if not block.startswith("## Candidate "):
            continue
        item: dict[str, str] = {}
        for line in block.splitlines():
            if not line.startswith("- ") or ":" not in line:
                continue
            key, value = line[2:].split(":", 1)
            item[key.strip()] = value.strip()
        if item.get("event") and item.get("source"):
            candidates.append(item)
    return candidates


def select_candidate(candidates: list[dict[str, str]], story: str) -> dict[str, str]:
    query = story.strip()
    if not query:
        raise StoryGenerateError("story 名称不能为空")
    if query.isdigit():
        index = int(query)
        if 1 <= index <= len(candidates):
            return candidates[index - 1]
    normalized_query = normalize_story_name(query)
    exact = [item for item in candidates if normalize_story_name(item.get("event", "")) == normalized_query]
    if len(exact) == 1:
        return exact[0]
    partial = [item for item in candidates if normalized_query in normalize_story_name(item.get("event", ""))]
    if len(partial) == 1:
        return partial[0]
    available = "、".join(item.get("event", "") for item in candidates[:12])
    if not candidates:
        raise StoryGenerateError("候选文件中没有可生成的故事")
    raise StoryGenerateError(f"无法唯一匹配 story：{query}。可选故事：{available}")


def _safe_summary_path(source_root: Path, relative: str) -> Path | None:
    if Path(relative).suffix.lower() not in SUMMARY_EXTENSIONS or SENSITIVE.search(relative):
        return None
    root = source_root.resolve()
    if is_reparse_point(root / relative):
        return None
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def read_doc_evidence(source_root: Path, source: str) -> list[str]:
    relative = source.split("summary:", 1)[1] if source.startswith("summary:") else ""
    path = _safe_summary_path(source_root, relative)
    if path is None:
        return []
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        content = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
    except OSError:
        return []
    evidence: list[str] = []
    for raw in content.splitlines():
        line = clean_text(raw.lstrip("#- "), 180)
        if (
            len(line) < 10
            or line.startswith("```")
            or SENSITIVE.search(line)
            or re.search(r"\b(?:private|internal|confidential|source code|do not share)\b", line, re.IGNORECASE)
            or re.search(r"(?:^|\s)(?:python|python3|node|npm|pnpm|yarn)\s+|(?:^|[/\\])scripts[/\\]|\.(?:py|ts|js|tsx|jsx)\b", line, re.IGNORECASE)
        ):
            continue
        if line.lower() in {"validation", "summary", "report", "overview", "contents"}:
            continue
        evidence.append(line)
        if len(evidence) >= 24:
            break
    return evidence


def read_git_evidence(source_root: Path, source: str) -> list[str]:
    match = re.match(r"git:([0-9a-f]+)", source, flags=re.IGNORECASE)
    if not match:
        return []
    try:
        result = bounded_subprocess(
            ["git", "-C", str(source_root), "show", "-s", "--format=%s%n%b", match.group(1)],
            timeout=DEFAULT_SUBPROCESS_TIMEOUT,
            max_output_bytes=MAX_GIT_OUTPUT_BYTES,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    evidence: list[str] = []
    for raw in result.stdout.splitlines():
        line = clean_text(raw, 180)
        if len(line) < 8 or SENSITIVE.search(line):
            continue
        evidence.append(line)
        if len(evidence) >= 8:
            break
    return evidence


def read_source_evidence(source_root: Path, candidate: dict[str, str]) -> list[str]:
    source = candidate.get("source", "")
    if source.startswith("summary:"):
        evidence = read_doc_evidence(source_root, source)
    elif source.startswith("git:"):
        evidence = read_git_evidence(source_root, source)
    else:
        evidence = []
    event = clean_text(candidate.get("event", ""), 180).rstrip("。.!！")
    technical = clean_text(candidate.get("technical_change", ""), 180).rstrip("。.!！")
    result: list[str] = []
    for item in evidence:
        normalized = item.rstrip("。.!！")
        if normalized in {event, technical} or normalized in result:
            continue
        result.append(item)
    return result


def _fact_text(value: str) -> str:
    value = clean_text(value, 220)
    value = re.sub(r"从摘要文件中识别到[“\"]?([^”\"]+)[”\"]?", r"\1", value)
    value = re.sub(r"；?没有保存正文[。.!！]?", "", value)
    value = re.sub(r"来源于开发总结文件[^。]*[。.!！]?", "", value)
    value = re.sub(r"；?不执行[^；。]*", "", value)
    value = re.sub(r"；?不修改[^；。]*", "", value)
    value = re.sub(r"；?不新增[^；。]*", "", value)
    value = re.sub(r"^本报告使用", "我使用", value)
    return value.strip(" ；。.!！")


def _matching_facts(evidence: list[str], pattern: str, limit: int = 2) -> list[str]:
    matches: list[str] = []
    for item in evidence:
        fact = _fact_text(item)
        if fact and re.search(pattern, fact, re.IGNORECASE) and fact not in matches:
            matches.append(fact)
        if len(matches) >= limit:
            break
    return matches


def _first_fact(evidence: list[str], *, exclude: str = "") -> str:
    for item in evidence:
        fact = _fact_text(item)
        if fact and fact != exclude and not re.search(r"^(?:Validation report|范围|计算规则|配置口径|提升)$", fact, re.IGNORECASE):
            return fact
    return ""


def _read_memory_file(source_root: Path, name: str) -> str:
    try:
        path = safe_join(source_root, f".vibesocial/{name}")
    except SafetyError:
        return ""
    if not path.is_file():
        return ""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
    except OSError:
        return ""


def _memory_bullets(text: str) -> list[str]:
    return [clean_text(line[2:].strip(), 220) for line in text.splitlines() if line.startswith("- ") and line[2:].strip()]


def _feedback_records(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for block in re.split(r"(?=^## Feedback)", text, flags=re.MULTILINE):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if not line.startswith("- ") or ":" not in line:
                continue
            key, value = line[2:].split(":", 1)
            fields[key.strip()] = clean_text(value.strip(), 220)
        if fields.get("inferred_rule"):
            records.append(fields)
    return records


def load_memory_context(source_root: Path) -> dict[str, list[str]]:
    """Load writing constraints without copying raw memory into the draft."""
    context = {"core": [], "repeated": [], "post_specific": []}
    context["core"].extend(_memory_bullets(_read_memory_file(source_root, "writing-style.md")))
    context["core"].extend(_memory_bullets(_read_memory_file(source_root, "anti-ai-patterns.md")))
    for record in _feedback_records(_read_memory_file(source_root, "feedback-log.md")):
        rule = record["inferred_rule"]
        status = record.get("status", "")
        scope = record.get("scope", "")
        if scope == "POST_SPECIFIC":
            context["post_specific"].append(rule)
        elif status == "REPEATED":
            context["repeated"].append(rule)
        elif status == "CORE":
            context["core"].append(rule)
    return context


def _inline_memory_rules(candidate: dict[str, str]) -> list[str]:
    values: list[str] = []
    for key in ("style_instruction", "memory_constraint", "post_specific_rule"):
        value = candidate.get(key, "")
        if isinstance(value, str) and value.strip():
            values.append(clean_text(value, 220))
    return values


def _effective_memory_rules(candidate: dict[str, str], memory: dict[str, list[str]] | None) -> list[str]:
    """Return rules in priority order: local > post-specific > repeated > core."""
    context = memory or {"core": [], "repeated": [], "post_specific": []}
    local = _inline_memory_rules(candidate)
    if str(candidate.get("memory_scope", "")).upper() == "POST_SPECIFIC":
        local.extend(context.get("post_specific", []))
    return local + context.get("repeated", []) + context.get("core", [])


def _memory_has(rules: list[str], pattern: str) -> bool:
    return any(re.search(pattern, rule, re.IGNORECASE) for rule in rules)


def _memory_length_limit(rules: list[str]) -> int:
    for rule in rules:
        if re.search(r"更短|短一些|shorter|more concise|shorter than|concise", rule, re.IGNORECASE):
            return 150
        if re.search(r"更长|长一些|longer|more detailed|expand", rule, re.IGNORECASE):
            return 220
    return 220


def _comparison_facts(evidence: list[str]) -> list[str]:
    results: list[str] = []
    for item in evidence:
        fact = _fact_text(item)
        if not fact.startswith("|") or fact.count("|") < 2 or not re.search(r"\d", fact):
            continue
        if re.search(r"^\|\s*:?-{2,}", fact):
            continue
        cells = [cell.strip() for cell in fact.strip("|").split("|") if cell.strip()]
        if len(cells) >= 3:
            results.append("；".join(cells))
    return results


def _candidate_facts(candidate: dict[str, str]) -> list[str]:
    facts: list[str] = []
    for key in ("before", "after", "experiment_result", "failure_reason", "validation_result", "user_visible_impact", "explicit_result"):
        value = candidate.get(key, "")
        if isinstance(value, str) and value.strip() and value.casefold() not in {"false", "none", "null"}:
            facts.append(_fact_text(value))
    return [fact for fact in facts if fact]


def extract_story_components(
    candidate: dict[str, str], evidence: list[str], memory: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    """Extract narrative material from candidate/evidence without adding domain claims."""
    event = _fact_text(candidate.get("event", "这次变化"))
    event_type = candidate.get("event_type", "")
    rules = _effective_memory_rules(candidate, memory)
    comparison_matches = _comparison_facts(evidence)
    verified_matches = _matching_facts(
        evidence,
        r"\d|before|after|from|to|error|result|test|output|request|response|cache|export|endpoint|结果|验证|通过|失败|错误|修正|用户|使用|点击|操作|请求|返回|输出|变化|减少|增加",
    )
    details = _candidate_facts(candidate) + (comparison_matches or verified_matches or [_first_fact(evidence)])
    details = list(dict.fromkeys(item for item in details if item))
    if _memory_has(rules, r"具体数字|保留数字|具体数据|number|numeric|concrete"):
        details.sort(key=lambda item: (0 if re.search(r"\d", item) else 1))
    if not details:
        details = [_fact_text(candidate.get("technical_change", "记录中的具体变化"))]
    if event_type == "failed_attempt":
        opening = f"这次我记录了“{event}”没有按原方案继续的结果。"
    elif _memory_has(rules, r"设问|为什么.*开头|question|forced.*hook"):
        opening = f"我先把“{event}”的具体变化写清楚。"
    else:
        opening = f"围绕“{event}”，我记录了这次具体变化。"
    return {"event": event, "opening": opening, "details": details, "rules": rules}


def draft_body(
    candidate: dict[str, str], evidence: list[str], memory: dict[str, list[str]] | None = None,
) -> str:
    components = extract_story_components(candidate, evidence, memory)
    title_event = re.sub(r"(?:对比)?验证报告$|报告$", "", str(components["event"])).strip(" ：") or str(components["event"])
    details = [str(item).rstrip("。.!！") for item in components["details"] if item]
    rules = components["rules"]
    max_chars = _memory_length_limit(rules)
    body = ""
    for count in range(len(details), 0, -1):
        detail_text = "，".join(details[:count])
        candidate_body = "\n".join([
            f"【我在看{title_event}】",
            str(components["opening"]).rstrip("。.!！") + "。",
            f"{detail_text}。",
        ])
        if len(re.sub(r"\s+", "", candidate_body)) <= max_chars or count == 1:
            body = candidate_body
            break
    return sanitize_narrative(body, rules)


def sanitize_narrative(text: str, rules: list[str] | None = None) -> str:
    """Keep source facts intact; memory rules constrain form before this point."""
    del rules
    return re.sub(r"[ \t]+", " ", text).strip()


def render_draft(
    source_root: Path, candidate: dict[str, str], evidence: list[str], memory: dict[str, list[str]] | None = None,
) -> str:
    del source_root
    return draft_body(candidate, evidence, memory) + "\n"


def generate(source_root: Path, candidates_file: Path, story: str) -> str:
    candidates = parse_candidates(candidates_file)
    candidate = select_candidate(candidates, story)
    if candidate.get("public_status") == "不建议公开":
        raise StoryGenerateError("该候选被标记为不建议公开，脚本不会生成草稿")
    evidence = read_source_evidence(source_root, candidate)
    memory = load_memory_context(source_root)
    return render_draft(source_root, candidate, evidence, memory)
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, help="项目根目录；只读")
    parser.add_argument("--story", required=True, help="候选编号、完整名称或唯一名称片段")
    parser.add_argument("--candidates-file", default=".vibesocial/story-candidates.md")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件路径")
    args = parser.parse_args()
    try:
        source_root = validate_scan_root(args.source_root)
        candidates_file = safe_input_path(source_root, args.candidates_file)
        output = safe_output_path(source_root, args.output, "story-draft.md")
        text = generate(source_root, candidates_file, args.story)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        temp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temp, output)
    except StoryGenerateError as exc:
        parser.error(str(exc))
    except OSError as exc:
        parser.error(f"无法写入输出文件：{exc}")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
