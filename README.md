# Vibe Social Agent

Vibe Social Agent is a local Codex Skill Bundle that turns real software-development progress into privacy-reviewed, human-approved social drafts.

It is for developers who want to explain what they built, changed, tested, or learned without handing over source code or automatically publishing anything.

## What it does

- Finds public-safe development story candidates.
- Ranks concrete, reader-relevant changes.
- Generates and revises factual drafts.
- Keeps approval separate from external publishing.
- Learns approved writing preferences locally.
- Optionally hands an approved version to the separate Weibo publishing Skill.

It does not modify application code, create a server or database, ingest comments, support multiple platforms, or publish without explicit human confirmation.

## Skill Bundle

Install both directories together:

- `vibe-social`: core scanning, story selection, drafting, revision, Pull, Approve, and local Writing Memory.
- `weibo-publish`: optional external Weibo publishing for an already `APPROVED` Social Commit.

The core Skill works without `weibo-cli`. The publishing Skill has a runtime dependency on the sibling `vibe-social` scripts, so do not install it by itself.

## Install

From a clean clone of this repository, run a dry-run first:

```powershell
.\scripts\install.ps1 -TargetRoot C:\path\to\your\project
```

Apply the installation only after reviewing the preview:

```powershell
.\scripts\install.ps1 -TargetRoot C:\path\to\your\project -Apply
```

On macOS/Linux:

```bash
bash ./scripts/install.sh --target /path/to/your/project
bash ./scripts/install.sh --target /path/to/your/project --apply
```

The installer copies only `.agents/skills/vibe-social` and `.agents/skills/weibo-publish`. It does not change project source, Git history, or `.vibesocial/`.

## Doctor

Run from this repository and point it at the target project:

```bash
python scripts/doctor.py --root /path/to/your/project
```

Core checks cover Python 3.11+, Git, both Skill directories, Skill metadata, references, and `.vibesocial` writability. Missing `weibo-cli` is a warning and does not make the core Skill unusable.

### Troubleshooting credential visibility

If `weibo-cli doctor` succeeds in your own PowerShell or Terminal but the Codex execution environment reports that credentials are unavailable, the environment may not be able to read the system Credential Store. Run the publishing flow from the same user environment used for `weibo-cli auth login`; do not repeatedly run `auth login` from an environment that cannot see those credentials.

## First use

Start Codex in the target project and invoke:

```text
$vibe-social
```

Choose a new or existing project, review the scan boundary, select a story candidate, and generate a draft. The normal flow is:

```text
scan → select material → draft → revise → Pull → Approve → save or publish handoff
```

Approve never publishes. Weibo publishing requires the separate Skill, an approved version, a final preview, and an explicit confirmation.

## Weibo publishing

Install and configure `weibo-cli` only if Weibo publishing is needed. The publishing adapter discovers the installed CLI schema and performs readback verification. On Windows, a `.ps1` CLI requires PowerShell. The current production code does not require Git Bash or ANSI-C quoting.

## Local data and privacy

`.vibesocial/` is local-only and gitignored. It may contain drafts, Writing Memory, approval state, series state, local publishing records, and platform preferences. It can contain private user-authored text.

- Updates preserve `.vibesocial/`.
- Normal Skill uninstall preserves `.vibesocial/`.
- Only the explicit full-removal mode deletes `.vibesocial/`.
- Do not copy `.vibesocial/` into a public repository or release archive.

See [SECURITY.md](SECURITY.md) and [privacy documentation](docs/privacy.md).

## Update and uninstall

Preview an update before applying it:

```powershell
.\scripts\install.ps1 -TargetRoot C:\path\to\your\project -Update
```

Use `-Apply` after reviewing the preview. Updates replace only the two Skill directories and never migrate or delete local state.

On macOS/Linux, use `bash ./scripts/install.sh --target /path/to/your/project --update --apply` after its dry-run preview.

Uninstall is also dry-run by default:

```powershell
.\scripts\uninstall.ps1 -TargetRoot C:\path\to\your\project
```

Mode 1 removes the Skill Bundle and keeps `.vibesocial/`. Mode 2 requires a second confirmation and removes both the Bundle and `.vibesocial/`.

On macOS/Linux, use the equivalent dry-run script:

```bash
bash ./scripts/uninstall.sh --target /path/to/your/project --mode 1
```

## Support status

- **Tested:** Windows + Codex for the core workflow and local fake-CLI task tests.
- **Supported:** Codex projects using `.agents/skills`, Python 3.11+ on the tested workflow.
- **Experimental:** Linux and macOS host workflows; real `weibo-cli` integration outside the tested Windows environment.
- **Unsupported:** GitHub Copilot Agent Skills and other hosts until independently verified.

This repository does not claim that a generic `SKILL.md` host provides the same installation or trigger behavior.

## Version

Current status: **Beta Candidate** (`v0.1.0b1`). This repository is not a pip package and does not provide an npx installer.

## License

Released under the [MIT License](LICENSE).
