# V0.1 workflow

## State machine

`DETECTED → SOCIAL_COMMIT → SOCIAL_PR → APPROVED → PUBLISHED`

Before `SOCIAL_COMMIT`, ranked candidates receive a separate Publish Readiness result: `ready`, `hold`, or `skip`. Only `ready` enters the normal Social Commit path; `hold` and `skip` require an explicit user override. This gate does not change the state machine.

本地编辑流程在 `APPROVED` 停止；`PUBLISHED` 是用户选择内容分发并成功确认后的可选结果。微博分发由独立的 `weibo-publish` Skill 负责。

`DRAFT` 是用户可见的草稿标签，`PULL` 是提交本轮修改的用户动作；两者都不是额外的持久化状态。修改已批准内容时，先创建新的 Social Commit 和 Social PR 版本：

`APPROVED(v1) → SOCIAL_COMMIT(v2) → SOCIAL_PR(v2) → APPROVED(v2)`

旧版本保持不变。每个 APPROVED 版本最多允许一个未批准的 revision。

After a revised Social PR reaches `APPROVED`, the local Learn step compares `first_draft` with the final body, consumes safe feedback summaries, updates writing memory, stores the approved example, and records the series position. It does not change immutable Social Commit events or perform external writes.

## Git analogy

| Git | VibeSocial |
| --- | --- |
| Working tree | Current development activity |
| Diff | Candidate changes inspected in memory |
| Commit | Public-safe facts grouped as a Social Commit |
| Branch | A proposed narrative direction |
| Social PR | A reviewable social draft |
| Review | User feedback and copy revision |
| Pull | 提交以上修改（Pull）：一次用户动作，不代表审核通过，也不是持久化状态 |
| Approve | 审核通过并存入草稿箱（Approve）：进入 APPROVED，不代表发布 |
| Publish | 内容分发动作：可进入微博发布流程、手动发布其他平台或仅保存 |

用户交互优先使用中文动作，括号保留英文语义。所有“继续修改”选项统一显示为“继续修改”，选择后立即等待自然语言修改意见，并继续使用当前 DRAFT 的 `vibe_state.py draft-edit` 唯一路径；“返回修改”也必须立即等待自然语言修改意见。`APPROVED` 版本不可原地修改；修改已批准内容必须创建新的 Social Commit 和 Social PR。

## Initialization

Run from the project root:

```text
python .agents/skills/vibe-social/scripts/vibe_state.py init --project-name "Project name" --style casual-weibo
```

If the user has not chosen a style, use `casual-weibo`. Initialization is idempotent and must not overwrite existing state.

## Update checkpoint

`last_scanned_ref` records the Git ref covered by the most recent Social Commit. An update scans after that checkpoint. Working-tree changes may be considered, but the agent must describe them as uncommitted and use `WORKTREE` as the ending ref.

Do not advance the checkpoint when there are no meaningful, safe events.

## Editorial grouping

Group events when they share one reader-facing tension or outcome. Split when they require different audiences, hooks, or explanations. Prefer zero strong drafts over one empty status update.

Reject generic output such as “optimized the architecture” unless it is backed by a concrete problem, change, and user effect.
