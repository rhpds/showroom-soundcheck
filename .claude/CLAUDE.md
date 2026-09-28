# Showroom Soundcheck — Claude notes

Read [AGENTS.md](../AGENTS.md) for architecture rules.

## PR safety

Before `gh pr create`:

1. Run `make pr-safety` / `./scripts/pr-safety-check.sh` (rh-pre-commit + heuristic secret scan).
2. Do not open a PR if it fails. The PreToolUse hook in `.claude/settings.json` also blocks `gh pr create` until it passes.
3. First-time rh-pre-commit auth: use the exact cached Python path from the hook with `-m rh_gitleaks login` (never system Python).
4. Security-review / Bugbot remain available when the user asks — they complement rh-pre-commit.
