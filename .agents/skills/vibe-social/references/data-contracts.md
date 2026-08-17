# Data contracts

All generated state uses UTF-8 JSON under `.vibesocial/`.

## Development event input

```json
{
  "type": "rule_correction",
  "summary": "Recalibrated entry-level diagnosis",
  "problem": "The previous model overestimated new staff",
  "change": "Adjusted the public-facing capability model",
  "user_value": "Simulation results are more realistic",
  "evidence": ["Targeted tests pass"],
  "public_safe": true
}
```

Required: `type`, `summary`, `problem`, `change`, `user_value`, `public_safe`. `evidence` is optional and contains public-safe summaries, never paths or raw logs.

## Generated records

A Social Commit includes `id`, `status`, `title`, `created_at`, `from_ref`, `to_ref`, and immutable events. A Social PR includes `id`, `status`, `social_commit_id`, `title`, `direction`, `body`, timestamps, and revision number.

When a Social PR is approved, its final body is copied to the related Social Commit as `final_text`, with `approved_at`. The PR also retains `first_draft`, `revisions`, optional `series`/`series_number`, and a `learning` summary. Approval writes project-local memory under `.vibesocial/` but never publishes. `learning: []` is valid; `learning_status` may be `saved`, `no_new_preference`, or `failed`, and a learning failure must not undo `APPROVED`.

Learning input is a temporary JSON object or array with `rule_key`, `scope` (`GLOBAL_STYLE`, `SERIES_STYLE`, or `POST_SPECIFIC`), `inferred_rule`, `confidence`, and optional safe summaries for `original_text`, `original_sentence`, `user_feedback`, `final_text`, `replacement`, `target`, `tags`, `series`, and `series_number`. The state script derives `count` and `status` (`OBSERVED`, `REPEATED`, `CORE`) and appends the result to `feedback-log.md`.

Project-local writing memory is initialized from the Skill references:

```text
.vibesocial/
├── config.json
├── state.json
├── style-profile.md
├── social-commits/
│   └── sc-0001.json
└── social-prs/
    └── spr-0001.json
├── writing-style.md
├── anti-ai-patterns.md
├── approved-examples.md
├── feedback-log.md
└── series-state.md
```

Read-only performance learning adds:

- `performance-log.jsonl`: one record per published Social Commit, with only metrics actually returned by the live CLI schema.
- `performance-baseline.json`: counts, observed metric keys, and the observation/descriptive-comparison gate.
- `performance-insights.md`: Reach, Interaction, Conversation, Series Health, Timing, Format, and Content summaries.

Performance files are reference state. They never mutate Writing CORE, approved examples, or series planning automatically.

Platform preferences are separate from Writing Memory:

```text
.vibesocial/platform_preferences/weibo.json
```

This file may store the user's default Weibo tags. Tags are selected at the platform boundary and are not required in `final_text` or promoted into Writing Memory.

After the user manually publishes on a non-Weibo platform, `record-manual-distribution` may record only the platform name and timestamp. It performs no external call and does not add a platform adapter.

Development-story discovery writes only `.vibesocial/story-candidates.md`. Each candidate contains `event`, `event_type`, `source`, `technical_change`, `reader_angle`, `why_people_care`, `story_score`, `confidence`, and `publish_suggestion`. It contains coarse evidence and editorial leads, not raw source, diffs, full project documents, or approved social text.
