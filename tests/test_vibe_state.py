import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "vibe-social" / "scripts" / "vibe_state.py"


class VibeStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(expect, result.returncode, result.stderr or result.stdout)
        stream = result.stdout if expect == 0 else result.stderr
        return json.loads(stream)

    def init(self):
        return self.run_cli("init", "--project-name", "Fixture", "--style", "casual-weibo")

    def create_draft_pr(self, body_text="第一句原稿。第二句保留。", title_text="原始标题"):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Draft editing fixture",
            "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "draft.md"
        body.write_text(body_text, encoding="utf-8")
        return self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", title_text,
            "--direction", "Draft editing", "--body-file", str(body),
        )

    def safe_events(self):
        path = self.root / "events.json"
        path.write_text(json.dumps([{
            "type": "rule_correction",
            "summary": "Corrected diagnosis estimates",
            "problem": "Results were too optimistic",
            "change": "Recalibrated the public model",
            "user_value": "Recommendations are more realistic",
            "evidence": ["Focused tests pass"],
            "public_safe": True,
        }]), encoding="utf-8")
        return path

    def readiness_file(self, status="ready", completion="complete"):
        path = self.root / "candidate.json"
        path.write_text(json.dumps({
            "event": "已验证的测试故事",
            "publish_readiness": {
                "status": status,
                "completion": completion,
                "reason": "测试用 readiness 原因",
            },
        }), encoding="utf-8")
        return path

    def test_full_local_workflow(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Honest diagnosis results",
            "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        self.assertEqual("sc-0001", commit["id"])

        body = self.root / "draft.md"
        body.write_text("I found why the simulation always looked too optimistic.", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "The optimistic simulator",
            "--direction", "Debugging story", "--body-file", str(body),
        )
        self.assertEqual("SOCIAL_PR", pr["status"])

        revised = self.root / "revised.md"
        revised.write_text("The simulator was not lucky. Its assumptions were too optimistic.", encoding="utf-8")
        pr = self.run_cli("revise-pr", "--pr", pr["id"], "--body-file", str(revised))
        self.assertEqual(2, pr["revision"])
        self.assertEqual("DRAFT", pr["current_state"])
        self.assertEqual("PULL", pr["action"])
        self.assertNotEqual("PULL", pr["status"])

        approved = self.run_cli("approve", "--pr", pr["id"])
        self.assertEqual("APPROVED", approved["status"])
        approved_commit = json.loads((self.root / ".vibesocial" / "social-commits" / f"{commit['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", approved_commit["status"])
        self.assertEqual("The simulator was not lucky. Its assumptions were too optimistic.", approved_commit["final_text"])
        status = self.run_cli("status")
        self.assertEqual("abc123", status["state"]["last_scanned_ref"])

    def test_init_is_idempotent(self):
        self.init()
        second = self.init()
        self.assertEqual("already_initialized", second["result"])

    def test_sentence_edit_uses_fast_path_and_renders_full_draft(self):
        pr = self.create_draft_pr()
        revised = self.root / "revised.md"
        revised.write_text("第一句已修改。第二句保留。", encoding="utf-8")
        result = self.run_cli("revise-pr", "--pr", pr["id"], "--body-file", str(revised))
        self.assertEqual("DRAFT_FAST_PATH", result["edit_path"])
        self.assertFalse(result["scan_performed"])
        self.assertEqual("第一句已修改。第二句保留。", result["full_draft"]["body"])
        self.assertEqual("原始标题", result["full_draft"]["title"])
        self.assertEqual("DRAFT", result["full_draft"]["status"])
        self.assertEqual("DRAFT", result["current_state"])
        self.assertEqual("PULL", result["action"])
        self.assertIn("提交以上修改（Pull）", result["next"])

    def test_title_edit_uses_fast_path_without_rescanning(self):
        pr = self.create_draft_pr()
        result = self.run_cli("revise-pr", "--pr", pr["id"], "--title", "更短的新标题")
        self.assertEqual("DRAFT_FAST_PATH", result["edit_path"])
        self.assertFalse(result["scan_performed"])
        self.assertEqual("更短的新标题", result["full_draft"]["title"])
        self.assertEqual("第一句原稿。第二句保留。", result["full_draft"]["body"])
        self.assertEqual("PULL", result["action"])

    def test_factual_number_change_requires_evidence(self):
        pr = self.create_draft_pr("从 18 次降到 11 次。")
        revised = self.root / "factual-revised.md"
        revised.write_text("从 18 次降到 20 次。", encoding="utf-8")
        error = self.run_cli(
            "revise-pr", "--pr", pr["id"], "--body-file", str(revised), expect=2,
        )
        self.assertIn("需要重新核实证据", error["error"])
        stored = json.loads((self.root / ".vibesocial" / "social-prs" / f"{pr['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual("从 18 次降到 11 次。", stored["body"])

    def test_factual_edit_with_evidence_uses_fact_check_path(self):
        pr = self.create_draft_pr("从 18 次降到 11 次。")
        revised = self.root / "factual-revised.md"
        revised.write_text("从 18 次降到 20 次。", encoding="utf-8")
        evidence = self.root / "evidence.md"
        evidence.write_text("验证记录：新的结果为 20 次。", encoding="utf-8")
        result = self.run_cli(
            "revise-pr", "--pr", pr["id"], "--body-file", str(revised),
            "--evidence-file", str(evidence),
        )
        self.assertEqual("FACT_CHECK", result["edit_path"])
        self.assertTrue(result["evidence_checked"])
        self.assertEqual("从 18 次降到 20 次。", result["full_draft"]["body"])
        self.assertEqual("DRAFT", result["current_state"])

    def test_unsupported_factual_evidence_does_not_save_edit(self):
        pr = self.create_draft_pr("从 18 次降到 11 次。")
        revised = self.root / "factual-revised.md"
        revised.write_text("从 18 次降到 20 次。", encoding="utf-8")
        evidence = self.root / "unsupported-evidence.md"
        evidence.write_text("验证记录仍然只有旧结果。", encoding="utf-8")
        error = self.run_cli(
            "revise-pr", "--pr", pr["id"], "--body-file", str(revised),
            "--evidence-file", str(evidence), expect=2,
        )
        self.assertIn("evidence 不支持", error["error"])
        stored = json.loads((self.root / ".vibesocial" / "social-prs" / f"{pr['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual("从 18 次降到 11 次。", stored["body"])

    def test_draft_edit_auto_finds_one_draft_and_replaces_title_and_body(self):
        self.create_draft_pr(
            "开发日志 01\n\n1.0.0 已经可以完成模板导入和使用，不必先理解 .tsav 的内部结构",
            "开发日志 01",
        )
        result = self.run_cli(
            "draft-edit", "--replace-old", "开发日志 01", "--replace-new", "开发记录 01",
        )
        self.assertEqual("draft-edit", result["command"])
        self.assertEqual("spr-0001", result["id"])
        self.assertEqual(2, result["revision"])
        self.assertEqual("开发记录 01", result["full_draft"]["title"])
        self.assertIn("开发记录 01", result["full_draft"]["body"])
        self.assertEqual("DRAFT", result["full_draft"]["status"])
        self.assertEqual("DRAFT", result["current_state"])
        self.assertEqual("PULL", result["action"])
        self.assertEqual("SOCIAL_PR", result["status"])
        self.assertIn("提交以上修改（Pull）", result["next"])

        stored = json.loads((self.root / ".vibesocial" / "social-prs" / "spr-0001.json").read_text(encoding="utf-8"))
        self.assertEqual(1, len(stored["revisions"]))
        self.assertEqual(2, stored["revision"])

    def test_draft_edit_rejects_multiple_current_drafts(self):
        first = self.create_draft_pr()
        body = self.root / "second-draft.md"
        body.write_text("第二份草稿。", encoding="utf-8")
        self.run_cli(
            "create-pr", "--commit", "sc-0001", "--title", "第二份标题",
            "--direction", "Draft editing", "--body-file", str(body),
        )
        error = self.run_cli(
            "draft-edit", "--replace-old", "第一句原稿。", "--replace-new", "第一句修改。", expect=2,
        )
        self.assertIn("exactly one current DRAFT", error["error"])
        self.assertEqual("spr-0001", first["id"])

    def test_ready_candidate_can_create_social_commit(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Ready story", "--events-file", str(self.safe_events()),
            "--to-ref", "abc123", "--candidate-file", str(self.readiness_file()),
        )
        self.assertEqual("ready", commit["publish_readiness"]["status"])

    def test_hold_candidate_requires_explicit_override(self):
        self.init()
        error = self.run_cli(
            "commit", "--title", "Held story", "--events-file", str(self.safe_events()),
            "--to-ref", "abc123", "--candidate-file", str(self.readiness_file("hold", "exploring")), expect=2,
        )
        self.assertIn("override-readiness", error["error"])

    def test_skip_candidate_override_is_recorded(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Skipped story", "--events-file", str(self.safe_events()),
            "--to-ref", "abc123", "--candidate-file", str(self.readiness_file("skip", "unknown")),
            "--override-readiness",
        )
        self.assertEqual("skip", commit["publish_readiness"]["status"])
        self.assertEqual("skip", commit["publish_readiness_override"]["status"])

    def test_style_can_use_preset_or_abstract_profile(self):
        self.init()
        preset = self.run_cli("set-style", "--preset", "storytelling")
        self.assertEqual({"kind": "preset", "name": "storytelling"}, preset)

        profile = self.root / "profile.md"
        profile.write_text("Short paragraphs; open with a concrete surprise; avoid slogans.", encoding="utf-8")
        learned = self.run_cli("set-style", "--profile-file", str(profile))
        self.assertEqual("profile", learned["kind"])
        self.assertTrue((self.root / ".vibesocial" / "style-profile.md").exists())

    def test_rejects_secret_field(self):
        self.init()
        path = self.root / "unsafe.json"
        path.write_text(json.dumps([{
            "type": "fix",
            "summary": "Safe summary",
            "problem": "Safe problem",
            "change": "Safe change",
            "user_value": "Safe value",
            "public_safe": True,
            "token": "not-allowed",
        }]), encoding="utf-8")
        error = self.run_cli(
            "commit", "--title", "Unsafe", "--events-file", str(path), "--to-ref", "abc123", expect=2,
        )
        self.assertIn("unsupported fields", error["error"])

    def test_rejects_absolute_path_in_draft(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Safe", "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "unsafe-draft.md"
        body.write_text("Read the details at C:\\private\\project\\notes.txt", encoding="utf-8")
        error = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "Unsafe",
            "--direction", "Leak", "--body-file", str(body), expect=2,
        )
        self.assertIn("sensitive content", error["error"])

    def test_approved_pr_cannot_be_revised(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Safe", "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "draft.md"
        body.write_text("A safe draft.", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "Safe",
            "--direction", "Story", "--body-file", str(body),
        )
        self.run_cli("approve", "--pr", pr["id"])
        error = self.run_cli("revise-pr", "--pr", pr["id"], "--body-file", str(body), expect=2)
        self.assertIn("immutable", error["error"])

    def test_create_revision_keeps_approved_version_immutable(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Safe", "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "draft.md"
        body.write_text("The approved version stays unchanged.", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "Safe",
            "--direction", "Story", "--body-file", str(body),
        )
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(self.root / "missing-learning.json"))

        old_pr_path = self.root / ".vibesocial" / "social-prs" / f"{pr['id']}.json"
        old_commit_path = self.root / ".vibesocial" / "social-commits" / f"{commit['id']}.json"
        old_pr = json.loads(old_pr_path.read_text(encoding="utf-8"))
        old_commit = json.loads(old_commit_path.read_text(encoding="utf-8"))

        revision = self.run_cli("create-revision", "--pr", pr["id"])
        self.assertEqual("SOCIAL_PR", revision["status"])
        self.assertEqual(2, revision["version"])
        self.assertEqual(pr["id"], revision["revision_of"])
        self.assertEqual(commit["id"], revision["source_approved_commit_id"])

        revision_commit_path = self.root / ".vibesocial" / "social-commits" / f"{revision['social_commit_id']}.json"
        revision_commit = json.loads(revision_commit_path.read_text(encoding="utf-8"))
        self.assertEqual("SOCIAL_COMMIT", revision_commit["status"])
        self.assertEqual(2, revision_commit["version"])
        self.assertEqual(commit["id"], revision_commit["revision_of"])
        self.assertEqual(commit["id"], revision_commit["source_approved_commit_id"])

        self.assertEqual(old_pr, json.loads(old_pr_path.read_text(encoding="utf-8")))
        self.assertEqual(old_commit, json.loads(old_commit_path.read_text(encoding="utf-8")))

        duplicate = self.run_cli("create-revision", "--pr", pr["id"], expect=2)
        self.assertIn("unapproved revision", duplicate["error"])

        revised = self.root / "revision.md"
        revised.write_text("The second version has a deliberately different conclusion.", encoding="utf-8")
        self.run_cli("revise-pr", "--pr", revision["id"], "--body-file", str(revised))
        approved_revision = self.run_cli("approve", "--pr", revision["id"], "--learning-file", str(self.root / "missing-learning.json"))
        self.assertEqual("APPROVED", approved_revision["status"])
        self.assertEqual(old_pr, json.loads(old_pr_path.read_text(encoding="utf-8")))
        self.assertEqual(old_commit, json.loads(old_commit_path.read_text(encoding="utf-8")))

    def test_legacy_approved_records_default_to_version_one(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Legacy", "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "draft.md"
        body.write_text("A legacy approved draft.", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "Legacy",
            "--direction", "Story", "--body-file", str(body),
        )
        self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(self.root / "missing-learning.json"))

        for relative_path in (
            f".vibesocial/social-prs/{pr['id']}.json",
            f".vibesocial/social-commits/{commit['id']}.json",
        ):
            path = self.root / relative_path
            record = json.loads(path.read_text(encoding="utf-8"))
            record.pop("version", None)
            path.write_text(json.dumps(record), encoding="utf-8")

        revision = self.run_cli("create-revision", "--pr", pr["id"])
        self.assertEqual(2, revision["version"])

    def test_empty_learning_is_a_valid_approval_result(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Safe", "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "draft.md"
        body.write_text("A safe draft.", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "Safe",
            "--direction", "Story", "--body-file", str(body),
        )
        learning = self.root / "learning.json"
        learning.write_text("[]", encoding="utf-8")
        approved = self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        self.assertEqual("APPROVED", approved["status"])
        self.assertEqual("no_new_preference", approved["learning_status"])
        self.assertEqual([], approved["learning"])

    def test_learning_failure_does_not_block_approval(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Safe", "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "draft.md"
        body.write_text("A safe draft.", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "Safe",
            "--direction", "Story", "--body-file", str(body),
        )
        learning = self.root / "learning.json"
        learning.write_text("{\"invalid\": true}", encoding="utf-8")
        approved = self.run_cli("approve", "--pr", pr["id"], "--learning-file", str(learning))
        self.assertEqual("APPROVED", approved["status"])
        self.assertEqual("failed", approved["learning_status"])
        commit_record = json.loads((self.root / ".vibesocial" / "social-commits" / f"{commit['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", commit_record["status"])

    def test_manual_distribution_records_platform_without_external_call(self):
        self.init()
        commit = self.run_cli(
            "commit", "--title", "Safe", "--events-file", str(self.safe_events()), "--to-ref", "abc123",
        )
        body = self.root / "draft.md"
        body.write_text("A safe draft.", encoding="utf-8")
        pr = self.run_cli(
            "create-pr", "--commit", commit["id"], "--title", "Safe",
            "--direction", "Story", "--body-file", str(body),
        )
        self.run_cli("approve", "--pr", pr["id"])
        result = self.run_cli(
            "record-manual-distribution", "--commit", commit["id"], "--platform", "小红书",
        )
        self.assertEqual("PUBLISHED", result["status"])
        record = json.loads((self.root / ".vibesocial" / "social-commits" / f"{commit['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual("小红书", record["publish"]["platform"])
        log = json.loads((self.root / ".vibesocial" / "published-log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual("manual", log["distribution_type"])


if __name__ == "__main__":
    unittest.main()
