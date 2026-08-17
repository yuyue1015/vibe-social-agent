import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "story_aggregate.py"
SPEC = importlib.util.spec_from_file_location("story_aggregate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def story(story_id, topic, stage="refinement", *, event_type="architecture_change", roles=None, before_after=False, screenshot=False, complete=False):
    return {
        "id": story_id,
        "status": "STORY",
        "title": f"{topic} {story_id}",
        "topic": topic,
        "summary": f"{topic} 的开发变化",
        "stage": stage,
        "event_type": event_type,
        "arc_roles": roles or [],
        "has_before_after": before_after,
        "has_screenshot": screenshot,
        "stage_complete": complete,
    }


class StoryAggregationTests(unittest.TestCase):
    def test_unrelated_stories_are_not_forced_into_one_group(self):
        stories = [
            story("map-1", "地图网格"),
            story("diagnosis-1", "诊断房间"),
            story("staff-1", "员工技能"),
            story("ui-1", "移动界面"),
        ]
        self.assertEqual([], MODULE.aggregate(stories))

    def test_same_stage_and_topic_can_aggregate(self):
        stories = [story(f"diag-{index}", "诊断引擎") for index in range(1, 4)]
        candidates = MODULE.aggregate(stories)
        self.assertEqual(1, len(candidates))
        self.assertEqual({"diag-1", "diag-2", "diag-3"}, set(candidates[0]["included_story_ids"]))

    def test_complete_arc_can_form_candidate_with_fewer_than_four_stories(self):
        stories = [
            story("origin", "诊断引擎", "origin", roles=["origin", "problem"]),
            story("adjust", "诊断引擎", "refinement", roles=["adjustment"], event_type="failed_attempt"),
            story("result", "诊断引擎", "validation", roles=["result"], event_type="experiment"),
        ]
        candidates = MODULE.aggregate(stories)
        self.assertEqual(1, len(candidates))
        self.assertIn("起点", candidates[0]["narrative_arc"])
        self.assertIn("结果", candidates[0]["narrative_arc"])

    def test_four_unrelated_stories_do_not_qualify_by_count(self):
        stories = [story(f"item-{index}", topic) for index, topic in enumerate(("地图", "疾病", "员工", "界面"), 1)]
        self.assertEqual([], MODULE.aggregate(stories))

    def test_aggregation_does_not_copy_or_modify_post_body(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [story(f"diag-{index}", "诊断引擎") for index in range(1, 5)]
            records[0]["final_text"] = "ORIGINAL_WEIBO_BODY"
            source = root / "stories.json"
            source.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            before = source.read_text(encoding="utf-8")
            loaded = MODULE.load_stories(root, source)
            output = MODULE.render(root, loaded, MODULE.aggregate(loaded))
            after = source.read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertNotIn("ORIGINAL_WEIBO_BODY", output)
        self.assertNotIn("## Draft", output)
        self.assertNotIn("正文", output)
        self.assertIn("阶段性素材聚合", output)
        self.assertIn("灵感候选", output)

    def test_aggregation_outputs_material_candidates_only(self):
        stories = [story(f"diag-{index}", "诊断引擎") for index in range(1, 5)]
        output = MODULE.render(Path("."), stories, MODULE.aggregate(stories))
        for field in ("included_story_ids", "stage_summary", "narrative_arc", "why_now", "missing_material", "readiness_score"):
            self.assertIn(field, output)
        self.assertNotIn("final_text", output)
        self.assertNotIn("## Draft", output)
        self.assertNotIn("生成", output)
        self.assertNotIn("发布", output)

    def test_recommendation_is_inspiration_only(self):
        stories = [story(f"diag-{index}", "诊断引擎") for index in range(1, 5)]
        recommendation = MODULE.aggregate(stories)[0]["recommendation"]
        self.assertIn(recommendation, {"继续积累素材", "已具备阶段性内容灵感", "可作为未来小红书选题素材"})
        self.assertNotIn("生成", recommendation)
        self.assertNotIn("发布", recommendation)
        self.assertNotIn("正文", recommendation)

    def test_aggregation_has_no_publish_or_platform_generator_hook(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("weibo-cli", source)
        self.assertNotIn("weibo_publish", source)
        self.assertNotIn("xhs_generate", source)

    def test_aggregation_does_not_create_weibo_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stories = [story(f"diag-{index}", "诊断引擎") for index in range(1, 5)]
            output = root / ".vibesocial" / "aggregation-candidates.md"
            output.parent.mkdir()
            output.write_text(MODULE.render(root, stories, MODULE.aggregate(stories)), encoding="utf-8")
            self.assertFalse((output.parent / "story-draft.md").exists())


if __name__ == "__main__":
    unittest.main()
