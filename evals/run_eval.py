#!/usr/bin/env python3
"""Run the small, deterministic VibeSocial task-evaluation suite.

The runner writes aggregate metrics only. Raw artifacts and expected answers are
never copied into results/, and the forward tests remain evaluator-run work.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases" / "core_benchmark.json"
RANKING_PATH = ROOT / "evals" / "cases" / "ranking_mix.json"
EXPECTED_PATH = ROOT / "evals" / "expected" / "core_benchmark.json"
PROJECT_FIXTURES = ROOT / "evals" / "fixtures" / "projects"
WEIBO_FIXTURES = ROOT / "evals" / "fixtures" / "weibo-cli"
STORY_DETECT_PATH = ROOT / ".agents" / "skills" / "vibe-social" / "scripts" / "story_detect.py"
STORY_GENERATE_PATH = ROOT / ".agents" / "skills" / "vibe-social" / "scripts" / "story_generate.py"
STATE_PATH = ROOT / ".agents" / "skills" / "vibe-social" / "scripts" / "vibe_state.py"
WEIBO_PUBLISH_PATH = ROOT / ".agents" / "skills" / "weibo-publish" / "scripts" / "weibo_publish.py"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STORY_DETECT = load_module(STORY_DETECT_PATH, "eval_story_detect")
STORY_GENERATE = load_module(STORY_GENERATE_PATH, "eval_story_generate")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_cases(cases: list[dict[str, Any]], expected: dict[str, Any]) -> None:
    if not 10 <= len(cases) <= 12:
        raise ValueError(f"core benchmark must contain 10–12 cases, found {len(cases)}")
    required = {
        "case_id", "raw_artifact", "expected_event_type", "expected_priority",
        "required_facts", "forbidden_claims", "expected_behavior",
    }
    ids: set[str] = set()
    for case in cases:
        missing = required - case.keys()
        if missing:
            raise ValueError(f"{case.get('case_id', '<unknown>')} missing {sorted(missing)}")
        case_id = str(case["case_id"])
        if case_id in ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        ids.add(case_id)
        if not isinstance(case["raw_artifact"], str) or not case["raw_artifact"].strip():
            raise ValueError(f"{case_id} raw_artifact must be non-empty text")
        if not isinstance(case["required_facts"], list) or not isinstance(case["forbidden_claims"], list):
            raise ValueError(f"{case_id} fact lists must be arrays")
    ranking_ids = expected.get("ranking", {}).get("expected_top_ids", [])
    if len(ranking_ids) != 5 or len(set(ranking_ids)) != 5:
        raise ValueError("expected ranking must define five unique candidate IDs")
    for fixture in ("non-game-cli.md", "saas-web.md", "api-data.md"):
        if not (PROJECT_FIXTURES / fixture).is_file():
            raise ValueError(f"missing project fixture: {fixture}")
    if not (WEIBO_FIXTURES / "responses.json").is_file():
        raise ValueError("missing Weibo recorded responses")
    ranking = load_json(RANKING_PATH)
    if len(ranking) != 5 or any(not isinstance(item.get("id"), str) for item in ranking):
        raise ValueError("ranking_mix.json must contain five named candidates")


def run_detect_eval(cases: list[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    predicted: list[dict[str, Any]] = []
    for case in cases:
        detect_input = dict(case.get("detect", {}))
        detect_input.setdefault("hash", case["case_id"])
        detect_input.setdefault("date", "2026-01-01")
        candidate = STORY_DETECT.candidate_for(detect_input)
        predicted.append({"case_id": case["case_id"], "candidate": candidate})

    comparable = [item for item in zip(cases, predicted) if item[0]["expected_event_type"] is not None]
    accuracy = sum(
        item[1]["candidate"].get("event_type") == item[0]["expected_event_type"] for item in comparable
    ) / len(comparable)
    threshold = int(expected["ranking"].get("reader_value_threshold", 7))
    high_cases = [item for item in zip(cases, predicted) if item[0]["expected_priority"] == "high"]
    high_recall = sum(STORY_DETECT.rank_event(item[1]["candidate"])["story_score"] >= threshold for item in high_cases)
    high_recall = high_recall / len(high_cases) if high_cases else 1.0
    housekeeping = next(item for item in zip(cases, predicted) if item[0]["category"] == "housekeeping")
    housekeeping_score = STORY_DETECT.rank_event(housekeeping[1]["candidate"])["story_score"]
    housekeeping_fpr = float(housekeeping_score >= threshold)
    ambiguous = next(item for item in zip(cases, predicted) if item[0]["category"] == "ambiguous-change")
    ambiguous_ranked = STORY_DETECT.rank_event(ambiguous[1]["candidate"])
    abstained = ambiguous_ranked["story_score"] < threshold and not ambiguous[1]["candidate"].get("user_visible")
    non_game = next(item for item in zip(cases, predicted) if item[0]["category"] == "non-game-project")
    non_game_text = json.dumps(non_game[1]["candidate"], ensure_ascii=False)
    domain_terms = ("玩家", "医院", "病人", "房间", "疾病", "诊断")
    generalized = not any(term in non_game_text for term in domain_terms)
    return {
        "event_type_accuracy": round(accuracy, 3),
        "high_value_recall": round(high_recall, 3),
        "housekeeping_false_positive_rate": housekeeping_fpr,
        "ambiguous_abstention_rate": float(abstained),
        "non_game_generalization_rate": float(generalized),
        "case_count": len(cases),
    }


def run_ranking_eval(candidates: list[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    ranked = sorted(
        (STORY_DETECT.rank_event(item) for item in candidates),
        key=lambda item: (-item["story_score"], item["id"]),
    )
    actual = [item["id"] for item in ranked]
    wanted = expected["ranking"]["expected_top_ids"]
    pair_count = sum(actual.index(left) < actual.index(right) for left, right in zip(wanted, wanted[1:]))
    return {
        "order": actual,
        "expected_order": wanted,
        "adjacent_precedence_rate": round(pair_count / (len(wanted) - 1), 3),
        "top_three_reader_value_rate": round(sum(item["story_score"] >= 7 for item in ranked[:3]) / 3, 3),
    }


def run_generate_eval(cases: list[dict[str, Any]]) -> dict[str, Any]:
    outputs: dict[str, str] = {}
    factual = []
    numbers = []
    unsupported = []
    invented_domain = []
    invented_emotion = []
    first_person = []
    emotion_pattern = re.compile(r"终于|突然|兴奋|顿悟|没想到|finally|excited|suddenly", re.IGNORECASE)
    for case in cases:
        detect = case["detect"]
        candidate = {
            "event": detect["subject"],
            "event_type": case["expected_event_type"],
            "technical_change": case["raw_artifact"],
        }
        output = STORY_GENERATE.draft_body(candidate, [case["raw_artifact"]])
        outputs[case["case_id"]] = output
        factual.append(all(str(fact) in output for fact in case["required_facts"]))
        input_numbers = re.findall(r"\d+(?:\.\d+)?%?", case["raw_artifact"])
        numbers.append(all(number in output for number in input_numbers))
        unsupported.append(not any(str(claim) in output for claim in case["forbidden_claims"]))
        domain = ("玩家", "医院", "病人", "房间", "疾病", "诊断")
        invented_domain.append(not any(term in output for term in domain if term not in case["raw_artifact"]))
        invented_emotion.append(not emotion_pattern.search(output))
        first_person.append("我" in output)
    return {
        "factual_fidelity": round(sum(factual) / len(factual), 3),
        "number_preservation": round(sum(numbers) / len(numbers), 3),
        "unsupported_claim_rate": round(1 - sum(unsupported) / len(unsupported), 3),
        "invented_domain_rate": round(1 - sum(invented_domain) / len(invented_domain), 3),
        "invented_emotion_rate": round(1 - sum(invented_emotion) / len(invented_emotion), 3),
        "first_person_consistency": round(sum(first_person) / len(first_person), 3),
        "case_count": len(outputs),
    }


def run_state(root: Path, *args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(STATE_PATH), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def run_memory_eval() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vibesocial-eval-memory-") as temp:
        root = Path(temp)
        run_state(root, "init", "--project-name", "Eval Fixture", "--style", "casual-weibo")
        learning_core = root / "learning-core.json"
        learning_core.write_text(json.dumps({
            "original_sentence": "默认稿件",
            "user_feedback": "以后都写短一些。",
            "replacement": "保留事实但缩短表达。",
            "inferred_rule": "Keep drafts shorter than the default.",
            "rule_key": "density.shorter",
            "scope": "GLOBAL_STYLE",
            "confidence": "high",
            "target": "anti-ai-patterns",
            "promote_core": True,
            "tags": ["concrete-data"],
        }), encoding="utf-8")
        learning_repeated = root / "learning-repeated.json"
        learning_repeated.write_text(json.dumps({
            "original_sentence": "默认稿件",
            "user_feedback": "事实多时可以写长一些。",
            "replacement": "事实多时可以写长一些。",
            "inferred_rule": "Allow a longer draft when facts need space.",
            "rule_key": "facts.numbers",
            "scope": "GLOBAL_STYLE",
            "confidence": "high",
            "target": "writing-style",
            "promote_core": False,
            "tags": ["concrete-data"],
        }), encoding="utf-8")
        candidate = {"event": "API export", "event_type": "feature"}
        candidate_b = {"event": "API export retry", "event_type": "feature"}
        evidence = [
            "The export returns 18 selected records and preserves the request filter after the request is retried.",
            "The output validation keeps the selected records and documents the cache key used for the request.",
        ]
        before = STORY_GENERATE.draft_body(candidate, evidence, STORY_GENERATE.load_memory_context(root))
        events = root / "events.json"
        events.write_text(json.dumps([{
            "type": "feature", "summary": "API export", "problem": "Export was not available",
            "change": "Added the API export endpoint", "user_value": "Selected rows can be exported",
            "public_safe": True,
        }]), encoding="utf-8")
        commit = run_state(root, "commit", "--title", "API export", "--events-file", str(events), "--to-ref", "eval-ref")
        body = root / "draft.md"
        body.write_text(before, encoding="utf-8")
        pr = run_state(
            root, "create-pr", "--commit", commit["id"], "--title", "API export draft",
            "--direction", "具体数据", "--body-file", str(body), "--series", "eval", "--series-number", "1",
        )
        run_state(root, "approve", "--pr", pr["id"], "--learning-file", str(learning_core))
        memory_core = STORY_GENERATE.load_memory_context(root)
        after_core = STORY_GENERATE.draft_body(candidate_b, evidence, memory_core)
        run_state(root, "learn", "--pr", pr["id"], "--learning-file", str(learning_repeated))
        run_state(root, "learn", "--pr", pr["id"], "--learning-file", str(learning_repeated))
        memory = STORY_GENERATE.load_memory_context(root)
        after_repeated = STORY_GENERATE.draft_body(candidate_b, evidence, memory)
        specific_path = root / ".vibesocial" / "feedback-log.md"
        with specific_path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n## Feedback\n- inferred_rule: Keep this local draft shorter.\n"
                "- status: POST_SPECIFIC\n- scope: POST_SPECIFIC\n"
            )
        scoped_memory = STORY_GENERATE.load_memory_context(root)
        other = STORY_GENERATE.draft_body(candidate_b, evidence, memory)
        scoped = STORY_GENERATE.draft_body({**candidate_b, "memory_scope": "POST_SPECIFIC"}, evidence, scoped_memory)
        trace = {
            "draft_count": 2,
            "revision_count": 1,
            "pull_count": 1,
            "approved": True,
            "first_draft_approval_rate": 0.0,
            "average_revisions_before_approve": 1.0,
        }
        return {
            "core_applied": len(after_core) < len(before),
            "repeated_applied": len(after_repeated) > len(after_core) and any("longer" in rule.lower() for rule in memory["repeated"]),
            "post_specific_is_scoped": len(scoped) < len(other),
            "post_specific_does_not_pollute_other": len(other) == len(after_repeated),
            "trace": trace,
        }


def write_commit(root: Path, *, images: bool = False, tagged: bool = True) -> None:
    state_dir = root / ".vibesocial" / "social-commits"
    state_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[str] = []
    if images:
        image = root / "preview.png"
        image.write_bytes(b"not-an-image-but-a-valid-fixture-path")
        image_paths = [str(image)]
    text = "Validated export result.\n#VibeSocial#" if tagged else "Validated export result."
    record = {
        "id": "sc-0001", "status": "APPROVED", "version": 1, "final_text": text,
        "tags": ["VibeSocial"], "mblog_statement": 1, "images": image_paths,
    }
    (state_dir / "sc-0001.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def last_json(text: str) -> dict[str, Any]:
    for index in range(len(text) - 1, -1, -1):
        if text[index] != "{":
            continue
        try:
            value = json.loads(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def run_publish_command(root: Path, cli: Path, env: dict[str, str], input_text: str = "1\n1\n") -> tuple[int, dict[str, Any], dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(WEIBO_PUBLISH_PATH), "publish", "sc-0001", "--root", str(root),
         "--cli", str(cli), "--confirm-publish"],
        input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False, timeout=30,
    )
    commit = load_json(root / ".vibesocial" / "social-commits" / "sc-0001.json")
    output = last_json(result.stdout or "" if result.returncode == 0 else result.stderr or "")
    return result.returncode, output, commit


def run_reconcile_command(root: Path, cli: Path, env: dict[str, str]) -> tuple[int, dict[str, Any], dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(WEIBO_PUBLISH_PATH), "reconcile", "sc-0001", "--root", str(root), "--cli", str(cli)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False, timeout=30,
    )
    commit = load_json(root / ".vibesocial" / "social-commits" / "sc-0001.json")
    return result.returncode, last_json(result.stdout or "" if result.returncode == 0 else result.stderr or ""), commit


def action_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_weibo_eval() -> dict[str, Any]:
    cli = WEIBO_FIXTURES / ("fake_weibo_cli.ps1" if os.name == "nt" else "fake_weibo_cli.sh")
    if os.name != "nt":
        cli.chmod(0o755)
    results: dict[str, bool] = {}

    def run_case(case_id: str, scenario: str = "success", *, images: bool = False, tagged: bool = True) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
        temp = tempfile.TemporaryDirectory(prefix=f"vibesocial-eval-{case_id}-")
        root = Path(temp.name)
        write_commit(root, images=images, tagged=tagged)
        log = root / "fake-cli.log"
        env = os.environ.copy()
        env.update({
            "PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
            "FAKE_WEIBO_SCENARIO": scenario, "FAKE_WEIBO_LOG": str(log),
            "FAKE_WEIBO_STATE": str(root / "fake-state.json"),
        })
        return root, log, {"temp": temp, "env": env, "scenario": scenario}, {}

    root, log, data, _ = run_case("plain-text")
    code, output, commit = run_publish_command(root, cli, data["env"])
    results["plain_text_approved"] = code == 0 and commit.get("status") == "PUBLISHED" and output.get("weibo_id") == "wb-001"
    data["temp"].cleanup()

    root, log, data, _ = run_case("image", images=True)
    code, _, commit = run_publish_command(root, cli, data["env"])
    actions = [item["action"] for item in action_log(log)]
    results["image_approved"] = code == 0 and commit.get("status") == "PUBLISHED" and "statuses upload_pic" in actions and "statuses upload_url_text" in actions
    data["temp"].cleanup()

    root, log, data, _ = run_case("tags", tagged=False)
    code, _, commit = run_publish_command(root, cli, data["env"])
    results["tags"] = code == 0 and commit.get("publish", {}).get("tags") == ["VibeSocial"]
    data["temp"].cleanup()

    root, log, data, _ = run_case("ai-statement")
    code, _, commit = run_publish_command(root, cli, data["env"])
    flags = [flag for item in action_log(log) for flag in item.get("flags", [])]
    results["ai_statement"] = code == 0 and "--mblog_statement" in flags and commit.get("status") == "PUBLISHED"
    data["temp"].cleanup()

    root, log, data, _ = run_case("cancel")
    code, output, commit = run_publish_command(root, cli, data["env"], input_text="1\n4\n")
    results["user_cancel"] = code == 0 and output.get("result") == "cancelled" and commit.get("status") == "APPROVED" and not action_log(log)
    data["temp"].cleanup()

    root, log, data, _ = run_case("schema", scenario="schema_mismatch")
    code, output, commit = run_publish_command(root, cli, data["env"])
    results["schema_mismatch"] = code == 2 and output.get("current_state") == "FAILED_RETRYABLE" and commit.get("status") == "APPROVED"
    data["temp"].cleanup()

    root, log, data, _ = run_case("readback", scenario="readback_mismatch")
    code, output, commit = run_publish_command(root, cli, data["env"])
    results["readback_mismatch"] = code == 2 and output.get("current_state") == "UNKNOWN_REQUIRES_RECONCILIATION" and commit.get("publish", {}).get("remote_id") == "wb-001"
    data["env"]["FAKE_WEIBO_SCENARIO"] = "success"
    reconcile_code, reconcile_output, reconciled = run_reconcile_command(root, cli, data["env"])
    results["unknown_reconcile"] = reconcile_code == 0 and reconcile_output.get("reconciled") is True and reconciled.get("status") == "PUBLISHED"
    data["temp"].cleanup()

    root, log, data, _ = run_case("duplicate")
    first_code, _, first_commit = run_publish_command(root, cli, data["env"])
    before = len(action_log(log))
    second_code, second_output, second_commit = run_publish_command(root, cli, data["env"])
    results["duplicate_publish"] = first_code == 0 and second_code == 2 and second_output.get("current_state") == "PUBLISHED" and len(action_log(log)) == before and second_commit == first_commit
    data["temp"].cleanup()

    root, log, data, _ = run_case("credential", scenario="credential_unavailable")
    code, output, commit = run_publish_command(root, cli, data["env"])
    results["credential_unavailable"] = code == 2 and output.get("current_state") == "FAILED_RETRYABLE" and commit.get("status") == "APPROVED" and not any(item["action"] in {"statuses update", "statuses upload_url_text"} for item in action_log(log))
    data["temp"].cleanup()

    root, log, data, _ = run_case("local-log-failure")
    (root / ".vibesocial" / "published-log.jsonl").mkdir(parents=True)
    code, output, commit = run_publish_command(root, cli, data["env"])
    results["remote_success_local_log_failure"] = code == 0 and commit.get("status") == "PUBLISHED" and "warning" in output
    data["temp"].cleanup()

    return {"passed": sum(results.values()), "total": len(results), "cases": results}


def run_all() -> dict[str, Any]:
    cases = load_json(CASES_PATH)
    ranking = load_json(RANKING_PATH)
    expected = load_json(EXPECTED_PATH)
    validate_cases(cases, expected)
    memory = run_memory_eval()
    generate = run_generate_eval(cases)
    generate["writing_memory_adherence"] = float(all(
        memory[key] for key in ("core_applied", "repeated_applied", "post_specific_is_scoped", "post_specific_does_not_pollute_other")
    ))
    return {
        "benchmark_case_count": len(cases),
        "story_detect": run_detect_eval(cases, expected),
        "story_ranking": run_ranking_eval(ranking, expected),
        "story_generate": generate,
        "writing_memory": memory,
        "weibo_task_eval": run_weibo_eval(),
        "forward_test": {
            "status": "READY_FOR_FORWARD_TEST",
            "reason": "Fresh Codex contexts are not launched by this local deterministic runner.",
            "case_count": len(expected["forward_test"]["case_ids"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="Validate benchmark contracts without running tasks")
    parser.add_argument("--output", default=str(ROOT / "evals" / "results" / "summary.json"))
    args = parser.parse_args()
    cases = load_json(CASES_PATH)
    ranking = load_json(RANKING_PATH)
    expected = load_json(EXPECTED_PATH)
    validate_cases(cases, expected)
    if args.validate_only:
        print(json.dumps({"valid": True, "benchmark_case_count": len(cases), "ranking_candidate_count": len(ranking)}, ensure_ascii=False))
        return 0
    summary = run_all()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
