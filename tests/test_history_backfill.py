import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "vibe_state.py"


class HistoryBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "init", "--project-name", "History Fixture"], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_confirmed_history_becomes_example_and_plan_gaps_stay_null(self):
        history = self.root / "history.json"
        history.write_text(json.dumps({
            "series": "双点医院诊疗模拟器",
            "fixed_title": "【我给《双点医院》做了一个诊疗模拟器｜开发日志XX】",
            "fixed_tags": ["#微博VibeLab#"],
            "current_number": "08",
            "approved_numbers": ["01"],
            "draft": "08",
            "approved": [{"number": "01", "final_text": "【标题】真实最终稿"}],
            "feedback": [{"social_commit_id": "BACKFILL-1", "rule_key": "test.core", "scope": "GLOBAL_STYLE", "inferred_rule": "保留具体事实", "user_feedback": "以后记住", "status": "CORE"}],
            "plan": {"01": {"topic": "已确认主题", "status": "approved"}, "08": {"topic": "当前草稿", "status": "draft"}},
        }, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "backfill-history", "--history-file", str(history)], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(1, json.loads(result.stdout)["approved_examples_added"])
        examples = (self.root / ".vibesocial" / "approved-examples.md").read_text(encoding="utf-8")
        state = (self.root / ".vibesocial" / "series-state.md").read_text(encoding="utf-8")
        self.assertIn("真实最终稿", examples)
        self.assertNotIn("08", examples)
        self.assertIn("number: 09\n    topic: null", state)


if __name__ == "__main__":
    unittest.main()
