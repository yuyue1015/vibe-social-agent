# Story Journey

Story Journey only helps choose public sharing rhythm. It is not a product roadmap, project-management system, project knowledge base, writing memory, or publishing workflow.

## Stages

### `origin`

The beginning: why the work started, the first problem, or the source of the idea.

### `discovery`

The problem became concrete: difficult data, an insufficient old method, complex rules, or the first unexpected obstacle.

### `prototype`

The first working result: a runnable version, the first successful simulation, or the first visible output.

### `refinement`

Ongoing improvement: bug fixes, algorithm adjustments, experience improvements, performance work, or architecture changes.

### `validation`

Evidence: user feedback, tests, comparisons, benchmark results, or real use.

### `release_growth`

After the core result is credible: new users, new features, community feedback, and extensions.

## Timing rules

- Prefer the next stage after the most recently published stage.
- Do not repeatedly publish the same stage or near-identical topic when a different stage is available.
- Do not jump to `refinement`, `validation`, or `release_growth` when there is no public origin/discovery/prototype context, unless a human explicitly chooses to do so.
- A candidate can be technically strong and still be a poor choice for the current public sequence.
- Only records with `status: PUBLISHED` count as published history. `APPROVED`, drafts, and unconfirmed historical examples do not advance the journey.
- Missing published history is reported as missing history; it is never inferred from the previous draft or from Writing Memory.

The runtime state stores only series name, stage/type/topic cadence, last published date, repeat-avoidance hints, and the next preferred stage. It must not store full post text, source code, raw diffs, or project plans.
