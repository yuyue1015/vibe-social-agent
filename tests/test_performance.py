import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "performance.py"
STATE = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "vibe_state.py"


class PerformanceLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run([sys.executable, str(STATE), "--root", str(self.root), "init", "--project-name", "Performance Fixture"], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args], capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(result.stdout)

    def write_entries(self, count):
        path = self.root / ".vibesocial" / "performance-log.jsonl"
        rows = []
        for index in range(count):
            rows.append({
                "social_commit_id": f"sc-{index:04d}",
                "weibo_id": str(index),
                "published_at": "2026-08-15T00:00:00+00:00",
                "content_features": {"char_count": 180, "has_bug": bool(index % 2)},
                "snapshots": [{"captured_at": f"2026-08-15T01:{index:02d}:00+00:00", "age_hours": 1, "metrics": {"read_count": index * 10, "like_count": index}}],
            })
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    def test_fewer_than_five_is_observation_only(self):
        self.write_entries(2)
        result = self.run_cli("analyze")
        self.assertEqual("OBSERVATION_ONLY", result["status"])
        insights = (self.root / ".vibesocial" / "performance-insights.md").read_text(encoding="utf-8")
        self.assertIn("Reach", insights)
        self.assertIn("fewer than 5", insights)

    def test_five_enables_description_without_writing_memory(self):
        self.write_entries(5)
        result = self.run_cli("analyze")
        self.assertEqual("DESCRIPTIVE_COMPARISON", result["status"])
        self.assertEqual(["like_count", "read_count"], result["metric_keys"])
        style = (self.root / ".vibesocial" / "writing-style.md").read_text(encoding="utf-8")
        self.assertNotIn("Performance", style)


if __name__ == "__main__":
    unittest.main()
