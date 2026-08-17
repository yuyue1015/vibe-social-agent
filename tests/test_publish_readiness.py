import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "story_detect.py"
SPEC = importlib.util.spec_from_file_location("story_detect_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
FIXTURES = Path(__file__).parents[1] / "fixtures" / "publish-readiness"


def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["candidates"]


def seed_published_history(root: Path, title: str = "第一个可运行版本") -> None:
    commits = root / ".vibesocial" / "social-commits"
    commits.mkdir(parents=True)
    (commits / "sc-0001.json").write_text(json.dumps({
        "id": "sc-0001",
        "status": "PUBLISHED",
        "title": title,
        "publish": {"platform": "weibo", "published_at": "2026-08-01"},
    }, ensure_ascii=False), encoding="utf-8")


class PublishReadinessTests(unittest.TestCase):
    def test_tph_roomtemplate_separates_score_from_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            results, _ = MODULE.apply_journey(load_fixture("tph-roomtemplate.json"), Path(temp))
        by_id = {item["id"]: item for item in results}
        self.assertEqual("ready", by_id["first-usable-1-0-0"]["publish_readiness"]["status"])
        self.assertEqual("hold", by_id["three-games-2-0-0"]["publish_readiness"]["status"])
        self.assertEqual("hold", by_id["unity-resource-experiment"]["publish_readiness"]["status"])
        self.assertEqual(9, by_id["three-games-2-0-0"]["story_score"])
        self.assertNotEqual(by_id["three-games-2-0-0"]["story_score"], 10)

    def test_tphhelper_verified_core_beats_unfinished_experiment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed_published_history(root)
            results, _ = MODULE.apply_journey(load_fixture("TPHhelper.json"), root)
        by_id = {item["id"]: item for item in results}
        self.assertEqual("ready", by_id["validated-core-fix"]["publish_readiness"]["status"])
        self.assertEqual("hold", by_id["unfinished-ui-experiment"]["publish_readiness"]["status"])
        self.assertEqual("validated", by_id["validated-core-fix"]["completion"])

    def test_vibe_social_agent_completed_capability_beats_future_concept(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed_published_history(root)
            results, _ = MODULE.apply_journey(load_fixture("vibe-social-agent.json"), root)
        by_id = {item["id"]: item for item in results}
        self.assertEqual("ready", by_id["completed-skill-capability"]["publish_readiness"]["status"])
        self.assertEqual("hold", by_id["future-concept"]["publish_readiness"]["status"])

    def test_duplicate_and_insufficient_evidence_are_skipped(self):
        duplicate = load_fixture("tph-roomtemplate.json")[0]
        duplicate["event"] = "已发布的核心故事"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed_published_history(root, "已发布的核心故事")
            results, _ = MODULE.apply_journey([duplicate], root)
        self.assertEqual("skip", results[0]["publish_readiness"]["status"])

        readme_only = dict(duplicate)
        readme_only["event"] = "README 功能描述"
        readme_only["evidence_level"] = "supporting"
        readme_only["completion"] = "complete"
        with tempfile.TemporaryDirectory() as temp:
            results, _ = MODULE.apply_journey([readme_only], Path(temp))
        self.assertEqual("skip", results[0]["publish_readiness"]["status"])

    def test_latest_or_high_score_does_not_override_readiness_order(self):
        ready = load_fixture("tph-roomtemplate.json")[0]
        latest_experiment = load_fixture("tph-roomtemplate.json")[2]
        latest_experiment["source"] = "summary:latest.md"
        with tempfile.TemporaryDirectory() as temp:
            results, _ = MODULE.apply_journey([latest_experiment, ready], Path(temp))
        self.assertEqual("ready", results[0]["publish_readiness"]["status"])
        self.assertEqual("hold", results[1]["publish_readiness"]["status"])


if __name__ == "__main__":
    unittest.main()
