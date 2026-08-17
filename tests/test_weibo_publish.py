import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "weibo-publish" / "scripts" / "weibo_publish.py"
SPEC = importlib.util.spec_from_file_location("weibo_publish", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WeiboPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.commit_path = self.root / ".vibesocial" / "social-commits" / "sc-0001.json"
        self.commit_path.parent.mkdir(parents=True)
        self.commit_path.write_text(json.dumps({
            "schema_version": 1,
            "id": "sc-0001",
            "status": "APPROVED",
            "title": "Safe post",
            "final_text": "A safe approved post.",
            "approved_at": "2026-08-15T00:00:00+00:00",
            "events": [],
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, confirm=True):
        return MODULE.argparse.Namespace(
            root=str(self.root), commit="sc-0001", cli="fake-cli", confirm_publish=confirm,
            input_fn=lambda _prompt="": "1", output_fn=lambda _text: None,
        )

    def test_failed_doctor_keeps_commit_approved(self):
        failed = CompletedProcess([], 0, "× 登录账号", "")
        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", return_value=failed):
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", record["status"])
        self.assertEqual("weibo", record["publish_error"]["platform"])
        self.assertEqual("FAILED_RETRYABLE", record["publish"]["status"])

    def test_publish_requires_explicit_guard(self):
        with self.assertRaises(MODULE.PublishError):
            MODULE.publish(self.args(confirm=False))
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", record["status"])
        self.assertNotIn("publish_error", record)

    def test_doctor_report_separates_warnings(self):
        result = CompletedProcess([], 0, "✓ 登录账号 demo\n", "")
        with patch.object(MODULE, "run_cli", return_value=result):
            report = MODULE.doctor(["fake-cli"])
        self.assertIn("微博账号：✓ 已登录", report)
        self.assertIn("CLI环境：✓ 可用", report)
        self.assertIn("开发者服务：⚠ 未检测", report)

    def test_credential_visibility_error_does_not_claim_logout(self):
        result = CompletedProcess([], 1, "auth login 已成功\n", "无法读取 Windows 用户凭据存储")
        outputs = []
        with patch.object(MODULE, "run_cli", return_value=result):
            report = MODULE.doctor(["fake-cli"], output_fn=outputs.append)
        message = "\n".join(outputs)
        self.assertIn("微博账号：⚠ 无法确认", message)
        self.assertIn("无法读取微博授权状态", message)
        self.assertIn("同一用户终端", message)
        self.assertNotIn("未登录微博账号", message)
        self.assertIn("⚠ 无法确认", report)

    def test_explicitly_not_logged_in_gets_login_entry(self):
        result = CompletedProcess([], 0, "未检测到授权", "")
        with patch.object(MODULE, "run_cli", return_value=result):
            with self.assertRaises(MODULE.PublishError) as raised:
                MODULE.doctor(["fake-cli"])
        message = str(raised.exception)
        self.assertIn("未检测到微博授权", message)
        self.assertIn("[1] 登录微博账号", message)
        self.assertIn("[2] 返回", message)

    def test_sandbox_failure_is_unknown_not_logged_out(self):
        result = CompletedProcess([], 1, "", "Access is denied while reading credential store")
        outputs = []
        with patch.object(MODULE, "run_cli", return_value=result):
            MODULE.doctor(["fake-cli"], output_fn=outputs.append)
        message = "\n".join(outputs)
        self.assertIn("微博账号：⚠ 无法确认", message)
        self.assertIn("CLI环境：⚠ 不可访问", message)
        self.assertNotIn("未检测到微博授权", message)

    def test_success_writes_published_record_from_live_schema(self):
        posted_status = None

        def fake_run(_base, args, timeout=45):
            nonlocal posted_status
            if args == ["doctor"]:
                return CompletedProcess([], 0, "✓ 登录账号\n✓ 完成开发者认证\n✓ 开通服务\n", "")
            if args[:3] == ["commands", "list", "--available"] and "--output" not in args:
                return CompletedProcess([], 0, "  statuses update    发布一条微博信息\n", "")
            if args[:3] == ["commands", "list", "--available"]:
                return CompletedProcess([], 0, json.dumps({"commands": [{"group": "statuses", "action": "update", "access": "allowed"}]}), "")
            if args[:4] == ["commands", "show", "statuses", "update"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "status", "description": "发布微博正文", "required": True, "type": "string"},
                    {"name": "mblog_statement", "description": "AI 内容声明", "required": True, "type": "int"},
                    {"name": "ai_content", "description": "AI 内容声明", "required": True, "type": "boolean"},
                ]}}), "")
            if args[:4] == ["commands", "show", "statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "ids", "description": "微博ID", "required": True, "type": "string"},
                    {"name": "isGetLongText", "description": "返回全文", "type": "int"},
                ]}}), "")
            if args[:2] == ["statuses", "update"]:
                posted_status = args[args.index("--status") + 1]
                return CompletedProcess([], 0, json.dumps({"id": "987654321"}), "")
            if args[:2] == ["statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"statuses": [
                    {"id": "987654321", "is_long_text": False, "text": posted_status}
                ]}), "")
            return CompletedProcess([], 0, json.dumps({"id": "987654321"}), "")

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=fake_run):
            result = MODULE.publish(self.args())
        self.assertEqual("987654321", result["weibo_id"])
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("PUBLISHED", record["status"])
        self.assertEqual("A safe approved post.", record["final_text"])
        self.assertEqual("2026-08-15T00:00:00+00:00", record["approved_at"])
        self.assertEqual("PUBLISHED", record["publish"]["status"])


if __name__ == "__main__":
    unittest.main()
