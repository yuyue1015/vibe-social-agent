import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / ".agents" / "skills" / "weibo-publish" / "scripts" / "weibo_publish.py"
SPEC = importlib.util.spec_from_file_location("weibo_publish_confirm", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class WeiboPublishConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.commit_path = self.root / ".vibesocial" / "social-commits" / "sc-0001.json"
        self.commit_path.parent.mkdir(parents=True)
        self.commit = {
            "schema_version": 1,
            "id": "sc-0001",
            "status": "APPROVED",
            "final_text": "一条完整的微博正文。",
            "tags": ["微博VibeLab", "VibeCoding"],
            "approved_at": "2026-08-15T00:00:00+00:00",
            "events": [],
        }
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        self._last_status = None

    def tearDown(self):
        self.temp.cleanup()

    def args(self, *, input_fn=None):
        return MODULE.argparse.Namespace(
            root=str(self.root), commit="sc-0001", cli="fake-cli", confirm_publish=True,
            input_fn=input_fn if input_fn is not None else (lambda _prompt="": "1"), output_fn=lambda _text: None,
        )

    def reconcile_args(self, weibo_id=None):
        return MODULE.argparse.Namespace(
            root=str(self.root), commit="sc-0001", cli="fake-cli", weibo_id=weibo_id,
        )

    def write_publish_state(self, status, **updates):
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        publish = {
            "status": status,
            "attempt_id": "pub-sc-0001-test",
            "social_commit_id": "sc-0001",
            "version": record.get("version", 1),
            "text_hash": MODULE.text_hash(record["final_text"]),
            "phase": "remote_write",
            "started_at": "2026-08-16T00:00:00+00:00",
            "remote_id": None,
            "tags": [],
            "pic_ids": [],
        }
        publish.update(updates)
        record["publish"] = publish
        self.commit_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def fake_cli(self, *, publish_result=None, schema=None):
        schema = schema or {"command": {"flags": [
            {"name": "status", "description": "发布微博正文", "required": True, "type": "string"},
            {"name": "mblog_statement", "description": "AI 内容声明", "required": True, "type": "int"},
        ]}}

        def run(_base, args, timeout=45):
            if args == ["doctor"]:
                return CompletedProcess([], 0, "✓ 登录账号\n✓ 完成开发者认证\n✓ 开通服务\n", "")
            if args == ["commands", "list", "--available"]:
                return CompletedProcess([], 0, "  statuses update             发布一条微博信息\n", "")
            if args == ["commands", "show", "statuses", "update"]:
                return CompletedProcess([], 0, json.dumps(schema, ensure_ascii=False), "")
            if args == ["commands", "show", "statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "ids", "description": "微博ID"},
                    {"name": "isGetLongText", "description": "返回全文"},
                ]}}, ensure_ascii=False), "")
            if args[:2] in (["statuses", "update"], ["statuses", "upload_url_text"]):
                self._last_status = args[args.index("--status") + 1]
                return publish_result or CompletedProcess([], 0, json.dumps({"id": "987654321"}), "")
            if args[:2] == ["statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"statuses": [
                    {"id": "987654321", "is_long_text": False, "text": self._last_status}
                ]}, ensure_ascii=False), "")
            return publish_result or CompletedProcess([], 0, json.dumps({"id": "987654321"}), "")

        return run

    def test_only_approved_commit_enters_publish_flow(self):
        self.commit["status"] = "DRAFT"
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        run_cli.assert_not_called()

    def test_without_y_no_cli_is_called(self):
        responses = iter(["3", "4"])
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishCancelled):
                MODULE.publish(self.args(input_fn=lambda _prompt="": next(responses)))
        run_cli.assert_not_called()

    def test_status_contains_complete_title_body_and_tags(self):
        self.commit["final_text"] = "标题\n" + ("正文500字。" * 50) + "\n标签"
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        calls = []

        def run(base, args, timeout=45):
            calls.append(args)
            if args == ["commands", "show", "statuses", "update"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "status"}, {"name": "mblog_statement"}, {"name": "is_longtext"},
                ]}}, ensure_ascii=False), "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        post = next(call for call in calls if call[:2] == ["statuses", "update"])
        sent = post[post.index("--status") + 1]
        self.assertIn("标题", sent)
        self.assertIn("正文500字", sent)
        self.assertIn("标签", sent)
        self.assertIn("#微博VibeLab#", sent)
        self.assertIn("#VibeCoding#", sent)
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual(MODULE.text_hash(sent), record["publish"]["text_hash"])

    def test_p_selects_existing_image_and_returns_to_preview(self):
        image = self.root / "preview.png"
        image.write_bytes(b"image")
        responses = iter(["2", str(image), "1"])
        selected = MODULE.confirm_preview(
            self.commit, [], input_fn=lambda _prompt="": next(responses), output_fn=lambda _text: None
        )
        self.assertEqual([image.resolve()], selected)

    def test_return_to_modify_collects_feedback_without_cli(self):
        responses = iter(["3", "把第二段写得更具体"])
        outputs = []
        prompts = []
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishRevisionRequested) as raised:
                MODULE.confirm_preview(
                    self.commit,
                    [],
                    input_fn=lambda prompt="": (prompts.append(prompt) or next(responses)),
                    output_fn=outputs.append,
                )
        self.assertEqual("把第二段写得更具体", raised.exception.feedback)
        prompt = "\n".join([*prompts, *outputs])
        self.assertIn("[1] 确认发布（Publish）", prompt)
        self.assertIn("[2] 添加/更换图片", prompt)
        self.assertIn("[3] 返回修改 + 输入修改内容", prompt)
        self.assertIn("[4] 取消", prompt)
        self.assertNotIn("[Y]", prompt)
        self.assertNotIn("[P]", prompt)
        self.assertNotIn("[N]", prompt)
        run_cli.assert_not_called()

    def test_preview_contains_final_text_and_tags(self):
        preview = MODULE.render_preview(self.commit, [])
        self.assertIn("一条完整的微博正文。", preview)
        self.assertIn("#微博VibeLab# #VibeCoding#", preview)
        self.assertIn("- 暂无图片", preview)

    def test_transport_status_flattens_paragraph_breaks_without_changing_commit_text(self):
        original = "标题\n第一段\r\n第二段"
        self.assertEqual("标题 第一段 第二段", MODULE.transport_status(original))
        self.assertEqual(original, MODULE.transport_status(original, preserve_newlines=True))
        self.assertEqual(original, "标题\n第一段\r\n第二段")

    def test_publish_command_is_not_hardcoded(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('(\"statuses\", \"upload\")', source)

    def test_commands_list_available_is_called(self):
        with patch.object(MODULE, "run_cli", return_value=CompletedProcess(
            [], 0, "  statuses update             发布一条微博信息\n", ""
        )) as run_cli:
            catalog = MODULE.list_available(["fake-cli"])
        self.assertEqual("statuses", catalog[0]["group"])
        run_cli.assert_called_once_with(["fake-cli"], ["commands", "list", "--available"])

    def test_human_readable_schema_is_parsed(self):
        schema = MODULE.parse_schema_output(
            """Usage:\n  weibo-cli statuses update [flags]\n\nFlags:\n  -h, --help                     help\n      --status string            发布微博正文\n      --mblog_statement int       AI 内容声明\n      --is_longtext int           长微博\n""",
            "statuses update",
        )
        names = {flag["name"] for flag in schema["flags"]}
        self.assertEqual({"help", "status", "mblog_statement", "is_longtext"}, names)

    def test_unclear_schema_does_not_publish(self):
        schema_without_ai = {"command": {"flags": [
            {"name": "status", "description": "发布微博正文", "required": True, "type": "string"},
        ]}}
        calls = []

        def fake_run(base, args, timeout=45):
            calls.append(args)
            return self.fake_cli(schema=schema_without_ai)(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "run_cli", side_effect=fake_run):
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        self.assertFalse(any(call[:2] == ["statuses", "update"] for call in calls))
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", record["status"])

    def test_success_changes_state_and_writes_published_log(self):
        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=self.fake_cli()):
            result = MODULE.publish(self.args())
        self.assertEqual("987654321", result["weibo_id"])
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("PUBLISHED", record["status"])
        log_lines = (self.root / ".vibesocial" / "published-log.jsonl").read_text(encoding="utf-8").splitlines()
        log = json.loads(log_lines[-1])
        self.assertEqual("sc-0001", log["social_commit_id"])
        self.assertEqual([], log["images"])
        self.assertEqual([], log["remote"]["pic_ids"])
        self.assertTrue(log["text_hash"])
        self.assertEqual("PUBLISHED", record["publish"]["status"])

    def test_published_commit_cannot_be_published_again(self):
        self.write_publish_state("PUBLISHED", remote_id="987654321")
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        record["status"] = "PUBLISHED"
        self.commit_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError) as raised:
                MODULE.publish(self.args())
        self.assertEqual("PUBLISHED", raised.exception.publish_status)
        run_cli.assert_not_called()

    def test_legacy_top_level_published_commit_cannot_be_published_again(self):
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        record["status"] = "PUBLISHED"
        self.commit_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError) as raised:
                MODULE.publish(self.args())
        self.assertEqual("PUBLISHED", raised.exception.publish_status)
        run_cli.assert_not_called()

    def test_legacy_approved_publish_error_requires_reconcile(self):
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        record["publish_error"] = {"platform": "weibo", "message": "旧失败记录"}
        self.commit_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError) as raised:
                MODULE.publish(self.args())
        self.assertEqual("UNKNOWN_REQUIRES_RECONCILIATION", raised.exception.publish_status)
        run_cli.assert_not_called()

    def test_publishing_commit_cannot_be_retried_directly(self):
        self.write_publish_state("PUBLISHING")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError) as raised:
                MODULE.publish(self.args())
        self.assertEqual("PUBLISHING", raised.exception.publish_status)
        run_cli.assert_not_called()

    def test_unknown_commit_cannot_be_retried_directly(self):
        self.write_publish_state("UNKNOWN_REQUIRES_RECONCILIATION", remote_id="987654321")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError) as raised:
                MODULE.publish(self.args())
        self.assertEqual("UNKNOWN_REQUIRES_RECONCILIATION", raised.exception.publish_status)
        run_cli.assert_not_called()

    def test_failed_retryable_commit_can_retry(self):
        self.write_publish_state("FAILED_RETRYABLE", phase="preflight")
        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=self.fake_cli()):
            result = MODULE.publish(self.args())
        self.assertEqual("PUBLISHED", result["current_state"])

    def test_remote_id_is_persisted_before_readback(self):
        def run(base, args, timeout=45):
            if args[:2] == ["statuses", "show_batch/biz"]:
                record = json.loads(self.commit_path.read_text(encoding="utf-8"))
                self.assertEqual("987654321", record["publish"]["remote_id"])
                expected = MODULE.transport_status(
                    MODULE.compose_status(record, record["publish"]["tags"]),
                    preserve_newlines=True,
                )
                return CompletedProcess([], 0, json.dumps({"statuses": [{
                    "id": "987654321", "is_long_text": False, "text": expected
                }]}, ensure_ascii=False), "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("987654321", record["publish"]["weibo_id"])

    def test_success_without_remote_id_enters_unknown(self):
        failed_response = CompletedProcess([], 0, json.dumps({"ok": True}), "")
        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=self.fake_cli(publish_result=failed_response)):
            with self.assertRaises(MODULE.PublishError) as raised:
                MODULE.publish(self.args())
        self.assertEqual("UNKNOWN_REQUIRES_RECONCILIATION", raised.exception.publish_status)
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("UNKNOWN_REQUIRES_RECONCILIATION", record["publish"]["status"])

    def test_published_commit_with_log_failure_cannot_be_republished(self):
        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=self.fake_cli()), patch.object(MODULE, "append_published_log", side_effect=OSError("disk full")):
            result = MODULE.publish(self.args())
        self.assertEqual("PUBLISHED", result["current_state"])
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        run_cli.assert_not_called()
        repaired = MODULE.reconcile(self.reconcile_args())
        self.assertEqual("PUBLISHED", repaired["current_state"])
        self.assertTrue((self.root / ".vibesocial" / "published-log.jsonl").is_file())

    def test_published_log_is_idempotent(self):
        first = MODULE.append_published_log(self.root, "sc-0001", "正文", [], [], [], "987654321", [["weibo-cli"]], attempt_id="a1", version=1)
        second = MODULE.append_published_log(self.root, "sc-0001", "正文", [], [], [], "987654321", [["weibo-cli"]], attempt_id="a2", version=1)
        self.assertTrue(first)
        self.assertFalse(second)
        lines = (self.root / ".vibesocial" / "published-log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(1, len(lines))

    def test_reconcile_success_marks_published_without_external_write(self):
        self.write_publish_state("UNKNOWN_REQUIRES_RECONCILIATION", remote_id="987654321", tags=[])
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        expected = MODULE.transport_status(MODULE.compose_status(record, []), preserve_newlines=True)
        self._last_status = expected
        calls = []

        def run(base, args, timeout=45):
            calls.append(args)
            if args == ["commands", "list", "--available"]:
                return CompletedProcess([], 0, "  statuses show_batch/biz    查询微博\n", "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            result = MODULE.reconcile(self.reconcile_args())
        self.assertEqual("PUBLISHED", result["current_state"])
        updated = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("PUBLISHED", updated["status"])
        self.assertEqual("PUBLISHED", updated["publish"]["status"])
        self.assertFalse(any(call[:2] in (["statuses", "update"], ["statuses", "upload_pic"], ["statuses", "upload_url_text"]) for call in calls))

    def test_reconcile_published_reads_new_publish_metadata(self):
        self.write_publish_state(
            "PUBLISHED",
            remote_id="987654321",
            weibo_id="987654321",
            images=[{"name": "demo.png", "source": "local_image", "extension": ".png"}],
            command={"tool": "weibo-cli", "action": "statuses.upload_url_text"},
        )
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        record["status"] = "PUBLISHED"
        self.commit_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

        with patch.object(MODULE, "run_cli") as run_cli:
            result = MODULE.reconcile(self.reconcile_args())

        self.assertEqual("PUBLISHED", result["current_state"])
        run_cli.assert_not_called()
        log = json.loads((self.root / ".vibesocial" / "published-log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual([{"name": "demo.png", "source": "local_image", "extension": ".png"}], log["images"])
        self.assertEqual({"tool": "weibo-cli", "action": "statuses.upload_url_text"}, log["command"])

    def test_reconcile_published_reads_legacy_publish_metadata(self):
        self.write_publish_state(
            "PUBLISHED",
            remote_id="987654321",
            weibo_id="987654321",
            image_paths=[r"C:\Users\alice\Pictures\legacy.jpg"],
            command_used=[["weibo-cli", "statuses", "update", "--status", "<value>"]],
        )
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        record["status"] = "PUBLISHED"
        self.commit_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

        result = MODULE.reconcile(self.reconcile_args())

        self.assertEqual("PUBLISHED", result["current_state"])
        log = json.loads((self.root / ".vibesocial" / "published-log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual([{"name": "legacy.jpg", "source": "local_image", "extension": ".jpg"}], log["images"])
        self.assertEqual({"tool": "weibo-cli", "action": "statuses.update"}, log["command"])
        self.assertNotIn("C:\\Users\\alice", json.dumps(log, ensure_ascii=False))

    def test_reconcile_failure_preserves_unknown(self):
        self.write_publish_state("UNKNOWN_REQUIRES_RECONCILIATION", remote_id="987654321", tags=[])
        self._last_status = "不是这篇微博"
        def run(base, args, timeout=45):
            if args == ["commands", "list", "--available"]:
                return CompletedProcess([], 0, "  statuses show_batch/biz    查询微博\n", "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run), patch.object(MODULE.time, "sleep"):
            with self.assertRaises(MODULE.PublishError):
                MODULE.reconcile(self.reconcile_args())
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", record["status"])
        self.assertEqual("UNKNOWN_REQUIRES_RECONCILIATION", record["publish"]["status"])

    def test_reconcile_without_remote_id_requires_user_id(self):
        self.write_publish_state("UNKNOWN_REQUIRES_RECONCILIATION", tags=[])
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError):
                MODULE.reconcile(self.reconcile_args())
        run_cli.assert_not_called()

    def test_versioned_social_commit_can_publish_independently(self):
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        record["version"] = 2
        record["revision_of"] = "sc-0001"
        self.commit_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=self.fake_cli()):
            MODULE.publish(self.args())
        updated = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual(2, updated["publish"]["version"])

    def test_failed_publish_keeps_approved(self):
        failed = CompletedProcess([], 1, "", "服务失败")
        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=self.fake_cli(publish_result=failed)):
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", record["status"])
        self.assertIn("publish_error", record)
        self.assertEqual("UNKNOWN_REQUIRES_RECONCILIATION", record["publish"]["status"])

    def test_truncated_readback_keeps_approved_and_does_not_log_success(self):
        def run(base, args, timeout=45):
            if args[:2] == ["statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"statuses": [
                    {"id": "987654321", "is_long_text": False, "text": "只有标题"}
                ]}, ensure_ascii=False), "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", record["status"])
        self.assertIn("publish_error", record)
        self.assertEqual("UNKNOWN_REQUIRES_RECONCILIATION", record["publish"]["status"])
        self.assertFalse((self.root / ".vibesocial" / "published-log.jsonl").exists())

    def test_readback_retries_for_eventual_consistency(self):
        read_count = 0

        def run(base, args, timeout=45):
            nonlocal read_count
            if args[:2] == ["statuses", "show_batch/biz"]:
                read_count += 1
                text = None if read_count == 1 else self._last_status
                statuses = [] if text is None else [{"id": "987654321", "is_long_text": False, "text": text}]
                return CompletedProcess([], 0, json.dumps({"statuses": statuses}, ensure_ascii=False), "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run), patch.object(MODULE.time, "sleep") as sleep:
            MODULE.publish(self.args())
        self.assertEqual(2, read_count)
        sleep.assert_called_once_with(2.0)

    def test_readback_accepts_live_long_text_content_field(self):
        record = {
            "id": "987654321",
            "is_long_text": True,
            "long_text": {"long_text_content": "完整微博正文"},
        }
        self.assertEqual("完整微博正文", MODULE.readback_text(record))

    def test_text_command_uses_confirmed_mblog_statement(self):
        calls = []

        def run(base, args, timeout=45):
            calls.append(args)
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        post = next(call for call in calls if call[:2] == ["statuses", "update"])
        self.assertEqual(["statuses", "update", "--status", "一条完整的微博正文。\n#微博VibeLab# #VibeCoding#", "--mblog_statement", "1"], post)

    def test_text_publish_preserves_paragraph_breaks(self):
        self.commit["final_text"] = "标题\n第一段\n第二段"
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        calls = []

        def run(base, args, timeout=45):
            calls.append(args)
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        post = next(call for call in calls if call[:2] == ["statuses", "update"])
        self.assertEqual("标题\n第一段\n第二段\n#微博VibeLab# #VibeCoding#", post[post.index("--status") + 1])

    def test_long_text_adds_is_longtext(self):
        self.commit["final_text"] = "字" * 141
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        calls = []

        def run(base, args, timeout=45):
            calls.append(args)
            schema = {"command": {"flags": [
                {"name": "status", "description": "发布微博正文", "required": True, "type": "string"},
                {"name": "mblog_statement", "description": "AI 内容声明", "required": True, "type": "int"},
                {"name": "is_longtext", "description": "长微博", "required": True, "type": "int"},
            ]}}
            if args == ["commands", "show", "statuses", "update"]:
                return CompletedProcess([], 0, json.dumps(schema, ensure_ascii=False), "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        post = next(call for call in calls if call[:2] == ["statuses", "update"])
        self.assertEqual("1", post[-1])
        self.assertEqual("--is_longtext", post[-2])

    def test_one_image_uploads_first_then_posts_with_pic_id(self):
        image = self.root / "one.png"
        image.write_bytes(b"image")
        self.commit["images"] = [str(image)]
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        calls = []

        def run(base, args, timeout=45):
            calls.append(args)
            if args == ["commands", "list", "--available"]:
                return CompletedProcess([], 0, "  statuses upload_pic         上传图片，返回图片id\n  statuses upload_url_text    发布一条带单/多图的微博\n", "")
            if args == ["commands", "show", "statuses", "upload_pic"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [{"name": "pic", "description": "本地图片路径"}]}}, ensure_ascii=False), "")
            if args == ["commands", "show", "statuses", "upload_url_text"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "pic_id", "description": "图片ID"},
                    {"name": "status", "description": "发布微博正文"},
                    {"name": "mblog_statement", "description": "AI 内容声明"},
                ]}}, ensure_ascii=False), "")
            if args[:2] == ["statuses", "upload_pic"]:
                return CompletedProcess([], 0, json.dumps({"pic_id": "pic-1"}), "")
            if args[:2] == ["statuses", "upload_url_text"]:
                self._last_status = args[args.index("--status") + 1]
                return CompletedProcess([], 0, json.dumps({"id": "weibo-1"}), "")
            if args[:2] == ["statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"statuses": [
                    {"id": "weibo-1", "is_long_text": False, "text": self._last_status}
                ]}, ensure_ascii=False), "")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[image.resolve()]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        upload_index = next(index for index, call in enumerate(calls) if call[:2] == ["statuses", "upload_pic"])
        post_index = next(index for index, call in enumerate(calls) if call[:2] == ["statuses", "upload_url_text"])
        self.assertLess(upload_index, post_index)
        post = calls[post_index]
        self.assertEqual("pic-1", post[post.index("--pic_id") + 1])
        self.assertNotIn(["statuses", "upload"], [call[:2] for call in calls])

    def test_multiple_images_upload_each_and_join_pic_ids(self):
        images = []
        for index in range(3):
            image = self.root / f"{index}.jpg"
            image.write_bytes(b"image")
            images.append(image)
        self.commit["images"] = [str(image) for image in images]
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        calls = []
        upload_count = 0

        def run(base, args, timeout=45):
            nonlocal upload_count
            calls.append(args)
            if args == ["commands", "list", "--available"]:
                return CompletedProcess([], 0, "  statuses upload_pic         上传图片，返回图片id\n  statuses upload_url_text    发布一条带单/多图的微博\n", "")
            if args == ["commands", "show", "statuses", "upload_pic"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [{"name": "pic", "description": "本地图片路径"}]}}, ensure_ascii=False), "")
            if args == ["commands", "show", "statuses", "upload_url_text"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "pic_id", "description": "图片ID"}, {"name": "status", "description": "发布微博正文"}, {"name": "mblog_statement", "description": "AI 内容声明"},
                ]}}, ensure_ascii=False), "")
            if args == ["commands", "show", "statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "ids"}, {"name": "isGetLongText"},
                ]}}, ensure_ascii=False), "")
            if args[:2] == ["statuses", "upload_pic"]:
                pic_id = f"pic-{upload_count}"
                upload_count += 1
                return CompletedProcess([], 0, json.dumps({"pic_id": pic_id}), "")
            if args[:2] == ["statuses", "upload_url_text"]:
                self._last_status = args[args.index("--status") + 1]
                return CompletedProcess([], 0, json.dumps({"id": "weibo-1"}), "")
            if args[:2] == ["statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"statuses": [
                    {"id": "weibo-1", "is_long_text": False, "text": self._last_status}
                ]}, ensure_ascii=False), "")
            return CompletedProcess([], 0, json.dumps({"id": "weibo-1"}), "")

        with patch.object(MODULE, "confirm_preview", return_value=[image.resolve() for image in images]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        post = next(call for call in calls if call[:2] == ["statuses", "upload_url_text"])
        self.assertEqual("pic-0,pic-1,pic-2", post[post.index("--pic_id") + 1])

    def test_more_than_nine_images_is_rejected(self):
        paths = []
        for index in range(10):
            image = self.root / f"{index}.png"
            image.write_bytes(b"image")
            paths.append(str(image))
        self.commit["images"] = paths
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        run_cli.assert_not_called()

    def test_unsupported_image_format_is_rejected(self):
        image = self.root / "preview.webp"
        image.write_bytes(b"image")
        self.commit["images"] = [str(image)]
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        with patch.object(MODULE, "run_cli") as run_cli:
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        run_cli.assert_not_called()

    def test_failed_image_upload_stops_before_final_post(self):
        image = self.root / "one.gif"
        image.write_bytes(b"image")
        self.commit["images"] = [str(image)]
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")
        calls = []

        def run(base, args, timeout=45):
            calls.append(args)
            if args[:2] == ["statuses", "upload_pic"]:
                return CompletedProcess([], 1, "", "upload failed")
            return self.fake_cli()(base, args, timeout)

        with patch.object(MODULE, "confirm_preview", return_value=[image.resolve()]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            with self.assertRaises(MODULE.PublishError):
                MODULE.publish(self.args())
        self.assertFalse(any(call[:2] == ["statuses", "upload_url_text"] for call in calls))
        record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual("APPROVED", record["status"])

    def test_published_log_contains_safe_image_metadata_and_pic_ids(self):
        image = self.root / "one.jpeg"
        image.write_bytes(b"image")
        self.commit["images"] = [str(image)]
        self.commit_path.write_text(json.dumps(self.commit, ensure_ascii=False), encoding="utf-8")

        def run(base, args, timeout=45):
            if args == ["doctor"]:
                return CompletedProcess([], 0, "✓ 登录账号", "")
            if args == ["commands", "list", "--available"]:
                return CompletedProcess([], 0, "  statuses upload_pic         上传图片，返回图片id\n  statuses upload_url_text    发布一条带单/多图的微博\n", "")
            if args == ["commands", "show", "statuses", "upload_pic"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [{"name": "pic"}]}}, ensure_ascii=False), "")
            if args == ["commands", "show", "statuses", "upload_url_text"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "pic_id"}, {"name": "status"}, {"name": "mblog_statement"},
                ]}}, ensure_ascii=False), "")
            if args == ["commands", "show", "statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"command": {"flags": [
                    {"name": "ids"}, {"name": "isGetLongText"},
                ]}}, ensure_ascii=False), "")
            if args[:2] == ["statuses", "upload_pic"]:
                return CompletedProcess([], 0, json.dumps({"pic_id": "pic-1"}), "")
            if args[:2] == ["statuses", "upload_url_text"]:
                self._last_status = args[args.index("--status") + 1]
                return CompletedProcess([], 0, json.dumps({"id": "weibo-1"}), "")
            if args[:2] == ["statuses", "show_batch/biz"]:
                return CompletedProcess([], 0, json.dumps({"statuses": [
                    {"id": "weibo-1", "is_long_text": False, "text": self._last_status}
                ]}, ensure_ascii=False), "")
            return CompletedProcess([], 0, json.dumps({"id": "weibo-1"}), "")

        with patch.object(MODULE, "confirm_preview", return_value=[image.resolve()]), patch.object(MODULE, "resolve_cli", return_value=["fake-cli"]), patch.object(MODULE, "run_cli", side_effect=run):
            MODULE.publish(self.args())
        log = json.loads((self.root / ".vibesocial" / "published-log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual([{"name": "one.jpeg", "source": "local_image", "extension": ".jpeg"}], log["images"])
        self.assertEqual(["pic-1"], log["remote"]["pic_ids"])
        self.assertNotIn("image_paths", log)
        self.assertNotIn("command_used", log)
        commit_record = json.loads(self.commit_path.read_text(encoding="utf-8"))
        self.assertEqual(log["images"], commit_record["publish"]["images"])
        self.assertNotIn("image_paths", commit_record["publish"])
        self.assertIsInstance(commit_record["publish"]["command"], dict)
        self.assertIn("published_at", log)


if __name__ == "__main__":
    unittest.main()
