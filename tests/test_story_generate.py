import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "story_generate.py"
FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "story-generate"
SPEC = importlib.util.spec_from_file_location("story_generate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class StoryGenerateTests(unittest.TestCase):
    def test_generates_draft_from_selected_summary_without_source_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "validation_report.md").write_text(
                "# Validation report\n\n279 cases passed against the Golden Case set.\n\npython scripts/private_check.py\n\nprivate source should not be copied.\n",
                encoding="utf-8",
            )
            candidates = root / "story-candidates.md"
            candidates.write_text(
                """# Development story candidates\n\n## Candidate 1 — milestone\n- event: 诊断结果验证\n- event_type: milestone\n- source: summary:docs/validation_report.md\n- technical_change: 从验证记录中确认诊断结果\n- reader_angle: 玩家可以更容易理解结果是否可靠。\n- why_people_care: 结果是否稳定会影响使用体验。\n- story_score: 8/10\n- journey_stage: validation\n- journey_fit: suitable_now\n- public_status: 适合进入候选\n""",
                encoding="utf-8",
            )
            text = MODULE.generate(root, candidates, "诊断结果验证")
            self.assertIn("【我在看诊断结果验证】", text)
            self.assertIn("诊断", text)
            self.assertIn("279 cases passed", text)
            self.assertNotIn("private source should not be copied", text)
            self.assertNotIn("scripts/private_check.py", text)
            self.assertNotIn("source:", text)
            self.assertNotIn("NEEDS_HUMAN_REVIEW", text)
            self.assertNotIn("Review checklist", text)

    def test_rejects_candidate_marked_not_public(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates = root / "story-candidates.md"
            candidates.write_text(
                """## Candidate 1 — architecture_change\n- event: 内部规划\n- event_type: architecture_change\n- source: git:abc123\n- public_status: 不建议公开\n""",
                encoding="utf-8",
            )
            with self.assertRaises(MODULE.StoryGenerateError):
                MODULE.generate(root, candidates, "内部规划")

    def test_can_select_candidate_by_number(self):
        candidates = [
            {"event": "第一条", "source": "git:a"},
            {"event": "第二条", "source": "git:b"},
        ]
        self.assertEqual("第二条", MODULE.select_candidate(candidates, "2")["event"])

    def test_candidate_lookup_ignores_markdown_backticks(self):
        candidates = [{"event": "标准房间与 `*` 房间配置对比验证报告", "source": "summary:docs/report.md"}]
        selected = MODULE.select_candidate(candidates, "标准房间与 * 房间配置对比验证报告")
        self.assertEqual("标准房间与 `*` 房间配置对比验证报告", selected["event"])

    def test_experiment_uses_companion_entry_not_report_language(self):
        candidate = {
            "event": "房间配置对比验证",
            "event_type": "experiment",
            "technical_change": "比较不同房间配置下的诊断结果",
            "reader_angle": "房间配置会影响诊断流程",
        }
        text = MODULE.draft_body(candidate, ["点金术达到 90% 的预计诊断次数从 3 次变为 2 次"])
        self.assertIn("90%", text)
        self.assertIn("3 次变为 2 次", text)
        self.assertNotIn("进行了实验", text)
        self.assertNotIn("实验报告", text)

    def test_bug_story_does_not_say_found_a_bug(self):
        candidate = {
            "event": "患者路线错误修复",
            "event_type": "bug_fix",
            "technical_change": "修复玩家点击地图后路线错误",
        }
        text = MODULE.draft_body(candidate, ["玩家点击地图后路线错误，病人没有进入预期房间"])
        self.assertIn("玩家", text)
        self.assertIn("病人", text)
        self.assertNotIn("发现了bug", text.lower())
        self.assertNotIn("修复了一个bug", text.lower())

    def test_no_report_audience_phrase_or_invented_psychology(self):
        candidate = {
            "event": "第一次跑通诊断流程",
            "event_type": "milestone",
            "technical_change": "第一个可运行的诊断流程",
        }
        text = MODULE.draft_body(candidate, ["第一次运行得到 90% 诊断结果"])
        for phrase in ("我突然发现", "我没想到", "我终于意识到", "原来如此"):
            self.assertNotIn(phrase, text)

    def test_output_is_plain_body_without_metadata(self):
        candidate = {
            "event": "具体疾病诊断",
            "event_type": "experiment",
            "technical_change": "比较诊断次数",
            "source": "summary:docs/report.md",
            "story_score": "8/10",
        }
        text = MODULE.draft_body(candidate, ["鬼畜腰从 9 次变为 5 次"])
        self.assertNotIn("source", text.lower())
        self.assertNotIn("score", text.lower())
        self.assertNotIn("checklist", text.lower())
        self.assertNotIn("generated_at", text)
        self.assertNotIn("metadata", text.lower())
        self.assertNotIn("NEEDS_HUMAN_REVIEW", text)

    def test_concrete_number_is_preserved(self):
        candidate = {
            "event": "诊断配置变化",
            "event_type": "experiment",
            "technical_change": "比较诊断配置",
        }
        text = MODULE.draft_body(candidate, ["点金术达到 90% 的预计诊断次数从 3 次变为 2 次"])
        self.assertIn("3 次变为 2 次", text)

    def test_non_game_projects_do_not_receive_game_domain_narrative(self):
        fixtures = [
            ("CLI cache export", "non-game-cli.md"),
            ("SaaS billing screen", "saas-web.md"),
            ("API batch endpoint", "api-data.md"),
        ]
        forbidden = ("玩家", "医院", "病人", "房间", "疾病", "诊断")
        for event, fixture_name in fixtures:
            with self.subTest(event=event):
                text = MODULE.draft_body(
                    {"event": event, "event_type": "feature", "technical_change": event},
                    (FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8").splitlines(),
                )
                self.assertFalse(any(word in text for word in forbidden), text)

    def test_numbers_are_preserved_and_missing_numbers_are_not_invented(self):
        text = MODULE.draft_body(
            {"event": "cache key correction", "event_type": "bug_fix"},
            ["The operation changed from 18 attempts to 11 attempts."],
        )
        self.assertIn("18", text)
        self.assertIn("11", text)
        no_new_number = MODULE.draft_body(
            {"event": "endpoint validation", "event_type": "bug_fix"},
            ["Invalid identifiers now return an error."],
        )
        self.assertNotIn("30%", no_new_number)

    def test_memory_priority_and_post_specific_scope(self):
        candidate = {"event": "cache export", "event_type": "feature"}
        evidence = [
            "The export includes 18 records and returns the cache result after the request is retried.",
            "The output keeps the selected record and explains which cache key was used.",
        ]
        plain = MODULE.draft_body(candidate, evidence, {"core": [], "repeated": [], "post_specific": ["shorter"]})
        scoped = MODULE.draft_body(
            {**candidate, "memory_scope": "POST_SPECIFIC"},
            evidence,
            {"core": [], "repeated": [], "post_specific": ["shorter"]},
        )
        self.assertGreaterEqual(len(plain), len(scoped))
        self.assertIn("18", scoped)
        repeated_long = MODULE.draft_body(
            candidate,
            evidence,
            {"core": ["Keep drafts shorter."], "repeated": ["Allow a longer draft when facts need space."], "post_specific": []},
        )
        local_short = MODULE.draft_body(
            {**candidate, "style_instruction": "这篇更短一些。"},
            evidence,
            {"core": [], "repeated": ["Allow a longer draft when facts need space."], "post_specific": []},
        )
        self.assertGreater(len(repeated_long), len(local_short))

    def test_memory_anti_ai_rule_controls_opening_without_adding_facts(self):
        candidate = {"event": "API export", "event_type": "feature"}
        evidence = ["The export returns the selected records."]
        text = MODULE.draft_body(
            candidate,
            evidence,
            {"core": ["Avoid forced question openings."], "repeated": [], "post_specific": []},
        )
        self.assertIn("我先把", text)
        self.assertNotIn("为什么", text)
        self.assertNotIn("用户反馈", text)


if __name__ == "__main__":
    unittest.main()
