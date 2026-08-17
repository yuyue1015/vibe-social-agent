#!/usr/bin/env python3
"""Publish an approved VibeSocial Social Commit through the live weibo-cli schema."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VIBE_SCRIPTS = Path(__file__).resolve().parents[2] / "vibe-social" / "scripts"
if str(VIBE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VIBE_SCRIPTS))
from safe_io import (  # noqa: E402
    SafetyError,
    WEIBO_SUBPROCESS_TIMEOUT,
    bounded_subprocess,
    safe_error,
    safe_image_metadata,
    safe_join,
    safe_state_record_path,
    validate_remote_id,
    validate_scan_root,
    validate_social_commit_id,
)


class PublishError(RuntimeError):
    def __init__(self, message: str, publish_status: str | None = None) -> None:
        self.publish_status = publish_status
        super().__init__(message)


class PublishCancelled(PublishError):
    pass


class PublishRevisionRequested(PublishCancelled):
    """The user wants to revise the approved draft before publishing."""

    def __init__(self, feedback: str) -> None:
        self.feedback = feedback
        super().__init__("已记录修改意见，请回到 vibe-social 提交以上修改（Pull）")


def load_vibe_state() -> Any:
    script = Path(__file__).resolve().parents[2] / "vibe-social" / "scripts" / "vibe_state.py"
    spec = importlib.util.spec_from_file_location("vibe_state", script)
    if spec is None or spec.loader is None:
        raise PublishError("Unable to load the bundled VibeSocial state script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vibe_state = load_vibe_state()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_cli(cli: str) -> list[str]:
    if cli != "weibo-cli":
        path = shutil.which(cli) or cli
        if not Path(path).exists() and shutil.which(path) is None:
            raise PublishError(f"weibo-cli executable not found: {cli}")
    else:
        path = shutil.which("weibo-cli") or shutil.which("weibo-cli.ps1")
        if not path:
            raise PublishError("weibo-cli executable not found")

    suffix = Path(path).suffix.lower()
    if suffix == ".ps1":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise PublishError("PowerShell is required to run the installed weibo-cli.ps1")
        return [shell, "-NoProfile", "-File", path]
    return [path]


def run_cli(base: list[str], args: list[str], timeout: int = WEIBO_SUBPROCESS_TIMEOUT) -> Any:
    return bounded_subprocess([*base, *args], timeout=timeout)


def cli_error(result: subprocess.CompletedProcess[str], label: str) -> str:
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    suffix = detail[0][:240] if detail else f"exit code {result.returncode}"
    return f"{label}: {suffix}"


def read_commit(root: Path, commit_id: str) -> tuple[Path, dict[str, Any]]:
    path = safe_state_record_path(root / ".vibesocial" / "social-commits", commit_id, validate_social_commit_id)
    if not path.is_file():
        raise PublishError(f"Social Commit does not exist: {commit_id}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublishError(f"Invalid Social Commit JSON: {commit_id}") from exc
    if not isinstance(record, dict) or record.get("id") != commit_id:
        raise PublishError(f"Invalid Social Commit record: {commit_id}")
    return path, record


def content_version(commit: dict[str, Any]) -> int:
    value = commit.get("version", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 1
    return value


def get_publish_status(commit: dict[str, Any]) -> str | None:
    if commit.get("status") == "PUBLISHED":
        return PUBLISHED
    publish = commit.get("publish")
    if isinstance(publish, dict):
        value = publish.get("status")
        if value in {PUBLISHING, PUBLISHED, FAILED_RETRYABLE, UNKNOWN_REQUIRES_RECONCILIATION}:
            return value
        if value == "success":
            return UNKNOWN_REQUIRES_RECONCILIATION
    if commit.get("status") == "APPROVED":
        return UNKNOWN_REQUIRES_RECONCILIATION if commit.get("publish_error") else NONE
    return None


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_attempt_id(commit_id: str) -> str:
    return f"pub-{commit_id}-{uuid.uuid4().hex[:12]}"


def persist_publish(path: Path, commit: dict[str, Any], **updates: Any) -> None:
    publish = commit.setdefault("publish", {})
    publish.update(updates)
    vibe_state.atomic_json(path, commit)


def published_log_contains(root: Path, commit_id: str, current_hash: str, weibo_id: str | None) -> bool:
    path = safe_join(root, ".vibesocial/published-log.jsonl")
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            existing = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(existing, dict)
            and existing.get("social_commit_id") == commit_id
            and existing.get("weibo_id") == weibo_id
            and existing.get("text_hash") == current_hash
        ):
            return True
    return False


def record_failure(
    path: Path,
    commit: dict[str, Any],
    message: str,
    final_write_started: bool = False,
) -> str:
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        persisted = dict(commit)
    if get_publish_status(persisted) == PUBLISHED:
        return PUBLISHED

    working = persisted if isinstance(persisted, dict) else dict(commit)
    publish = working.get("publish") if isinstance(working.get("publish"), dict) else {}
    final_write_started = final_write_started or publish.get("phase") in REMOTE_WRITE_PHASES
    state = UNKNOWN_REQUIRES_RECONCILIATION if final_write_started else FAILED_RETRYABLE
    failure = safe_error(
        "PUBLISH_RESULT_UNKNOWN" if final_write_started else "PUBLISH_RETRYABLE_FAILED",
        "发布结果需要核对" if final_write_started else "发布前检查失败",
    )
    publish.update({
        "status": state,
        "phase": "unknown" if state == UNKNOWN_REQUIRES_RECONCILIATION else "failed",
        **failure,
        "updated_at": now(),
    })
    working["status"] = "APPROVED"
    working["publish"] = publish
    working["publish_error"] = {"platform": "weibo", **failure, "at": now()}
    vibe_state.atomic_json(path, working)
    return state


ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif"}
TEXT_COMMAND = ("statuses", "update")
PIC_UPLOAD_COMMAND = ("statuses", "upload_pic")
IMAGE_TEXT_COMMAND = ("statuses", "upload_url_text")
READBACK_COMMAND = ("statuses", "show_batch/biz")
PUBLISHING = "PUBLISHING"
PUBLISHED = "PUBLISHED"
FAILED_RETRYABLE = "FAILED_RETRYABLE"
UNKNOWN_REQUIRES_RECONCILIATION = "UNKNOWN_REQUIRES_RECONCILIATION"
NONE = "NONE"
REMOTE_WRITE_PHASES = {"remote_write", "readback", "local_finalize"}


def validate_image_paths(paths: list[Path]) -> list[Path]:
    if len(paths) > 9:
        raise PublishError("微博最多支持 9 张图片")
    invalid = [path for path in paths if path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES]
    if invalid:
        raise PublishError(f"图片格式不支持：{invalid[0].name}；仅支持 JPEG/JPG/PNG/GIF")
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise PublishError(f"图片文件不存在：{missing[0]}")
    return paths


def extract_images(commit: dict[str, Any]) -> list[Path]:
    raw = commit.get("images", [])
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        raise PublishError("Social Commit images must be a list of file paths")
    paths = [Path(item).expanduser().resolve() for item in raw]
    return validate_image_paths(paths)


def normalize_tag(value: str) -> str:
    value = value.strip().strip("#")
    return f"#{value}#" if value else ""


def format_tags(commit: dict[str, Any], text: str = "", selected: list[str] | None = None) -> str:
    if selected is not None:
        return " ".join(normalize_tag(value) for value in selected if normalize_tag(value))
    raw = commit.get("tag_suggestions") or commit.get("tags") or commit.get("hashtags") or commit.get("tag")
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return " ".join(normalize_tag(value) for value in values if normalize_tag(value))
    if isinstance(raw, str) and raw.strip():
        values = re.findall(r"#[^#\s]+#", raw)
        if values:
            return " ".join(values)
        return " ".join(normalize_tag(value) for value in raw.split() if normalize_tag(value))
    return " ".join(re.findall(r"#[^#\s]+#", text))


def compose_status(commit: dict[str, Any], selected_tags: list[str] | None = None) -> str:
    text = str(commit.get("final_text") or "").strip()
    if not text:
        return ""
    tags = format_tags(commit, text, selected_tags) if selected_tags is not None else format_tags(commit, text)
    missing_tags = [tag for tag in tags.split() if tag not in text]
    if missing_tags:
        return f"{text}\n{' '.join(missing_tags)}"
    return text


def transport_status(status: str, preserve_newlines: bool = False) -> str:
    """Keep the approved draft intact when the caller explicitly preserves breaks."""
    if preserve_newlines:
        return status.strip()
    return re.sub(r"\s*[\r\n]+\s*", " ", status).strip()


def render_preview(commit: dict[str, Any], images: list[Path], selected_tags: list[str] | None = None) -> str:
    text = transport_status(compose_status(commit, selected_tags), preserve_newlines=True)
    tags = format_tags(commit, text, selected_tags) if selected_tags is not None else format_tags(commit, text)
    tags = tags or "暂无标签"
    image_lines = [f"- {path.name}" for path in images] or ["- 暂无图片"]
    return "\n".join([
        "微博正文：",
        text,
        "",
        "Tag：",
        tags,
        "",
        "图片：",
        *image_lines,
    ])


def select_images(
    current: list[Path], input_fn: Any = None, output_fn: Any = print
) -> list[Path]:
    input_fn = input if input_fn is None else input_fn
    output_fn("请输入已有图片路径，多个路径用逗号分隔；直接回车表示无图片：")
    raw = input_fn().strip()
    if not raw:
        return []
    values = [item.strip().strip('"') for item in raw.split(",") if item.strip()]
    paths = [Path(item).expanduser().resolve() for item in values]
    return validate_image_paths(paths)


def confirm_preview(
    commit: dict[str, Any], images: list[Path], input_fn: Any = None,
    output_fn: Any = print, selected_tags: list[str] | None = None,
) -> list[Path]:
    input_fn = input if input_fn is None else input_fn
    selected = list(images)
    while True:
        output_fn("准备发布：\n\n" + render_preview(commit, selected, selected_tags))
        choice = input_fn(
            "\n确认：[1] 确认发布（Publish） [2] 添加/更换图片 [3] 返回修改 + 输入修改内容 [4] 取消："
        ).strip().upper()
        if choice == "1":
            return selected
        if choice == "2":
            selected = select_images(selected, input_fn, output_fn)
            continue
        if choice in {"3"}:
            feedback = input_fn("请输入具体修改内容：").strip()
            if feedback:
                output_fn(
                    "已记录修改意见。\n\n"
                    "请回到内容审核流程：\n"
                    "[1] 提交以上修改（Pull）\n"
                    "[2] 继续修改 + 输入修改内容\n"
                    "[3] 放弃本稿"
                )
                raise PublishRevisionRequested(feedback)
            output_fn("未输入修改内容，请直接输入具体修改意见。")
            continue
        if choice == "4":
            raise PublishCancelled("用户取消发布")
        output_fn("请输入 1、2、3 或 4。")


def normalize_image_metadata(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        source = value.get("source", "local_image")
        extension = value.get("extension", Path(name).suffix.lower())
        if not isinstance(source, str) or not source.strip():
            source = "local_image"
        if not isinstance(extension, str):
            extension = Path(name).suffix.lower()
        return {
            "name": name.replace("\x00", "")[:128] or "image",
            "source": source.replace("\x00", "")[:64],
            "extension": extension.replace("\x00", "").lower()[:16],
        }
    if isinstance(value, (str, Path)):
        return safe_image_metadata(Path(str(value)))
    return None


def image_metadata_records(values: list[Any]) -> list[dict[str, str]]:
    return [metadata for value in values if (metadata := normalize_image_metadata(value)) is not None]


def persisted_image_values(publish: dict[str, Any], commit: dict[str, Any]) -> list[Any]:
    for field in ("images", "image_paths"):
        value = publish.get(field)
        if isinstance(value, list):
            return value
    return extract_images(commit)


def normalize_command_metadata(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        tool = value.get("tool")
        action = value.get("action")
        if isinstance(tool, str) and tool.strip() and isinstance(action, str) and action.strip():
            return {"tool": tool.strip()[:64], "action": action.strip()[:128]}
        return None
    if not isinstance(value, list):
        return None
    command = value if all(isinstance(item, str) for item in value) else next(
        (item for item in reversed(value) if isinstance(item, list) and all(isinstance(part, str) for part in item)),
        None,
    )
    if not isinstance(command, list) or len(command) < 3:
        return None
    tool, group, action = (part.strip() for part in command[:3])
    if not group or not action:
        return None
    return {"tool": tool[:64] or "weibo-cli", "action": f"{group}.{action}"[:128]}


def append_published_log(
    root: Path,
    commit_id: str,
    text: str,
    tags: list[str],
    images: list[Path | dict[str, str]],
    pic_ids: list[str],
    weibo_id: str | None,
    commands: list[list[str]],
    attempt_id: str | None = None,
    version: int | None = None,
    command_metadata_value: dict[str, str] | None = None,
) -> bool:
    path = safe_join(root, ".vibesocial/published-log.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    current_hash = text_hash(text)
    if published_log_contains(root, commit_id, current_hash, weibo_id):
        return False
    action = "statuses.upload_url_text" if images or pic_ids else "statuses.update"
    record = {
        "schema_version": 2,
        "social_commit_id": commit_id,
        "version": version if version is not None else 1,
        "published_at": now(),
        "weibo_id": weibo_id,
        "text_hash": current_hash,
        "tags": tags,
        "images": image_metadata_records(images),
        "remote": {"platform": "weibo", "pic_ids": pic_ids},
        "command": command_metadata_value or {"tool": "weibo-cli", "action": action},
    }
    if attempt_id is not None:
        record["attempt_id"] = attempt_id
    if version is not None:
        record["version"] = version
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def credential_unavailable(text: str) -> bool:
    lowered = text.lower()
    return any(marker in text or marker in lowered for marker in (
        "无法读取", "凭据不可见", "credential unavailable", "access denied", "access is denied", "permission denied",
    ))


def doctor_report(text: str, returncode: int = 0, credential_state: str | None = None) -> str:
    clean = strip_ansi(text)
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    def positive(line: str) -> bool:
        return any(marker in line for marker in ("✓", "√", "成功", "完成", "可用", "已登录", "ready", "success"))
    account_line = next((line for line in lines if any(marker in line for marker in ("登录", "账号", "account", "login"))), "")
    platform_line = next((line for line in lines if any(marker in line for marker in ("开发者", "开放平台", "认证", "developer", "auth"))), "")
    service_line = next((line for line in lines if any(marker in line for marker in ("服务", "开通", "service"))), "")
    if credential_state == "unreadable":
        account = "⚠ 无法确认"
    elif account_line and positive(account_line):
        account = "✓ 已登录"
    elif any(marker in clean for marker in ("× 登录", "✗ 登录", "未登录", "未检测到授权", "登录失败", "login failed", "not logged")):
        account = "⚠ 未检测到授权"
    else:
        account = "⚠ 无法确认"
    cli = "✓ 可用" if returncode == 0 else "⚠ 不可访问"
    platform = "✓ 已开通" if platform_line and positive(platform_line) else "⚠ 未检测"
    service = "✓ 已开通" if service_line and positive(service_line) else "⚠ 未检测"
    return "\n".join([
        "微博环境检查：",
        f"微博账号：{account}",
        f"CLI环境：{cli}",
        f"开发者服务：{platform if platform_line else service}",
    ])


def doctor(base: list[str], output_fn: Any = None) -> str:
    result = run_cli(base, ["doctor"])
    raw = result.stdout + "\n" + result.stderr
    if credential_unavailable(raw):
        report = doctor_report(raw, result.returncode, credential_state="unreadable")
        message = (
            f"{report}\n\n"
            "无法读取微博授权状态。\n\n"
            "可能原因：\n"
            "- 当前运行环境无法访问本机微博 CLI 凭据\n"
            "- 请使用与 auth login 相同的用户环境运行\n\n"
            "当前环境无法完成自动验证，请确认已在同一用户终端完成微博登录。\n\n"
            "下一步：\n"
            "[1] 重新检查\n"
            "[2] 返回发布选择"
        )
        if output_fn is not None:
            output_fn(message)
        return report
    report = doctor_report(raw, result.returncode)
    explicit_account_failure = any(marker in raw for marker in ("× 登录", "✗ 登录", "未登录", "未检测到授权", "登录失败", "login failed", "not logged"))
    if explicit_account_failure:
        raise PublishError(
            f"{report}\n\n"
            "未检测到微博授权。\n\n"
            "下一步：\n"
            "[1] 登录微博账号\n"
            "[2] 返回\n\n"
            f"{cli_error(result, 'weibo-cli doctor') if result.returncode != 0 else '请先完成 auth login。'}"
        )
    if result.returncode != 0:
        raise PublishError(
            f"{report}\n\n微博环境检查未完成。\n\n下一步：\n[1] 重新检查\n[2] 返回\n\n"
            f"{cli_error(result, 'weibo-cli doctor')}"
        )
    if output_fn is not None:
        output_fn(report)
    return report


def preference_path(root: Path) -> Path:
    return root / ".vibesocial" / "platform_preferences" / "weibo.json"


def read_weibo_preferences(root: Path) -> dict[str, Any]:
    path = preference_path(root)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def save_weibo_preferences(root: Path, tags: list[str]) -> None:
    path = preference_path(root)
    vibe_state.atomic_json(path, {"default_tags": tags, "updated_at": now()})


def suggested_weibo_tags(commit: dict[str, Any], preferences: dict[str, Any]) -> list[str]:
    preferred = preferences.get("default_tags")
    raw = preferred if isinstance(preferred, list) else commit.get("tag_suggestions") or commit.get("tags") or []
    if isinstance(raw, str):
        raw = re.split(r"[,，\s]+", raw)
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        value = str(item).strip().strip("#")
        if value and value not in result:
            result.append(value)
    return result


def select_weibo_tags(
    root: Path, commit: dict[str, Any], input_fn: Any = None, output_fn: Any = print,
) -> list[str]:
    input_fn = input if input_fn is None else input_fn
    preferences = read_weibo_preferences(root)
    defaults = suggested_weibo_tags(commit, preferences)
    shown = " ".join(normalize_tag(tag) for tag in defaults) or "暂无默认标签"
    output_fn(
        "是否添加微博标签？\n\n"
        f"当前默认标签：{shown}\n\n"
        "[1] 使用默认标签\n"
        "[2] 修改标签\n"
        "[3] 不添加"
    )
    while True:
        choice = input_fn("请选择：").strip()
        if choice == "1":
            save_weibo_preferences(root, defaults)
            return defaults
        if choice == "2":
            raw = input_fn("请输入标签，多个标签用空格或逗号分隔：").strip()
            values = [item.strip().strip("#") for item in re.split(r"[,，\s]+", raw) if item.strip().strip("#")]
            save_weibo_preferences(root, values)
            return values
        if choice == "3":
            save_weibo_preferences(root, [])
            return []
        output_fn("请输入 1、2 或 3。")


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def parse_command_catalog(text: str) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for line in strip_ansi(text).splitlines():
        match = re.match(r"^\s{2,}([A-Za-z0-9_-]+)\s+([A-Za-z0-9_/-]+)(?:\s{2,}|\t+)(.*)$", line)
        if not match:
            continue
        group, action, description = match.groups()
        commands.append({"group": group, "action": action, "description": description.strip()})
    return commands


def list_available(base: list[str]) -> list[dict[str, str]]:
    # Use only the confirmed human-facing discovery command. Do not append
    # unverified output-format flags to the installed CLI.
    human = run_cli(base, ["commands", "list", "--available"])
    if human.returncode != 0:
        raise PublishError(cli_error(human, "Unable to list available weibo-cli commands"))
    commands = parse_command_catalog(human.stdout)
    if not commands:
        raise PublishError("No usable commands were returned by weibo-cli commands list --available")
    return commands


def parse_schema_output(text: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        command = payload.get("command", payload) if isinstance(payload, dict) else None
        if isinstance(command, dict) and isinstance(command.get("flags"), list):
            return command
    except json.JSONDecodeError:
        pass

    flags: list[dict[str, Any]] = []
    in_flags = False
    for line in strip_ansi(text).splitlines():
        if line.strip() == "Flags:":
            in_flags = True
            continue
        if not in_flags:
            continue
        match = re.match(
            r"^\s*(?:-[A-Za-z0-9],\s*)?(--[A-Za-z0-9][A-Za-z0-9_-]*)"
            r"(?:\s+([^\s]+))?\s{2,}(.*)$",
            line,
        )
        if not match:
            continue
        name, type_name, description = match.groups()
        flags.append({
            "name": name[2:],
            "type": type_name or "string",
            "description": description.strip(),
            "required": bool(re.search(r"\brequired\b|必填", description, re.IGNORECASE)),
        })
    if not flags:
        raise PublishError(f"{label} has no usable flags list")
    return {"flags": flags}


def command_schema(base: list[str], group: str, action: str) -> dict[str, Any]:
    result = run_cli(base, ["commands", "show", group, action])
    if result.returncode != 0:
        raise PublishError(cli_error(result, f"Unable to inspect schema for {group} {action}"))
    return parse_schema_output(result.stdout, f"Schema for {group} {action}")


def available_command(catalog: list[dict[str, str]], command: tuple[str, str]) -> bool:
    return any(item.get("group") == command[0] and item.get("action") == command[1] for item in catalog)


def schema_flags(schema: dict[str, Any], command: tuple[str, str], required: tuple[str, ...]) -> None:
    names = {
        flag.get("name")
        for flag in schema.get("flags", [])
        if isinstance(flag, dict) and isinstance(flag.get("name"), str)
    }
    missing = [name for name in required if name not in names]
    if missing:
        raise PublishError(
            f"当前 CLI 未确认发布参数，请先检查可用命令。"
            f" {command[0]} {command[1]} 缺少: {', '.join(missing)}"
        )


def status_args(status: str, longtext: bool) -> list[str]:
    args = ["--status", status, "--mblog_statement", "1"]
    if longtext:
        args.extend(["--is_longtext", "1"])
    return args


def canonical_weibo_text(value: str) -> str:
    """Normalize the documented readback formats without changing content meaning."""
    value = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"<br\\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\u200b", "").replace("\ufeff", "")
    return "\n".join(line.rstrip() for line in value.split("\n")).strip()


def extract_status_record(payload: Any, weibo_id: str) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        statuses = payload.get("statuses")
        if isinstance(statuses, list):
            for item in statuses:
                found = extract_status_record(item, weibo_id)
                if found:
                    return found
        if "text" in payload and any(str(payload.get(key, "")) == weibo_id for key in ("id", "idstr", "mid")):
            return payload
        for value in payload.values():
            found = extract_status_record(value, weibo_id)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = extract_status_record(item, weibo_id)
            if found:
                return found
    return None


def readback_text(record: dict[str, Any]) -> str | None:
    if record.get("is_long_text") or record.get("isLongText"):
        long_text = record.get("longText") or record.get("long_text")
        if isinstance(long_text, str):
            return long_text
        if isinstance(long_text, dict):
            for key in ("longTextContent", "long_text_content", "content", "text"):
                value = long_text.get(key)
                if isinstance(value, str):
                    return value
        return None
    text = record.get("text")
    return text if isinstance(text, str) else None


def verify_remote_content(
    base: list[str], weibo_id: str | None, expected: str, attempts: int = 4, delay_seconds: float = 2.0
) -> None:
    """Fail closed when Weibo accepts a write but does not retain its full text."""
    if not weibo_id:
        raise PublishError("微博发布响应未返回微博 ID，无法回读确认正文；保持 APPROVED")
    actual: str | None = None
    last_error: str | None = None
    for attempt in range(attempts):
        result = run_cli(base, [READBACK_COMMAND[0], READBACK_COMMAND[1], "--ids", weibo_id, "--isGetLongText", "1"])
        if result.returncode != 0:
            last_error = cli_error(result, "微博发布后正文回读失败")
        else:
            record = extract_status_record(cli_payload(result), weibo_id)
            actual = readback_text(record) if record else None
            if actual is not None and canonical_weibo_text(actual) == canonical_weibo_text(expected):
                return
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    actual_length = len(canonical_weibo_text(actual)) if actual is not None else 0
    suffix = f"；最后一次回读错误：{last_error}" if last_error else ""
    raise PublishError(
        "微博接口未在回读窗口内保留完整正文（预期 "
        f"{len(canonical_weibo_text(expected))} 字，回读 {actual_length} 字，微博 ID {weibo_id}）；"
        f"保持 APPROVED。{suffix}"
    )


def discover_confirmed_schemas(
    base: list[str], catalog: list[dict[str, str]], status: str, has_images: bool
) -> dict[str, dict[str, Any]]:
    commands = (TEXT_COMMAND,) if not has_images else (PIC_UPLOAD_COMMAND, IMAGE_TEXT_COMMAND)
    if any(not available_command(catalog, command) for command in commands):
        raise PublishError("当前 CLI 未确认发布参数，请先检查可用命令。")
    schemas: dict[str, dict[str, Any]] = {}
    for group, action in commands:
        schema = command_schema(base, group, action)
        if (group, action) == TEXT_COMMAND:
            required = ("status", "mblog_statement")
            if len(status) > 140:
                required += ("is_longtext",)
        elif (group, action) == PIC_UPLOAD_COMMAND:
            required = ("pic",)
        else:
            required = ("pic_id", "status", "mblog_statement")
            if len(status) > 140:
                required += ("is_longtext",)
        schema_flags(schema, (group, action), required)
        schemas[action] = schema
    # Publish is not considered successful until the platform returns the same
    # text. Check this read-only schema before any write, but do not make it a
    # format-specific publishing command.
    readback_schema = command_schema(base, *READBACK_COMMAND)
    schema_flags(readback_schema, READBACK_COMMAND, ("ids", "isGetLongText"))
    schemas[READBACK_COMMAND[1]] = readback_schema
    return schemas


def redacted_command(base: list[str], group: str, action: str, args: list[str]) -> list[str]:
    result = ["weibo-cli", group, action]
    skip_value = False
    for item in args:
        if skip_value:
            result.append("<value>")
            skip_value = False
        elif item.startswith("--"):
            result.append(item)
            skip_value = True
        else:
            result.append("<value>")
    return result


def command_metadata(group: str, action: str) -> dict[str, str]:
    return {"tool": "weibo-cli", "action": f"{group}.{action}"}


def extract_weibo_id(payload: Any) -> str | None:
    preferred = ("weibo_id", "status_id", "idstr", "mid", "id")
    if isinstance(payload, dict):
        for key in preferred:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value)
        for value in payload.values():
            found = extract_weibo_id(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = extract_weibo_id(value)
            if found:
                return found
    elif isinstance(payload, str):
        match = re.search(r"(?:weibo[_ -]?id|status[_ -]?id|微博ID|微博id)\s*[:：=]\s*([A-Za-z0-9_-]+)", payload, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_pic_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("pic_id")
        if value is not None and str(value).strip():
            return str(value)
        for nested in payload.values():
            found = extract_pic_id(nested)
            if found:
                return found
    elif isinstance(payload, list):
        for nested in payload:
            found = extract_pic_id(nested)
            if found:
                return found
    elif isinstance(payload, str):
        match = re.search(r"pic_id\s*[:：=]\s*([A-Za-z0-9_-]+)", payload, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def cli_payload(result: subprocess.CompletedProcess[str]) -> Any:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def publish(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_publish:
        raise PublishError("Publishing requires the explicit --confirm-publish guard")

    root = validate_scan_root(args.root)
    path, commit = read_commit(root, args.commit)
    current_state = get_publish_status(commit)
    if current_state == PUBLISHED:
        raise PublishError("该 Social Commit 已经 PUBLISHED，禁止重复发布。", publish_status=PUBLISHED)
    if current_state in {PUBLISHING, UNKNOWN_REQUIRES_RECONCILIATION}:
        raise PublishError(
            f"当前发布状态为 {current_state}，请先 reconcile，禁止直接重试。",
            publish_status=current_state,
        )
    if commit.get("status") != "APPROVED":
        raise PublishError(f"Social Commit must be APPROVED, found {commit.get('status')!r}")

    command_for_record: list[str] | None = None
    command_records: list[list[str]] = []
    final_write_started = False

    try:
        text = commit.get("final_text")
        if not isinstance(text, str) or not text.strip():
            raise PublishError("Approved Social Commit has no final_text")
        images = extract_images(commit)
        input_fn = getattr(args, "input_fn", None)
        output_fn = getattr(args, "output_fn", print)
        previous_publish = commit.get("publish") if isinstance(commit.get("publish"), dict) else {}
        if current_state == FAILED_RETRYABLE and isinstance(previous_publish.get("tags"), list):
            tags = [str(tag) for tag in previous_publish["tags"]]
        else:
            tags = select_weibo_tags(root, commit, input_fn, output_fn)
        images = confirm_preview(
            commit,
            images,
            input_fn,
            output_fn,
            tags,
        )
        original_status = compose_status(commit, tags)
        status = transport_status(original_status, preserve_newlines=True)
        if not status:
            raise PublishError("Approved Social Commit has no publishable status text")

        attempt_id = new_attempt_id(commit["id"])
        attempt = {
            "status": PUBLISHING,
            "attempt_id": attempt_id,
            "social_commit_id": commit["id"],
            "version": content_version(commit),
            "text_hash": text_hash(status),
            "phase": "preflight",
            "started_at": now(),
            "remote_id": None,
            "tags": tags,
            "images": [safe_image_metadata(image) for image in images],
            "pic_ids": [],
        }
        commit["publish"] = attempt
        commit.pop("publish_error", None)
        vibe_state.atomic_json(path, commit)

        base = resolve_cli(args.cli)
        doctor(base, output_fn=output_fn)
        catalog = list_available(base)
        discover_confirmed_schemas(base, catalog, status, bool(images))
        pic_ids: list[str] = []
        if images:
            persist_publish(path, commit, phase="image_upload", pic_ids=pic_ids)
            for image in images:
                upload_args = [PIC_UPLOAD_COMMAND[0], PIC_UPLOAD_COMMAND[1], "--pic", str(image)]
                upload_record = redacted_command(base, PIC_UPLOAD_COMMAND[0], PIC_UPLOAD_COMMAND[1], upload_args[2:])
                result = run_cli(base, upload_args)
                if result.returncode != 0:
                    raise PublishError(cli_error(result, "weibo-cli upload_pic failed"))
                pic_id = extract_pic_id(cli_payload(result))
                if not pic_id:
                    raise PublishError("statuses upload_pic 未返回 pic_id，已停止发布")
                try:
                    pic_id = validate_remote_id(pic_id)
                except SafetyError as exc:
                    raise PublishError("statuses upload_pic 返回了不安全的 pic_id") from exc
                pic_ids.append(pic_id)
                command_records.append(upload_record)
                persist_publish(path, commit, phase="image_upload", pic_ids=pic_ids)
            publish_args = [
                IMAGE_TEXT_COMMAND[0], IMAGE_TEXT_COMMAND[1],
                "--pic_id", ",".join(pic_ids),
                *status_args(status, len(status) > 140),
            ]
            group, action = IMAGE_TEXT_COMMAND
        else:
            publish_args = [
                TEXT_COMMAND[0], TEXT_COMMAND[1],
                *status_args(status, len(status) > 140),
            ]
            group, action = TEXT_COMMAND
        command_for_record = redacted_command(base, group, action, publish_args[2:])
        command_records.append(command_for_record)
        persist_publish(
            path,
            commit,
            phase="remote_write",
            command=command_metadata(group, action),
            pic_ids=pic_ids,
        )
        final_write_started = True
        result = run_cli(base, publish_args)
        if result.returncode != 0:
            raise PublishError(cli_error(result, "weibo-cli publish failed"))
        weibo_id = extract_weibo_id(cli_payload(result))
        if not weibo_id:
            raise PublishError("微博发布响应未返回微博 ID，无法安全确认发布结果")
        try:
            weibo_id = validate_remote_id(weibo_id)
        except SafetyError as exc:
            raise PublishError("微博发布响应返回了不安全的微博 ID") from exc
        persist_publish(
            path,
            commit,
            phase="readback",
            remote_id=weibo_id,
            remote_result="response_received",
        )
        verify_remote_content(base, weibo_id, status)

        commit["status"] = "PUBLISHED"
        commit.pop("publish_error", None)
        commit["publish"] = {
            "platform": "weibo",
            "status": PUBLISHED,
            "attempt_id": attempt_id,
            "social_commit_id": commit["id"],
            "version": content_version(commit),
            "text_hash": text_hash(status),
            "weibo_id": weibo_id,
            "tags": tags,
            "images": [safe_image_metadata(image) for image in images],
            "pic_ids": pic_ids,
            "published_at": now(),
            "command": command_metadata(group, action),
        }
        vibe_state.atomic_json(path, commit)
        log_warning = None
        try:
            append_published_log(
                root,
                commit["id"],
                status,
                tags,
                images,
                pic_ids,
                weibo_id,
                command_records,
                attempt_id=attempt_id,
                version=content_version(commit),
            )
        except OSError as exc:
            log_warning = f"published-log 写入失败，可通过 reconcile 修复：{str(exc)[:240]}"
        result = {
            "result": "published",
            "commit": commit["id"],
            "weibo_id": weibo_id,
            "command": command_for_record,
            "current_state": "PUBLISHED",
            "completed": "微博已发布，并已确认完整正文。",
            "next": ["查看分发记录", "开始处理下一篇", "暂停"],
        }
        if log_warning:
            result["warning"] = log_warning
        return result
    except (OSError, subprocess.SubprocessError, PublishError) as exc:
        if isinstance(exc, PublishCancelled):
            raise
        try:
            failure_state = record_failure(path, commit, str(exc)[:500], final_write_started)
        except OSError:
            failure_state = UNKNOWN_REQUIRES_RECONCILIATION if final_write_started else FAILED_RETRYABLE
        if isinstance(exc, PublishError):
            exc.publish_status = failure_state
        raise


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    """Reconcile a post created by a prior write without performing another write."""
    root = validate_scan_root(args.root)
    path, commit = read_commit(root, args.commit)
    current_state = get_publish_status(commit)
    if current_state == PUBLISHED:
        publish = commit.get("publish") if isinstance(commit.get("publish"), dict) else {}
        log_warning = None
        if isinstance(publish.get("weibo_id"), str) and isinstance(commit.get("final_text"), str):
            tags = publish.get("tags") if isinstance(publish.get("tags"), list) else []
            status = transport_status(compose_status(commit, tags), preserve_newlines=True)
            images = persisted_image_values(publish, commit)
            stored_pic_ids = publish.get("pic_ids")
            pic_ids = [str(pic_id) for pic_id in stored_pic_ids] if isinstance(stored_pic_ids, list) else []
            command_meta = normalize_command_metadata(publish.get("command"))
            if command_meta is None:
                command_meta = normalize_command_metadata(publish.get("command_used"))
            try:
                append_published_log(
                    root,
                    commit["id"],
                    status,
                    tags,
                    images,
                    pic_ids,
                    str(publish["weibo_id"]),
                    [],
                    attempt_id=publish.get("attempt_id"),
                    version=content_version(commit),
                    command_metadata_value=command_meta,
                )
            except OSError as exc:
                log_warning = f"published-log 写入失败，可再次 reconcile 修复：{str(exc)[:240]}"
        result = {
            "result": "already_published",
            "commit": commit["id"],
            "current_state": "PUBLISHED",
            "completed": "该 Social Commit 已经标记为 PUBLISHED，未执行外部写入。",
            "next": ["查看分发记录", "开始处理下一篇", "暂停"],
        }
        if log_warning:
            result["warning"] = log_warning
        return result
    if current_state not in {PUBLISHING, UNKNOWN_REQUIRES_RECONCILIATION}:
        raise PublishError(f"当前发布状态不需要 reconcile：{current_state}")
    text = commit.get("final_text")
    if not isinstance(text, str) or not text.strip():
        raise PublishError("Approved Social Commit has no final_text")
    publish = commit.get("publish") if isinstance(commit.get("publish"), dict) else {}
    images = persisted_image_values(publish, commit)
    stored_pic_ids = publish.get("pic_ids")
    pic_ids = [str(pic_id) for pic_id in stored_pic_ids] if isinstance(stored_pic_ids, list) else []
    tags = publish.get("tags") if isinstance(publish.get("tags"), list) else None
    if not isinstance(tags, list):
        tags = suggested_weibo_tags(commit, read_weibo_preferences(root))
    status = transport_status(compose_status(commit, tags), preserve_newlines=True)
    weibo_id = args.weibo_id or publish.get("remote_id")
    if not isinstance(weibo_id, str) or not weibo_id.strip():
        raise PublishError("无法自动确认微博 ID，请提供 --weibo-id；不会自动重试发布")
    try:
        weibo_id = validate_remote_id(weibo_id)
    except SafetyError as exc:
        raise PublishError("微博 ID 格式不安全") from exc
    base = resolve_cli(args.cli)
    doctor(base)
    catalog = list_available(base)
    if not available_command(catalog, READBACK_COMMAND):
        raise PublishError("当前 CLI 未确认回读参数，请先检查可用命令。")
    readback_schema = command_schema(base, *READBACK_COMMAND)
    schema_flags(readback_schema, READBACK_COMMAND, ("ids", "isGetLongText"))
    verify_remote_content(base, weibo_id, status)
    command = (
        normalize_command_metadata(publish.get("command"))
        or normalize_command_metadata(publish.get("command_used"))
        or command_metadata(*TEXT_COMMAND)
    )
    commit["status"] = "PUBLISHED"
    commit.pop("publish_error", None)
    commit["publish"] = {
        "platform": "weibo",
        "status": PUBLISHED,
        "attempt_id": publish.get("attempt_id"),
        "social_commit_id": commit["id"],
        "version": content_version(commit),
        "text_hash": text_hash(status),
        "weibo_id": weibo_id,
        "tags": tags,
        "images": image_metadata_records(images),
        "pic_ids": pic_ids,
        "published_at": now(),
        "command": command,
        "reconciled": True,
    }
    vibe_state.atomic_json(path, commit)
    log_warning = None
    try:
        append_published_log(
            root,
            commit["id"],
            status,
            tags,
            images,
            pic_ids,
            weibo_id,
            [command],
            attempt_id=publish.get("attempt_id"),
            version=content_version(commit),
            command_metadata_value=command,
        )
    except OSError as exc:
        log_warning = f"published-log 写入失败，可再次 reconcile 修复：{str(exc)[:240]}"
    result = {
        "result": "published",
        "reconciled": True,
        "commit": commit["id"],
        "weibo_id": weibo_id,
        "command": command,
        "current_state": "PUBLISHED",
        "completed": "微博正文已回读确认，并已记录分发结果。",
        "next": ["查看分发记录", "开始处理下一篇", "暂停"],
    }
    if log_warning:
        result["warning"] = log_warning
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    publish_parser = sub.add_parser("publish")
    publish_parser.add_argument("commit")
    publish_parser.add_argument("--root", default=".")
    publish_parser.add_argument("--cli", default="weibo-cli", help=argparse.SUPPRESS)
    publish_parser.add_argument("--confirm-publish", action="store_true", help=argparse.SUPPRESS)
    publish_parser.set_defaults(run=publish)
    reconcile_parser = sub.add_parser("reconcile", help=argparse.SUPPRESS)
    reconcile_parser.add_argument("commit")
    reconcile_parser.add_argument("--weibo-id")
    reconcile_parser.add_argument("--root", default=".")
    reconcile_parser.add_argument("--cli", default="weibo-cli", help=argparse.SUPPRESS)
    reconcile_parser.set_defaults(run=reconcile)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    try:
        output = args.run(args)
    except PublishRevisionRequested as exc:
        print(json.dumps({
            "result": "revision_requested",
            "feedback": exc.feedback,
            "current_state": "PULL",
            "completed": "已记录修改意见，尚未进行外部写入。",
            "next": "回到 vibe-social，选择提交以上修改（Pull）",
        }, ensure_ascii=False, indent=2))
        return 0
    except PublishCancelled as exc:
        print(json.dumps({
            "result": "cancelled",
            "current_state": "APPROVED",
            "completed": "已取消本次发布，审核通过的草稿保持不变。",
            "next": ["重新发布", "继续修改", "仅保存并暂停"],
            "message": str(exc),
        }, ensure_ascii=False, indent=2))
        return 0
    except (PublishError, SafetyError, OSError, subprocess.SubprocessError) as exc:
        current_state = getattr(exc, "publish_status", None)
        if not current_state and hasattr(args, "commit"):
            try:
                _, failed_commit = read_commit(Path(args.root).resolve(), args.commit)
                current_state = get_publish_status(failed_commit)
            except (OSError, SafetyError, PublishError, json.JSONDecodeError):
                current_state = None
        current_state = current_state or "FAILED"
        if current_state in {PUBLISHING, UNKNOWN_REQUIRES_RECONCILIATION}:
            next_steps = ["执行 reconcile", "返回修改", "仅保存并暂停"]
        elif current_state == FAILED_RETRYABLE:
            next_steps = ["重新检查并重试", "返回修改", "仅保存并暂停"]
        elif current_state == PUBLISHED:
            next_steps = ["查看分发记录", "开始处理下一篇", "暂停"]
        else:
            next_steps = ["重新检查并重试", "返回修改", "仅保存并暂停"]
        print(json.dumps({
            "error": str(exc),
            "current_state": current_state,
            "completed": "已保留审核通过的草稿，未标记为已发布。",
            "preserved_state": "APPROVED",
            "next": next_steps,
        }, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
