import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "story_detect.py"
SPEC = importlib.util.spec_from_file_location("story_detect_journey", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def candidate(event_type, event="测试故事"):
    return {
        "event": event,
        "event_type": event_type,
        "source": "git:abc",
        "technical_change": event,
        "reader_angle": "普通用户可以理解这个变化。",
        "why_people_care": "它会影响读者看到的结果。",
        "story_score": 7,
        "confidence": "medium",
        "publish_suggestion": "可以进入 Social Commit 前的人工核实",
        "public_status": "适合进入候选",
    }


class StoryJourneyTests(unittest.TestCase):
    def test_approved_examples_do_not_count_as_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_dir = root / ".vibesocial"
            state_dir.mkdir()
            (state_dir / "approved-examples.md").write_text("published_at: not supplied\n", encoding="utf-8")
            result, state = MODULE.apply_journey([candidate("performance")], root)
            self.assertIsNone(state["current_stage"])
            self.assertEqual("origin", state["next_preferred_stage"])
            self.assertEqual("needs_published_history", result[0]["journey_fit"])

    def test_published_origin_prefers_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commits = root / ".vibesocial" / "social-commits"
            commits.mkdir(parents=True)
            (commits / "sc-0001.json").write_text(json.dumps({
                "id": "sc-0001", "status": "PUBLISHED", "title": "为什么开始做这个工具",
                "series": "示例系列", "publish": {"platform": "weibo", "published_at": "2026-08-01"},
                "final_text": "完整正文不应进入 Journey 状态。",
            }, ensure_ascii=False), encoding="utf-8")
            result, state = MODULE.apply_journey([candidate("failed_attempt", "第一次遇到数据问题")], root)
            self.assertEqual("origin", state["current_stage"])
            self.assertEqual("discovery", state["next_preferred_stage"])
            self.assertEqual("suitable_now", result[0]["journey_fit"])

    def test_journey_state_stores_cadence_not_full_post(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commits = root / ".vibesocial" / "social-commits"
            commits.mkdir(parents=True)
            (commits / "sc-0001.json").write_text(json.dumps({
                "id": "sc-0001", "status": "PUBLISHED", "title": "起点故事",
                "publish": {"platform": "weibo", "published_at": "2026-08-01"},
                "final_text": "SECRET_FULL_POST_TEXT",
            }), encoding="utf-8")
            MODULE.write_journey_state(root)
            state_text = (root / ".vibesocial" / MODULE.JOURNEY_STATE_NAME).read_text(encoding="utf-8")
            self.assertNotIn("SECRET_FULL_POST_TEXT", state_text)
            self.assertNotIn("final_text", state_text)

    def test_same_stage_is_marked_as_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commits = root / ".vibesocial" / "social-commits"
            commits.mkdir(parents=True)
            (commits / "sc-0001.json").write_text(json.dumps({
                "id": "sc-0001", "status": "PUBLISHED", "title": "起点故事",
                "publish": {"platform": "weibo", "published_at": "2026-08-01"},
            }), encoding="utf-8")
            result, _ = MODULE.apply_journey([candidate("feature", "为什么开始做另一个功能")], root)
            self.assertEqual("avoid_repeat", result[0]["journey_fit"])


if __name__ == "__main__":
    unittest.main()
