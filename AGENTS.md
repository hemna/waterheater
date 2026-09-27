# AGENTS.md — Waterheater Project

## Linting

- Before committing any code, run `uvx ruff check` on all modified Python files and fix any errors.
- Do not commit or push code that fails linting. CI runs ruff and will reject it.

## Conventions

- Prefer simple solutions.
- Avoid code duplication — check existing codebase before adding similar functionality.
- Only make changes that are required or well understood and related to the change being requested.
- When fixing a bug, exhaust existing implementation options before introducing new patterns. If you do introduce something new, remove the old implementation.
- Keep the codebase clean and organized.
- Avoid files over 200-300 lines — refactor at that point.
- Mocking is only for tests, never for dev or prod.
- Never overwrite .env without asking first.

## Deployment

- App runs on Raspberry Pi Zero 2 W at waterheater.hemna.com (192.168.0.70).
- SSH: `ssh -i ~/.ssh/id_rsa waboring@waterheater.hemna.com`
- App path on Pi: `/home/waboring/waterheater/`
- Systemd service: `waterheater.service`
- Git remote on Pi: `forgejo` → http://git.hemna.com/hemna/waterheater.git

## Git Workflow

- Never push directly to master. All changes go through feature/ or fix/ branches via PR.
- CI must pass before merge.
