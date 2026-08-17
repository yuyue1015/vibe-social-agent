# Scan boundary

This reference defines the route into project inspection. The safety helpers and their tests remain the executable boundary; this file does not replace them.

## Required preflight

After the user selects a project, resolve `project_root` and run:

```text
python .agents/skills/vibe-social/scripts/scan_guard.py preflight --project-root <project-root>
```

Run it before every first analysis and whenever the selected project or scope changes. If the Git root is a parent workspace, offer the existing choices: current project (default), entire workspace after explicit confirmation, or cancel. Never silently widen the root.

Respect the preflight result and resource confirmation. Warn above the configured large-scan threshold, require explicit confirmation above the hard confirmation threshold, and rerun with `--confirm-large-scan` before continuing. Report only counts, estimates, and reason codes for skipped material.

## Approved inspection

Pass only the selected project or explicitly confirmed workspace root to `story_detect.py`, and keep generated output under the project’s `.vibesocial/`. Inspect scoped Git summaries, selected development documents, tests, changelogs, audits, and reports. Do not read credential stores, `.env` files, raw source broadly, or private URLs.

Use the bundled scan and I/O helpers for root containment, symlink/junction policy, file and Git budgets, bounded output, and subprocess timeouts. A scan that exceeds a budget skips safely and reports how much was skipped without exposing full paths.
