# Development story detection

`story_detect.py` is a discovery layer between development changes and Social Commit drafting. It identifies possible stories; it does not write a post, create a Social Commit, update Writing Memory, or publish externally.

## What it looks for

- New features or visible capability changes
- Bug fixes and failed attempts
- Architecture or performance adjustments
- User feedback and product-facing decisions
- First successful runs, tests, or usable milestones
- Important decisions that are safe to discuss publicly

The detector uses recent commit subjects, dates, coarse changed-area categories, and selected summary/test/feedback filenames. It may read a bounded summary header to classify an event, but does not persist raw diffs, source code, full documents, absolute paths, or project knowledge. A generated candidate is an editorial lead, not a verified fact.

Candidates are ranked using [story-ranking.md](story-ranking.md). The score measures reader value: user impact, turning point, explainability, and concrete detail, with deductions for file-only work, dependency-only changes, renames, and invisible refactors.

## Public-safety gate

Candidates with credential-shaped paths, private configuration, customer or personal data, generated exports, binary archives, unpublished roadmaps, or ambiguous ownership are marked `待人工确认` or withheld. The detector never treats a safe-looking commit subject as permission to publish.

Every candidate explains:

- what the development trace appears to show;
- why an ordinary reader might care, when a user-visible effect is supported;
- how to translate the technical change into plain language;
- a platform direction, if appropriate;
- a title direction, without generating the final social copy.
- an event type from the controlled set: `feature`, `bug_fix`, `architecture_change`, `performance`, `ux_change`, `failed_attempt`, `milestone`, `user_feedback`, or `experiment`;
- a score, confidence, and publish suggestion that still require human review.

## Boundaries

Story candidates are not Writing Memory. They do not become approved examples or style rules, and they are not performance insights. A human must verify the underlying change, public-safety status, and factual wording before it can become a Social Commit.
