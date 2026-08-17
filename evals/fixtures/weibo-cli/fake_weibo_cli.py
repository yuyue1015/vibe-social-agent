#!/usr/bin/env python3
"""Small recorded-response CLI used only by the repository eval harness."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
RESPONSES = json.loads((FIXTURE_DIR / "responses.json").read_text(encoding="utf-8"))


def record(action: str, args: list[str]) -> None:
    log_path = os.environ.get("FAKE_WEIBO_LOG")
    if not log_path:
        return
    flags = [item for item in args if item.startswith("--")]
    with Path(log_path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"action": action, "flags": flags}, ensure_ascii=False) + "\n")


def value(args: list[str], name: str, default: str = "") -> str:
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        return default


def main() -> int:
    args = sys.argv[1:]
    action = " ".join(args[:2]) if len(args) >= 2 else " ".join(args)
    scenario = os.environ.get("FAKE_WEIBO_SCENARIO", "success")
    record(action, args)

    if args[:1] == ["doctor"]:
        if scenario == "credential_unavailable":
            print("credential unavailable", file=sys.stderr)
            return 1
        print("login: success\nservice: success")
        return 0
    if args[:3] == ["commands", "list", "--available"]:
        if scenario == "credential_unavailable":
            print("credential unavailable", file=sys.stderr)
            return 1
        print("\n".join(RESPONSES["commands"]))
        return 0
    if args[:2] == ["commands", "show"]:
        key = " ".join(args[2:4])
        names = RESPONSES["schemas"].get(key, [])
        if scenario == "schema_mismatch" and key == "statuses update":
            names = ["status"]
        print(json.dumps({"command": {"flags": [{"name": name} for name in names]}}))
        return 0

    state_path = Path(os.environ.get("FAKE_WEIBO_STATE", "fake-state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    if args[:2] == ["statuses", "upload_pic"]:
        state["pic_id"] = "pic-001"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        print(json.dumps({"pic_id": "pic-001"}))
        return 0
    if args[:2] in (["statuses", "update"], ["statuses", "upload_url_text"]):
        state["text"] = value(args, "--status")
        state["weibo_id"] = "wb-001"
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"id": "wb-001"}))
        return 0
    if args[:2] == ["statuses", "show_batch/biz"]:
        text = state.get("text", "")
        if scenario == "readback_mismatch":
            text = "different remote text"
        print(json.dumps({"statuses": [{"id": value(args, "--ids", "wb-001"), "text": text}]}))
        return 0
    print("unsupported fake command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
