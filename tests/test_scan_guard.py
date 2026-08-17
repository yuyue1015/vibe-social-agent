import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts"

sys.path.insert(0, str(SCRIPT_ROOT))
import scan_guard  # noqa: E402


class ScanGuardTests(unittest.TestCase):
    def test_parent_git_root_requires_scope_choice(self):
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as git_dir:
            project = Path(project_dir)
            parent = Path(git_dir)
            with patch.object(scan_guard, "git_root_for", return_value=parent):
                result = scan_guard.build_result(project, None, False)
        self.assertEqual("scope_required", result["status"])
        self.assertEqual(["[1] 只分析当前项目目录（默认）", "[2] 分析整个工作区", "[3] 取消"], result["options"])

    def test_project_scope_keeps_scan_root_at_selected_directory(self):
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as git_dir:
            project = Path(project_dir)
            (project / "README.md").write_text("summary", encoding="utf-8")
            parent = Path(git_dir)
            with patch.object(scan_guard, "git_root_for", return_value=parent), \
                    patch.object(scan_guard, "collect_git_metrics", return_value=scan_guard.GitMetrics(str(parent), 1, 2, "project")):
                result = scan_guard.build_result(project, "project", False)
        self.assertEqual("project", result["scope"])
        self.assertEqual(str(project), result["scan_root"])
        self.assertEqual(1, result["tree"]["file_count"])
        self.assertEqual(1, result["tree"]["document_count"])

    def test_large_estimate_requires_confirmation(self):
        tree = scan_guard.TreeMetrics(file_count=10000, document_count=1000)
        git = scan_guard.GitMetrics(root=None, commit_count=0, file_count=10000, scope=None)
        estimate = scan_guard.estimate_tokens(tree, git)
        self.assertGreater(estimate.high, 100_000)


if __name__ == "__main__":
    unittest.main()
