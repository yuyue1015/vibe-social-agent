#!/bin/sh
exec "${PYTHON:-python3}" "$(dirname "$0")/fake_weibo_cli.py" "$@"
