import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class EvalHarnessContractTests(unittest.TestCase):
    def test_core_benchmark_is_small_and_has_required_fields(self):
        cases = json.loads((ROOT / "evals" / "cases" / "core_benchmark.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 10)
        self.assertLessEqual(len(cases), 12)
        required = {
            "case_id", "raw_artifact", "expected_event_type", "expected_priority",
            "required_facts", "forbidden_claims", "expected_behavior",
        }
        self.assertTrue(all(required.issubset(case) for case in cases))

    def test_forward_testing_is_explicitly_not_claimed_as_passed(self):
        text = (ROOT / "evals" / "forward-testing.md").read_text(encoding="utf-8")
        self.assertIn("READY_FOR_FORWARD_TEST", text)
        self.assertIn("expected output", text)

    def test_existing_no_commit_forward_fixture_is_present(self):
        fixture = ROOT / "evals" / "fixtures" / "projects" / "existing-no-commit"
        self.assertTrue((fixture / "src" / "cli.py").is_file())
        self.assertTrue((fixture / "tests" / "test_cli.py").is_file())
        self.assertTrue((fixture / "reports" / "test-report.md").is_file())
        self.assertTrue((fixture / "history" / "social-commits" / "sc-0001.json").is_file())
        self.assertFalse(any(path.name == ".vibesocial" for path in fixture.rglob("*")))


if __name__ == "__main__":
    unittest.main()
