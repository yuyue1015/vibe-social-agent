# VibeSocial Agent project rules

## Goal

Build a project-level Codex Skill that turns software-development progress into privacy-reviewed, human-approved social content.

## Current phase

Keep the existing V0.1 editorial workflow unchanged: local state, Social Commits, draft directions, Social PR review, style configuration, approval, Writing Memory, and read-only performance learning. The independent `.agents/skills/weibo-publish/` Skill owns the separate Weibo external-write boundary.

Do not add publishing behavior to `vibe-social`, and do not implement comment ingestion, a web UI, a server, a database, multi-user support, or multi-platform support. Performance learning may collect only fields returned by the installed CLI and must remain read-only and descriptive until enough observations exist.

## Engineering rules

- Prefer clear standard-library code and explicit JSON contracts.
- Avoid frameworks, premature abstraction, and hidden state.
- Use the bundled state script for generated `.vibesocial` JSON.
- Keep raw diffs and secret-bearing inputs out of persistent social state.
- Keep approval separate from future publishing.
- Do not alter application code while executing the social workflow.
- `vibe-social` owns content and approval; `weibo-publish` owns external Weibo publishing.
- `APPROVED` is not `PUBLISHED`.
- External write operations require an explicit human publishing instruction.
- Performance Insights are reference signals only; they cannot override Writing CORE, factuality, the series plan, or approved-content boundaries.
- `development-story` may analyze coarse recent development traces into story candidates, but must not create a project knowledge base, persist raw diffs/source, modify Writing Memory, or publish.

## Safety rules

- Treat uncertain content as private.
- Never read `.env` or credential stores for social-content generation.
- Never store raw source code, tokens, private URLs, personal data, or unauthorized third-party content.
- External Weibo write actions are owned by `weibo-publish` and require a separate explicit human publishing instruction and final confirmation.
