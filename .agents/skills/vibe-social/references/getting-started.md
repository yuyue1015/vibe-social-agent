# Getting started

Use this guide only during first-run onboarding. Keep user-facing wording and choices consistent with [interaction-flow.md](interaction-flow.md); lifecycle and state meanings remain in [workflow.md](workflow.md).

## Welcome and project choice

Explain that VibeSocial finds shareable material in development progress and creates drafts. It does not modify source code, initialize Git, upload source, or publish automatically.

Offer the existing choices:

1. New project, first VibeSocial setup.
2. Existing project with development history.
3. View the example flow.
4. Exit or pause where the current interaction flow permits.

Do not require the user to know script paths, Social Commit IDs, or internal state names.

## First setup route

1. Ask for the project directory and resolve it as the selected project root.
2. Run `scripts/scan_guard.py preflight` before any Git command. Apply the default project scope unless the user explicitly chooses the confirmed workspace scope.
3. Show the existing `.gitignore` choice before creating local records when `.vibesocial/` is not protected.
4. Initialize missing local state with `scripts/vibe_state.py init`.
5. Read memory context and the privacy policy before choosing a direction or inspecting project material.
6. Continue through scan → candidate selection → draft → review. The user-facing nodes must always show the current state, completed action, and next choices.

For an existing project, a first analysis may use historical Git and selected development documents only within the approved scan root. It must not persist raw source, raw diffs, secrets, or private content.
