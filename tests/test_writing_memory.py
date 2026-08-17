import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "vibe_state.py"
STORY_SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "story_generate.py"
STORY_SPEC = importlib.util.spec_from_file_location("story_generate_memory", STORY_SCRIPT)
STORY_MODULE = importlib.util.module_from_spec(STORY_SPEC)
assert STORY_SPEC and STORY_SPEC.loader
STORY_SPEC.loader.exec_module(STORY_MODULE)


class WritingMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(expect, result.returncode, result.stderr or result.stdout)
        return json.loads(result.stdout if expect == 0 else result.stderr)

    def init(self):
        self.run_cli("init", "--project-name", "Memory Fixture", "--style", "casual-weibo")

    def make_approved(self, number=1, series="诊疗模拟器"):
        events = self.root / f"events-{number}.json"
        events.write_text(json.dumps([{
            "type": "bug_fix", "summary": f"Fixed concrete bug {number}",
            "problem": "A player-facing result was wrong", "change": "Corrected the rule",
            "user_value": "The result is easier to trust", "public_safe": True,
        }]), encoding="utf-8")
        commit = self.run_cli(
            "commit", "--title", f"Bug fix {number}", "--events-file", str(events), "--to-ref", f"ref-{number}",
        )
        body = self.root / f"draft-{number}.md"
        body.write_text(f"【诊疗模拟器】我修了第 {number} 个结果 Bug，玩家现在能看懂它为什么这样判断。", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", f"Draft {number}",
            "--direction", "具体 Bug", "--body-file", str(body), "--series", series, "--series-number", str(number),
        )
        return commit, pr, body

    def learning_file(self, name, rule_key="anti_ai.question", scope="GLOBAL_STYLE", promote=False):
        path = self.root / name
        path.write_text(json.dumps({
            "original_sentence": "为什么这个功能很重要？",
            "user_feedback": "以后都不要用营销号式设问开头。" if promote else "这篇不要用设问开头。",
            "replacement": "我先把具体 Bug 写清楚。",
            "inferred_rule": "Avoid forced question openings.",
            "rule_key": rule_key,
            "scope": scope,
            "confidence": "high",
            "target": "anti-ai-patterns",
            "promote_core": promote,
            "tags": ["concrete-data"],
        }), encoding="utf-8")
        return path

    def test_approved_writes_final_example(self):
        self.init()
        commit, pr, _ = self.make_approved()
        self.run_cli("approve", "--pr", pr["id"], "--tags", "bug-story")
        examples = (self.root / ".vibesocial" / "approved-examples.md").read_text(encoding="utf-8")
        self.assertIn(f"Social Commit ID: {commit['id']}", examples)
        self.assertIn("final_text:", examples)

    def test_explicit_negative_enters_feedback_log(self):
        self.init()
        _, pr, _ = self.make_approved()
        learning = self.learning_file("negative.json", promote=True)
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        log = (self.root / ".vibesocial" / "feedback-log.md").read_text(encoding="utf-8")
        self.assertIn("anti_ai.question", log)
        self.assertIn("CORE", log)

    def test_same_rule_key_accumulates(self):
        self.init()
        _, pr, _ = self.make_approved()
        learning = self.learning_file("rule.json", rule_key="density.concrete")
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        self.run_cli("learn", "--pr", pr["id"], "--learning-file", str(learning))
        log = (self.root / ".vibesocial" / "feedback-log.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(log.count("- rule_key: density.concrete"), 2)
        self.assertIn("REPEATED", log)

    def test_conflicting_rule_is_recorded_without_silent_overwrite(self):
        self.init()
        _, pr, _ = self.make_approved()
        learning = self.learning_file("conflict.json", rule_key="density.concrete")
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        changed = json.loads(learning.read_text(encoding="utf-8"))
        changed["inferred_rule"] = "Allow a broad summary when the post is short."
        learning.write_text(json.dumps(changed), encoding="utf-8")
        self.run_cli("learn", "--pr", pr["id"], "--learning-file", str(learning))
        log = (self.root / ".vibesocial" / "feedback-log.md").read_text(encoding="utf-8")
        self.assertIn("- conflict: Existing rule kept visible", log)

    def test_core_rule_enters_next_memory_context(self):
        self.init()
        _, pr, _ = self.make_approved()
        learning = self.learning_file("core.json", promote=True)
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        context = self.run_cli("memory-context")
        self.assertIn("Avoid forced question openings.", context["anti-ai-patterns"])

    def test_post_specific_does_not_pollute_global_memory(self):
        self.init()
        _, pr, _ = self.make_approved()
        learning = self.learning_file("specific.json", rule_key="post.sc-0001", scope="POST_SPECIFIC")
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        style = (self.root / ".vibesocial" / "writing-style.md").read_text(encoding="utf-8")
        self.assertNotIn("Avoid forced question openings.", style)

    def test_series_state_is_updated_for_next_article(self):
        self.init()
        _, pr, _ = self.make_approved(number=8, series="诊疗模拟器")
        self.run_cli("approve", "--pr", pr["id"])
        state = (self.root / ".vibesocial" / "series-state.md").read_text(encoding="utf-8")
        self.assertIn("series: 诊疗模拟器", state)
        self.assertIn("current_number: 08", state)
        self.assertIn("sc-0001", state)

    def test_critic_flags_anti_ai_and_missing_detail(self):
        self.init()
        draft = self.root / "critic.md"
        draft.write_text("这次才发现，我们要持续优化体验。为什么这很重要？", encoding="utf-8")
        result = self.run_cli("critique", "--text-file", str(draft))
        keys = {issue["key"] for issue in result["issues"]}
        self.assertIn("concrete_detail", keys)
        self.assertIn("invented_emotion", keys)

    def test_unapproved_draft_is_not_positive_example(self):
        self.init()
        _, _, _ = self.make_approved()
        examples = (self.root / ".vibesocial" / "approved-examples.md").read_text(encoding="utf-8")
        self.assertNotIn("final_text: 【诊疗模拟器】", examples)

    def test_approved_pr_is_not_rewritten_on_repeat_approval(self):
        self.init()
        _, pr, body = self.make_approved()
        self.run_cli("approve", "--pr", pr["id"])
        before = body.read_text(encoding="utf-8")
        result = self.run_cli("approve", "--pr", pr["id"])
        self.assertEqual("APPROVED", result["status"])
        self.assertEqual(before, body.read_text(encoding="utf-8"))

    def test_series_template_forbids_previous_body_inference(self):
        self.init()
        state = (self.root / ".vibesocial" / "series-state.md").read_text(encoding="utf-8")
        self.assertIn("Do not infer the next topic from the previous body", state)

    def test_core_memory_changes_the_next_story_generate(self):
        self.init()
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "cli-report.md").write_text(
            "The command exports the cache report after a request error.\n"
            "The output keeps the selected record and explains which cache key was used.\n"
            "The same report can be checked again without changing the source data.",
            encoding="utf-8",
        )
        candidates = self.root / "candidates.md"
        candidates.write_text(
            "# Development story candidates\n\n"
            "## Candidate 1 — feature\n"
            "- event: CLI cache export\n"
            "- event_type: feature\n"
            "- source: summary:docs/cli-report.md\n"
            "- technical_change: Added a cache export command\n"
            "- public_status: 适合进入候选\n",
            encoding="utf-8",
        )
        before = STORY_MODULE.generate(self.root, candidates, "CLI cache export")
        _, pr, _ = self.make_approved(number=20)
        learning = self.root / "shorter.json"
        learning.write_text(json.dumps({
            "user_feedback": "以后都写短一些。",
            "inferred_rule": "Keep the draft shorter than the default.",
            "rule_key": "length.shorter",
            "scope": "GLOBAL_STYLE",
            "confidence": "high",
            "promote_core": True,
            "target": "writing-style",
            "tags": ["concise"],
        }), encoding="utf-8")
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        after = STORY_MODULE.generate(self.root, candidates, "CLI cache export")
        self.assertLess(len(after), len(before))
        self.assertIn("Keep the draft shorter", "\n".join(STORY_MODULE.load_memory_context(self.root)["core"]))

    def test_post_specific_memory_does_not_apply_to_other_story(self):
        self.init()
        feedback = self.root / ".vibesocial" / "feedback-log.md"
        feedback.write_text(
            "## Feedback — local\n"
            "- inferred_rule: Keep this draft shorter.\n"
            "- rule_key: post.shorter\n"
            "- scope: POST_SPECIFIC\n"
            "- status: OBSERVED\n",
            encoding="utf-8",
        )
        context = STORY_MODULE.load_memory_context(self.root)
        self.assertIn("Keep this draft shorter.", context["post_specific"])
        candidate = {"event": "API export", "event_type": "feature"}
        evidence = ["The export returns the selected records and the request status for the current batch."]
        without_scope = STORY_MODULE.draft_body(candidate, evidence, context)
        with_scope = STORY_MODULE.draft_body({**candidate, "memory_scope": "POST_SPECIFIC"}, evidence, context)
        self.assertGreaterEqual(len(without_scope), len(with_scope))


if __name__ == "__main__":
    unittest.main()
