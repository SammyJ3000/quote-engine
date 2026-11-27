# Build process records

These are the working documents from a staged, agent driven build that I briefed and reviewed.

- `2026-08-20-engine-plan.md` is the step by step implementation plan for Plan 1, the deterministic engine. This is the plan the code in this repo was built from.
- `2026-08-21-followups.md` collects what the code reviews during Plan 1 found and deliberately left undone, ranked by value.
- `2026-08-21-webapp-plan.md` is the implementation plan for Plan 2, the web app and LLM intake. It has not been carried out yet.

Each plan breaks the work into small tasks: a failing test first, the code to make it pass, then a commit. The agents worked through the tasks one at a time, the code was reviewed as it landed (sixteen reviews during Plan 1), and the follow ups file is what those reviews turned up.

File paths inside these plans reflect the layout of the working copy at the time (`planning/`, `logs/`). In this repo the design specs and research live one level up in `docs/`.
