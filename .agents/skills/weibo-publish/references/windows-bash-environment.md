# Windows, Bash, and long-text transport

## Purpose

The publish adapter preserves an approved long Weibo text by sending it through Git Bash with Bash ANSI-C quoting. This is a transport detail of the adapter, not a token or login mechanism.

## Shell boundary

| Environment | `$'first line\nsecond line'` | Correct action |
| --- | --- | --- |
| Git Bash | Supported Bash ANSI-C quoting | Let `weibo_publish.py` invoke the adapter path. |
| Windows PowerShell | Not Bash syntax; manual use can be parsed differently or fail | Do not use it to reproduce the publish transport. |
| `weibo_publish.py` | Selects Git Bash for long text through `run_cli_with_ansi_c` | Use the approved adapter and final preview. |

The literal form `$'第一行\n第二行'` is expected inside the Bash command constructed by the adapter. It is not a PowerShell command and must not be copied into PowerShell for manual publishing or debugging.

## Diagnostics

`weibo-cli doctor` checks the current execution environment. Authentication and transport are separate checks:

- A credential-store access failure means the current environment cannot verify the local CLI credential. It does not prove that the user needs to log in again.
- A doctor/auth mismatch stops publishing and should be investigated as an environment, CLI, or service diagnostic issue.
- A missing Git Bash only affects long-text transport; it does not change Weibo authentication state.

Do not copy tokens into the project, environment files, or command arguments. Do not hand-run a publish command to bypass the adapter: the adapter preserves the final preview, explicit confirmation, ANSI-C text transport, readback verification, and reconciliation boundary.
