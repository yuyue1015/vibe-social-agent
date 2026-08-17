import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "story_detect.py"
SPEC = importlib.util.spec_from_file_location("story_detect", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
FIXTURE = Path(__file__).parents[1] / "evals" / "fixtures" / "projects" / "existing-no-commit"
HISTORY_FIXTURE = FIXTURE / "history" / "social-commits" / "sc-0001.json"


def init_empty_git(root: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "init"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def copy_existing_project_fixture(root: Path, include_runtime_state: bool = False) -> None:
    for item in FIXTURE.iterdir():
        if item.name == "history":
            continue
        destination = root / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)
    if include_runtime_state:
        state = root / ".vibesocial" / "social-commits"
        state.mkdir(parents=True)
        shutil.copy2(HISTORY_FIXTURE, state / HISTORY_FIXTURE.name)


class DevelopmentStoryTests(unittest.TestCase):
    def test_commit_trace_becomes_story_lead_not_post(self):
        history = """__VIBESOCIAL_STORY_COMMIT__
abc1234
2026-08-15
fix: correct patient routing threshold
M\tapplication/engine.py
M\ttests/test_routing.py
"""
        commits = MODULE.parse_history(history)
        self.assertEqual(1, len(commits))
        candidate = MODULE.candidate_for(commits[0])
        self.assertEqual("bug_fix", candidate["event_type"])
        self.assertIn("用户", candidate["why_people_care"])
        self.assertIn("story_score", MODULE.render(Path("TPHhelper"), [candidate]))
        self.assertNotIn("微博正文", MODULE.render(Path("TPHhelper"), [candidate]))

    def test_sensitive_and_unpublished_paths_are_not_recommended(self):
        commit = {
            "hash": "bad1234",
            "date": "2026-08-15",
            "subject": "docs: establish roadmap v2",
            "paths": ["docs/PROJECT_ROADMAP_V2.0.md", "exports/private.zip"],
        }
        candidate = MODULE.candidate_for(commit)
        self.assertEqual("不建议公开", candidate["public_status"])
        self.assertEqual("不建议转为故事", candidate["publish_suggestion"])

    def test_render_does_not_persist_absolute_source_path(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "TPHhelper"
            output = MODULE.render(source, [])
        self.assertIn("source_scope: TPHhelper", output)
        self.assertNotIn(temp, output)

    def test_non_game_change_uses_generic_concrete_signals(self):
        commit = {
            "hash": "api1234",
            "date": "2026-08-15",
            "subject": "fix: cache key for API export returned stale records",
            "paths": ["src/cache.py", "tests/test_export.py"],
        }
        candidate = MODULE.candidate_for(commit)
        self.assertEqual("bug_fix", candidate["event_type"])
        self.assertIn("cache", candidate["event"])
        self.assertNotIn("玩家", candidate["reader_angle"] + candidate["why_people_care"])

    def test_no_commit_uses_working_tree_and_strong_test_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            copy_existing_project_fixture(root, include_runtime_state=True)
            init_empty_git(root)
            entries, note = MODULE.working_tree_paths(root, root, None)
            events, error = MODULE.collect_events(root, 12)
            rendered = MODULE.render(root, MODULE.merge_and_rank(events, 12), error)

        self.assertIsNone(note)
        self.assertTrue(any(item["path"] == "tests/test_cli.py" for item in entries))
        self.assertTrue(any(item["path"] == "reports/test-report.md" for item in entries))
        self.assertTrue(any(item["source"] == "summary:reports/test-report.md" for item in events))
        self.assertTrue(all(item["evidence_level"] == "strong" for item in events))
        self.assertNotIn("Old published story", rendered)
        self.assertIn("[1] 选择一个候选", rendered)
        self.assertIn("summary:reports/test-report.md", rendered)

    def test_no_commit_readme_and_source_do_not_claim_recent_event(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("This project exports records.", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("def export(): return []", encoding="utf-8")
            init_empty_git(root)
            events, error = MODULE.collect_events(root, 12)
            rendered = MODULE.render(root, events, error)

        self.assertEqual([], events)
        self.assertIn("未发现可验证的近期开发证据", error or "")
        self.assertIn("[1] 提供当前开发摘要或明确近期 artifact", rendered)
        self.assertNotIn("README", rendered)

    def test_no_commit_old_vibesocial_history_is_not_new_event(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / ".vibesocial" / "social-commits"
            state.mkdir(parents=True)
            (state / "sc-0001.json").write_text(json.dumps({
                "id": "sc-0001",
                "status": "PUBLISHED",
                "title": "Old published story",
                "publish": {"platform": "weibo", "published_at": "2025-01-01"},
            }), encoding="utf-8")
            init_empty_git(root)
            events, error = MODULE.collect_events(root, 12)

        self.assertEqual([], events)
        self.assertIn("未发现可验证的近期开发证据", error or "")
        self.assertNotIn("Old published story", error or "")

    def test_supporting_artifact_does_not_use_mtime_as_recent_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs"
            docs.mkdir()
            note = docs / "dev-notes.md"
            note.write_text("# Export behavior\n\nThe tool exports selected records.", encoding="utf-8")
            init_empty_git(root)
            events, error = MODULE.collect_events(root, 12)

        self.assertEqual([], events)
        self.assertIn("当前能验证功能存在，但无法证明这是近期开发变化", error or "")

    def test_no_commit_current_user_summary_is_last_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_empty_git(root)
            events, error = MODULE.collect_events(
                root,
                12,
                "2026-08-17: fixed the CLI export result and passed the validation test.",
            )

        self.assertIn("Git 历史为空或不可用", error or "")
        self.assertEqual(["user:current-summary"], [item["source"] for item in events])
        self.assertEqual("strong", events[0]["evidence_level"])


if __name__ == "__main__":
    unittest.main()
