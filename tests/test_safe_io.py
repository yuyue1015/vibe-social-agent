import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_ROOT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
import safe_io  # noqa: E402


class SafeIoTests(unittest.TestCase):
    def test_id_validators_reject_traversal_absolute_and_long_values(self):
        for value in ("../xxx", r"..\xxx", r"C:\secret.json", r"\\server\share\x", "sc-0001:bad", "sc-" + "1" * 200):
            with self.subTest(value=value):
                with self.assertRaises(safe_io.SafetyError):
                    safe_io.validate_social_commit_id(value)
        with self.assertRaises(safe_io.SafetyError):
            safe_io.validate_social_pr_id(r"..spr-0001")
        with self.assertRaises(safe_io.SafetyError):
            safe_io.validate_attempt_id("pub-sc-0001-not-an-attempt")

    def test_valid_ids_are_accepted(self):
        self.assertEqual("sc-0001", safe_io.validate_social_commit_id("sc-0001"))
        self.assertEqual("spr-0001", safe_io.validate_social_pr_id("spr-0001"))
        self.assertEqual("pub-sc-0001-0123456789ab", safe_io.validate_attempt_id("pub-sc-0001-0123456789ab"))

    def test_safe_join_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(safe_io.SafetyError):
                safe_io.safe_join(root, "../outside.txt")
            self.assertTrue(safe_io.is_within_root(root / "child", root))

    def test_legacy_record_lookup_is_bounded_and_uses_internal_id(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            record = directory / "legacy-file.json"
            record.write_text('{"id": "legacy-1", "status": "SOCIAL_COMMIT"}', encoding="utf-8")
            path = safe_io.safe_state_record_path(directory, "legacy-1", safe_io.validate_social_commit_id)
            self.assertEqual(record, path)
            with self.assertRaises(safe_io.SafetyError):
                safe_io.safe_state_record_path(directory, "../legacy-1", safe_io.validate_social_commit_id)

    def test_error_redaction_does_not_keep_paths_or_tokens(self):
        result = safe_io.safe_error(
            "TEST",
            r"failed at C:\Users\alice\private.txt with token=sk-abcdefghijklmnopqrstuvwxyz",
        )
        self.assertEqual("TEST", result["error_code"])
        self.assertNotIn("alice", result["error_message_safe"])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", result["error_message_safe"])

    def test_bounded_subprocess_limits_output(self):
        result = safe_io.bounded_subprocess(
            [sys.executable, "-c", "print('x' * 10000)"],
            timeout=10,
            max_output_bytes=128,
        )
        self.assertEqual(0, result.returncode)
        self.assertTrue(result.output_truncated)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 128)

    def test_bounded_subprocess_timeout(self):
        result = safe_io.bounded_subprocess(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=1,
            max_output_bytes=128,
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(124, result.returncode)

    def test_symlink_outside_root_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            outside = Path(temp) / "outside"
            root.mkdir()
            outside.mkdir()
            target = root / "link"
            try:
                target.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            with self.assertRaises(safe_io.SafetyError):
                safe_io.safe_join(root, "link/file.txt")


if __name__ == "__main__":
    unittest.main()
