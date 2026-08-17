# Writing Memory

Writing Memory learns stable editorial form from safe user feedback and approved drafts. It never supplies facts, product claims, names, dates, or metrics.

## Scope and precedence

- `GLOBAL_STYLE` contains stable cross-series preferences.
- `SERIES_STYLE` applies to one series.
- `POST_SPECIFIC` applies to one draft and cannot overwrite a CORE global rule.
- One observation is `OBSERVED`; a second matching `rule_key` is `REPEATED`; an explicit, repeatedly confirmed preference can become `CORE`.

When rules conflict, keep the conflict visible, let the latest explicit request win for the current draft, and preserve the older CORE rule until it is deliberately changed.

For Story Generate, apply constraints in this order: an explicit local or `POST_SPECIFIC` instruction for the current draft, then `REPEATED`, then `CORE` defaults. Memory constrains form and emphasis; it never adds facts, numbers, user results, or domain context.

## Safe inputs and operations

Learn rhythm, sentence length, openings, structure, technical density, concrete-material preference, emoji habits, and disliked phrases. Store concise safe feedback summaries, never raw private conversation, source, secrets, or copied factual claims.

Use `scripts/vibe_state.py memory-context` before drafting, `backfill-memory` only for eligible legacy approved drafts, and the approval path for best-effort learning. An empty learning result is valid (`no_new_preference`) and must not block approval. Approved examples contain only final approved text.

Project-local files include `writing-style.md`, `anti-ai-patterns.md`, `approved-examples.md`, `feedback-log.md`, and `series-state.md`; their runtime data lives under `.vibesocial/`. The 50-post plan and current number are read before “下一篇”.
