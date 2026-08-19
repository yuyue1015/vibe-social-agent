---
name: vibe-social
description: Turn VibeSocial development progress into privacy-reviewed, human-approved drafts, revisions, and publish handoffs. Use only for VibeSocial progress scanning, story or style direction, draft generation or revision, create-revision, approval, or a publish handoff; do not use for ordinary code summaries, code style, product direction, deployment, npm/GitHub release, or other generic publishing requests.
---

# VibeSocial

VibeSocial discovers public-safe material from a local software project, turns selected facts into reviewable Social Commits and Social PRs, and learns stable writing preferences from approved revisions. It stops at local approval; the separate `weibo-publish` Skill owns external Weibo writes.

## Core route and ownership

- Keep the existing user flow: development records → material selection → draft → natural-language revision → Pull → Approve → publish handoff or save.
- `APPROVED` is not `PUBLISHED`. Approval never publishes.
- An `APPROVED` version is immutable. To change it, run `vibe_state.py create-revision`; revise the new Social PR instead.
- `PULL` is a user action that submits the current edit, not a persisted JSON status.
- When the current PR is `DRAFT`, ordinary wording edits have **LOW freedom** and one deterministic route: call `vibe_state.py draft-edit` exactly once with `--replace-old` and `--replace-new`. `draft-edit` finds the only current DRAFT, reads the complete `title`/`body`, applies the exact replacement, writes one revision, and returns the complete draft. Consume `full_draft.title`, `full_draft.body`, `current_state`, and `next` directly; do not choose another implementation.
- Ordinary DRAFT edits include changing one sentence, changing the title, deleting one sentence, shortening, or adjusting tone/wording. They must not call `revise-pr`, `--help`, `scan_guard.py`, `story_detect.py`, `story_generate.py`, `story_aggregate.py`, `performance.py`, Story Ranking, Publish Readiness, or any project/Git full scan.
- A changed number or explicit fact-verification request requires evidence before the edit is saved; one wording edit must not trigger Writing Memory rescan or global learning.
- Do not modify business code, invent facts, hand-edit generated JSON, or call Weibo write commands from this Skill.
- Before any Git or project scan, use `scan_guard.py preflight` and the user-approved root/scope. Read the privacy policy before inspecting project material.

## Progressive disclosure route

Load only the references required for the current action; do not load the complete reference set by default.

| Action | Required context |
| --- | --- |
| First start | [getting-started.md](references/getting-started.md), [workflow.md](references/workflow.md), [interaction-flow.md](references/interaction-flow.md) |
| Existing project scan | [scan-boundary.md](references/scan-boundary.md), [privacy-policy.md](references/privacy-policy.md), [development-story.md](references/development-story.md) |
| Choose a Story | [development-story.md](references/development-story.md), [story-ranking.md](references/story-ranking.md), [story-journey.md](references/story-journey.md) |
| Story aggregation | [story-aggregation.md](references/story-aggregation.md) only when several records may form a larger phase |
| 下一篇 | `.vibesocial/series-state.md`, [series-state.md](references/series-state.md), [writing-memory.md](references/writing-memory.md), [workflow.md](references/workflow.md) |
| DRAFT Fast Edit | **No references.** For one ordinary DRAFT wording/title replacement, call `vibe_state.py draft-edit` exactly once, then render only `full_draft.title`, `full_draft.body`, `current_state`, and `next`. |
| Other Revision / Fact Check | Read [workflow.md](references/workflow.md), [interaction-flow.md](references/interaction-flow.md), and [data-contracts.md](references/data-contracts.md) only when creating a revision after `APPROVED`, verifying a fact/changed number, or handling a non-ordinary edit. |
| Approve | [interaction-flow.md](references/interaction-flow.md), [data-contracts.md](references/data-contracts.md), [writing-memory.md](references/writing-memory.md) when learning is needed |
| create-revision | [workflow.md](references/workflow.md), [interaction-flow.md](references/interaction-flow.md), [data-contracts.md](references/data-contracts.md) |
| Publish handoff | [weibo-publish](../weibo-publish/SKILL.md) |
| Performance Learning | [performance-learning.md](references/performance-learning.md), [data-contracts.md](references/data-contracts.md) |

## Deterministic entry points

Use the bundled scripts for state, scanning, bounded subprocesses, and repeatable transformations. Do not recreate their logic as free-form instructions.

- `scripts/scan_guard.py`: preflight, approved scan root, and resource boundary.
- `scripts/vibe_state.py`: initialize, inspect, commit, create PR/revision, `draft-edit`, approve, memory context, and safe state writes.
- `scripts/story_detect.py`, `story_generate.py`, `story_aggregate.py`: candidate detection, draft materialization, and optional aggregation.
- `scripts/performance.py`: read-only CLI schema discovery, snapshots, and descriptive analysis.

## Freedom level

- **LOW:** DRAFT title/wording edits, Story Detect, Approve, create-revision, Publish handoff, Reconcile, state read/write, path safety, and Performance CLI invocation.
- **MEDIUM:** Story Ranking, Story Journey selection, Story Generate, and Writing Memory semantic judgment.

Keep deterministic operations in scripts. Do not turn low-freedom operations into long natural-language procedures.

## Single sources of truth

- [workflow.md](references/workflow.md): states, actions, and lifecycle.
- [interaction-flow.md](references/interaction-flow.md): user-visible wording, choices, and next menus.
- [data-contracts.md](references/data-contracts.md): JSON contracts and field semantics.
- [privacy-policy.md](references/privacy-policy.md): privacy and content boundary.
- [development-story.md](references/development-story.md): Story Candidate and content boundary.
- [story-ranking.md](references/story-ranking.md): ranking rules.
- [performance-learning.md](references/performance-learning.md): read-only performance rules.
- [writing-memory.md](references/writing-memory.md): learning and memory rules.
- [weibo-publish](../weibo-publish/SKILL.md): external Weibo ownership and safety entry.

Other references are templates or focused, on-demand material. When a rule changes, update its authority and keep this file as a short route, not a duplicate specification.
