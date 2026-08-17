"""Shared safety boundaries for VibeSocial local files and subprocesses.

This module deliberately contains policy-level helpers only.  It does not
know anything about Story or publishing semantics.
"""

from __future__ import annotations

import os
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


MAX_GIT_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
DEFAULT_SUBPROCESS_TIMEOUT = 30
WEIBO_SUBPROCESS_TIMEOUT = 45
MAX_ID_LENGTH = 128

_COMMIT_ID = re.compile(r"^sc-[0-9]{4}$")
_PR_ID = re.compile(r"^spr-[0-9]{4}$")
_ATTEMPT_ID = re.compile(r"^pub-sc-[0-9]{4}-[0-9a-f]{12}$")
_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_WINDOWS_ABSOLUTE = re.compile(r"(?:^[A-Za-z]:[\\/])|(?:^[\\/]{2})")
_UNIX_ABSOLUTE = re.compile(r"^/")
_SENSITIVE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b|"
    r"\b(?:token|secret|password|passwd|cookie|api[_-]?key|credential)\b)",
    re.IGNORECASE,
)
_WINDOWS_PATH_IN_TEXT = re.compile(r"\b[A-Za-z]:\\(?:[^\s\\]+\\)+[^\s]*")
_UNIX_PATH_IN_TEXT = re.compile(r"(?<![\w.])/(?:home|Users|var|etc|srv|opt)/[^\s]+")
_URL_CREDENTIALS = re.compile(r"\b(?:https?|postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/[^\s]+", re.IGNORECASE)


class SafetyError(ValueError):
    """Raised when an input would cross a local safety boundary."""


@dataclass(frozen=True)
class BoundedCompletedProcess:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_truncated: bool = False


def _validate(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_LENGTH:
        raise SafetyError(f"Invalid {label}")
    if any(char.isspace() or ord(char) == 0 for char in value):
        raise SafetyError(f"Invalid {label}")
    if not pattern.fullmatch(value):
        raise SafetyError(f"Invalid {label}")
    return value


def validate_social_commit_id(value: str) -> str:
    return _validate(value, _COMMIT_ID, "Social Commit ID")


def validate_social_pr_id(value: str) -> str:
    return _validate(value, _PR_ID, "Social PR ID")


def validate_attempt_id(value: str) -> str:
    return _validate(value, _ATTEMPT_ID, "attempt ID")


def validate_remote_id(value: str) -> str:
    return _validate(value, _REMOTE_ID, "remote ID")


def safe_state_record_path(directory: Path, record_id: str, validator: object) -> Path:
    """Resolve current IDs directly and legacy IDs only by bounded JSON lookup."""
    try:
        validated = validator(record_id)  # type: ignore[operator]
    except SafetyError:
        if (
            not isinstance(record_id, str)
            or not record_id
            or len(record_id) > MAX_ID_LENGTH
            or "\x00" in record_id
            or any(char.isspace() for char in record_id)
            or ":" in record_id
            or "/" in record_id
            or "\\" in record_id
        ):
            raise SafetyError("Invalid state record ID")
        boundary = _resolved(directory)
        if not boundary.is_dir() or is_reparse_point(boundary):
            raise SafetyError("Controlled state directory is unavailable")
        inspected = 0
        for candidate in sorted(boundary.glob("*.json")):
            if inspected >= 10_000 or is_reparse_point(candidate):
                continue
            inspected += 1
            try:
                if candidate.stat().st_size > MAX_FILE_BYTES:
                    continue
                value = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("id") == record_id:
                _reject_link_chain(candidate, boundary)
                return candidate
        raise SafetyError("Legacy state record was not found in the controlled directory")
    return safe_join(directory, f"{validated}.json", must_exist=True)


def is_reparse_point(path: Path) -> bool:
    """Return whether a path is a symlink or Windows reparse point."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.stat(), "st_file_attributes", 0)
        return bool(attributes & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within_root(candidate: Path, root: Path) -> bool:
    try:
        _resolved(candidate).relative_to(_resolved(root))
        return True
    except ValueError:
        return False


def _reject_link_chain(path: Path, root: Path) -> None:
    current = path.expanduser().absolute()
    boundary = _resolved(root)
    while True:
        if current.exists() and is_reparse_point(current):
            raise SafetyError("Controlled path cannot use a symlink or reparse point")
        if current == boundary or current.parent == current:
            return
        current = current.parent


def safe_join(root: Path, relative: str | Path, *, allowed_root: Path | None = None, must_exist: bool = False) -> Path:
    """Join a controlled relative path and prove it remains under allowed_root."""
    raw = str(relative)
    if not raw or "\x00" in raw or _WINDOWS_ABSOLUTE.search(raw) or _UNIX_ABSOLUTE.search(raw):
        raise SafetyError("Absolute or invalid path is not allowed")
    if Path(raw).is_absolute() or any(part == ".." for part in re.split(r"[\\/]", raw)):
        raise SafetyError("Path traversal is not allowed")
    root = _resolved(root)
    boundary = _resolved(allowed_root or root)
    candidate = _resolved(root / raw)
    if not is_within_root(candidate, boundary):
        raise SafetyError("Path is outside the allowed root")
    _reject_link_chain(candidate, boundary)
    if must_exist and not candidate.exists():
        raise SafetyError("Controlled path does not exist")
    return candidate


def safe_input_path(root: Path, value: str | Path) -> Path:
    """Resolve an input file only when it is inside the approved project root."""
    raw = Path(value)
    if raw.is_absolute():
        candidate = _resolved(raw)
        boundary = _resolved(root)
        if not is_within_root(candidate, boundary):
            raise SafetyError("Input file is outside the approved root")
        _reject_link_chain(raw, boundary)
    else:
        candidate = safe_join(root, raw, must_exist=True)
    if not candidate.is_file():
        raise SafetyError("Input file does not exist")
    return candidate


def safe_output_path(root: Path, value: str | Path | None, default_name: str) -> Path:
    """Resolve Skill-owned output strictly below <root>/.vibesocial/."""
    base = _resolved(root / ".vibesocial")
    raw = Path(value) if value else Path(default_name)
    candidate = _resolved(raw if raw.is_absolute() else root / raw)
    if not is_within_root(candidate, base):
        raise SafetyError("Skill output must be inside .vibesocial")
    _reject_link_chain(raw if raw.is_absolute() else root / raw, base)
    return candidate


def validate_scan_root(value: str | Path, *, approved_root: Path | None = None, scope: str = "project") -> Path:
    root = _resolved(Path(value))
    if not root.is_dir() or is_reparse_point(root):
        raise SafetyError("Scan root must be a real directory")
    if scope not in {"project", "workspace"}:
        raise SafetyError("Invalid scan scope")
    if approved_root is not None and scope == "project" and not is_within_root(root, approved_root):
        raise SafetyError("Project scan root is outside the approved root")
    return root


def safe_error(code: str, fallback: str) -> dict[str, str]:
    """Create a non-sensitive persisted error without retaining exception text."""
    safe = fallback.strip() if fallback else "操作未完成"
    safe = _WINDOWS_PATH_IN_TEXT.sub("<local-path>", safe)
    safe = _UNIX_PATH_IN_TEXT.sub("<local-path>", safe)
    safe = _URL_CREDENTIALS.sub("<private-url>", safe)
    if _SENSITIVE.search(safe):
        safe = "操作失败，详细信息未保存。"
    return {"error_code": code, "error_message_safe": safe[:240]}


def safe_image_metadata(path: Path) -> dict[str, str]:
    name = path.name.replace("\x00", "")[:128] or "image"
    return {"name": name, "source": "local_image", "extension": path.suffix.lower()}


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        process.kill()
    except OSError:
        pass


def bounded_subprocess(
    command: Sequence[str],
    *,
    timeout: int = DEFAULT_SUBPROCESS_TIMEOUT,
    max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
    cwd: Path | None = None,
) -> BoundedCompletedProcess:
    """Run a list-form subprocess with bounded output and safe cancellation."""
    args = [str(item) for item in command]
    if not args or any("\x00" in item for item in args):
        raise SafetyError("Invalid subprocess arguments")
    if timeout <= 0 or max_output_bytes <= 0:
        raise SafetyError("Invalid subprocess limits")
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": str(cwd) if cwd else None,
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(args, **kwargs)  # type: ignore[arg-type]
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}

    def read_stream(name: str, stream: object) -> None:
        if stream is None:
            return
        reader = stream  # type: ignore[assignment]
        while True:
            chunk = reader.read(65536)
            if not chunk:
                return
            if len(buffers[name]) < max_output_bytes:
                remaining = max_output_bytes - len(buffers[name])
                buffers[name].extend(chunk[:remaining])
            if len(buffers[name]) < len(chunk) or len(chunk) > max_output_bytes:
                truncated[name] = True

    threads = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if process.poll() is None:
            timed_out = True
            _terminate(process)
        returncode = process.wait(timeout=5)
    except KeyboardInterrupt:
        _terminate(process)
        process.wait(timeout=5)
        return BoundedCompletedProcess(args, 130, "", "进程已取消", False, False)
    finally:
        for thread in threads:
            thread.join(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    if timed_out:
        returncode = 124
        buffers["stderr"] = bytearray("进程超时，原始输出未保存".encode("utf-8"))
        truncated["stderr"] = False
    return BoundedCompletedProcess(
        args,
        returncode,
        bytes(buffers["stdout"]).decode("utf-8", errors="replace"),
        bytes(buffers["stderr"]).decode("utf-8", errors="replace"),
        timed_out,
        truncated["stdout"] or truncated["stderr"],
    )
