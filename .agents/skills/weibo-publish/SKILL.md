---
name: weibo-publish
description: Publish an already APPROVED VibeSocial Social Commit to Weibo through the locally installed weibo-cli. Use only when the user explicitly requests 发布到微博, 发微博, 批准并发布, or invokes $weibo-publish for an approved draft; do not use for generic publish, npm publish/release, GitHub release, website deployment, or application releases.
---

# Weibo Publish

This Skill owns the external Weibo write boundary. It consumes an already `APPROVED` VibeSocial version and delegates all deterministic checks and writes to the bundled `scripts/weibo_publish.py` adapter.

## Trigger and authorization

Run only for explicit Weibo publishing intent: `发布到微博`, `发微博`, `批准并发布`, or an equivalent `$weibo-publish` request naming an approved VibeSocial draft. Generic approval such as `批准`, `可以`, or `保存` is not publishing authorization. Neither are npm/GitHub releases, deployments, or other generic publish requests.

The source Social Commit must be exactly `APPROVED`. `APPROVED` is not `PUBLISHED`, and this Skill must not alter approved content or bypass the approval boundary. A user must see the final transport preview and explicitly confirm the external write.

## Safe entry and exit

1. Hand off only after local approval and the user’s explicit Weibo intent.
2. Invoke the bundled adapter; do not hand-construct `weibo-cli` commands or call its write commands directly.
3. Let the adapter discover the installed CLI schema, preserve the approved text, and enforce the publish state/idempotence contract.
4. Keep every user-visible result aligned with [interaction-flow.md](../vibe-social/references/interaction-flow.md): show current state, completed action, and next choices.

The publish operation has four persisted outcomes:

- `PUBLISHED`: remote text was verified and local state was committed; never publish this version again.
- `FAILED_RETRYABLE`: the final remote write was confirmed not to have run; the user may return to the final preview.
- `PUBLISHING`: a write attempt is in progress or was interrupted; reconcile before retrying.
- `UNKNOWN_REQUIRES_RECONCILIATION`: the remote result is ambiguous; never blind-retry. Reconcile it first.

After a remote success, the adapter records the remote ID, verifies the complete transport text, writes the Social Commit as `PUBLISHED`, and then idempotently repairs or appends the published log. A missing or failed readback remains unknown.

## Reconcile

Reconcile never calls `statuses update`, `statuses upload_url_text`, or any other external write. It may read the remote post, verify the complete text, repair local state, and complete an idempotent published-log entry. Existing `remote_id` is preferred; otherwise require the user-provided Weibo ID. A verified match becomes `PUBLISHED`; an inconclusive readback stays `UNKNOWN_REQUIRES_RECONCILIATION`.

Only when the user has independently confirmed that the ambiguous remote post was deleted may the adapter run `reconcile --confirm-remote-deleted`. This records that explicit local confirmation, restores the still-approved commit to `APPROVED`, and permits a fresh, separately confirmed publish attempt. It must not infer deletion from a missing readback.

For Windows shell behavior and long-text ANSI-C transport diagnostics, see [references/windows-bash-environment.md](references/windows-bash-environment.md). CLI schema details, quoting rules, doctor diagnostics, command parameters, and JSON examples belong to the adapter and its tests, not to this always-loaded contract. Do not modify application code, Story logic, Writing Memory, scan boundaries, or the approved draft text here.
