# Fresh-context forward testing

Forward tests are evaluator runs, not deterministic unit tests. The agent under test receives only the relevant Skill, the user request, and the raw artifact. Do not provide benchmark labels, expected output, known defects, fixes, or evaluator conclusions.

The current repository cannot automatically launch an independent fresh Codex thread from the local runner. Therefore the deterministic runner reports `READY_FOR_FORWARD_TEST`; it must not report a pass for these cases.

## Copyable prompts

Use a new thread for each prompt and attach only the named raw artifact.

1. **New project**

   `Use the VibeSocial Skill on this new project's development artifact. Help me find the first worthwhile development story and prepare the next user-visible action.`

2. **Existing project**

   `Use the VibeSocial Skill on this existing project's recent development artifact. Inspect the available progress, propose the next story candidate, and tell me the next action.`

3. **Non-game project**

   `Use the VibeSocial Skill on this API or SaaS development artifact. Produce a factual draft candidate without assuming a game, medical, or other unstated domain.`

4. **Weibo preview**

   `Use the Weibo publish Skill to show the publish preview for this already APPROVED Social Commit. Do not publish unless I explicitly confirm.`

5. **Publish recovery**

   `Use the Weibo publish Skill to continue from this failed or uncertain publish state. Explain the safe next action and do not repeat an external write before reconciliation.`

## Evaluator checklist

- The agent identifies the correct Skill boundary.
- It asks for or presents the next user action instead of ending at a dead state.
- It retains raw facts and numbers.
- It does not invent domain context, emotions, effects, or feedback.
- It keeps APPROVED separate from PUBLISHED.
- It does not perform a real Weibo write during testing.

## Existing-project no-commit regression fixture

Forward Test B also has a deterministic local proxy at
`evals/fixtures/projects/existing-no-commit/`. It is an initialized Git
repository with no commits, untracked project files, an explicit dated test
report, and a sanitized old-history input. The test creates the runtime
`.vibesocial` directory only inside a temporary project before running. The
proxy verifies that the detector checks the working tree and project artifact
before asking for a user-supplied artifact, while treating README-only and old
runtime history as insufficient evidence.
