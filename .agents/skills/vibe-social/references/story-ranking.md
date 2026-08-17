# Story ranking

Story ranking estimates reader value, not technical importance. A complex refactor can score lower than a small bug fix if the bug fix changes a user-visible result or action.

## Positive dimensions

### User impact

- `+3`: directly changes a user-visible result or action
- `+2`: the before/after difference should be visible
- `+1`: mainly valuable as a development-process note

### Turning point

- `+3`: failure, rework, or a changed understanding
- `+2`: a solution or direction was adjusted
- `+1`: ordinary iteration

### Explainability

- `+3`: an ordinary reader can understand it
- `+2`: it can be explained with a concrete analogy
- `+1`: it requires substantial technical background

### Specificity

- `+2`: a concrete number
- `+2`: a concrete case, user action, or user problem
- `+1`: a named module or visible area

## Deductions

- `-3`: pure file organization
- `-3`: dependency-only upgrade
- `-2`: variable renaming
- `-2`: refactoring with no identified user-visible effect

The implementation caps the result at `10/10` and floors it at `0/10`. Missing reader value, missing user impact, or missing public permission lowers confidence or publishability even when the code change is technically large.

## Interpretation

- `7–10`: strong candidate after factual and public-safety review
- `4–6`: candidate needs a concrete user effect, comparison, or validation
- `0–3`: usually not worth turning into a reader-facing story

Ranking never creates copy, never approves publication, never updates Writing Memory, and never overrides human review.
