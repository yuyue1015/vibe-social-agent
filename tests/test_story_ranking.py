import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "story_detect.py"
SPEC = importlib.util.spec_from_file_location("story_detect_ranking", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def event(event_type, *, user_visible=False, reader_angle="用户可以看到具体变化。", why="普通用户会关心结果。", technical_change="明确模块发生了变化。", source="git:abc"):
    return {
        "event": "测试事件",
        "event_type": event_type,
        "source": source,
        "technical_change": technical_change,
        "reader_angle": reader_angle,
        "why_people_care": why,
        "areas": ["实现"],
        "user_visible": user_visible,
        "public_status": "适合进入候选",
        "source_count": 1,
        "explicit_result": False,
    }


class StoryRankingTests(unittest.TestCase):
    def test_complex_architecture_without_user_effect_is_not_high(self):
        result = MODULE.rank_event(event("architecture_change", technical_change="重构复杂核心引擎，没有确认用户可见变化。", reader_angle="当前没有明确的用户可见后果。", why="当前没有明确的用户可见后果。"))
        self.assertLess(result["story_score"], 7)

    def test_small_bug_with_user_effect_can_score_high(self):
        result = MODULE.rank_event(event("bug_fix", user_visible=True, technical_change="修复玩家点击地图后路线错误的 Bug。", source="git:bug123"))
        self.assertGreaterEqual(result["story_score"], 7)

    def test_failure_process_raises_turning_point_score(self):
        failed = MODULE.rank_event(event("failed_attempt", technical_change="第一次方案失败，重新改用更简单的测试路径。"))
        ordinary = MODULE.rank_event(event("experiment", technical_change="做了一次普通方案试验。"))
        self.assertGreater(failed["story_score"], ordinary["story_score"])

    def test_missing_reader_angle_lowers_score(self):
        result = MODULE.rank_event(event("feature", reader_angle="", why=""))
        self.assertLess(result["story_score"], 7)

    def test_detector_does_not_read_or_emit_source_content(self):
        commit = {"hash": "abc", "date": "2026-08-15", "subject": "add feature", "paths": ["src/secret.py"]}
        result = MODULE.candidate_for(commit)
        self.assertNotIn("source code that must stay private", str(result))
        rendered = MODULE.render(Path("TPHhelper"), [result])
        self.assertNotIn("def ", rendered)
        self.assertNotIn("微博正文", rendered)

    def test_summary_sources_exclude_source_code_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "validation_notes.md").write_text("# Validation", encoding="utf-8")
            (docs / "test_validation.py").write_text("def private_source(): pass", encoding="utf-8")
            (docs / "README.md").write_text("# Project overview", encoding="utf-8")
            paths = MODULE.summary_candidates(root)
        self.assertEqual(["validation_notes.md"], [path.name for path in paths])


if __name__ == "__main__":
    unittest.main()
