#!/usr/bin/env bash
# Claude Code PreToolUse: deny Bash `gh pr create` until PR safety checks pass.
set -euo pipefail

input="$(cat)"
command="$(printf '%s' "${input}" | python3 -c 'import json,sys
d=json.load(sys.stdin)
print((d.get("tool_input") or d.get("input") or {}).get("command",""))' 2>/dev/null || true)"

if ! printf '%s' "${command}" | grep -Eq '(^|[[:space:]]|[;&|])gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)'; then
  exit 0
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
script="${ROOT}/scripts/pr-safety-check.sh"
err_file="$(mktemp)"

if [ ! -x "${script}" ]; then
  python3 -c 'import json; print(json.dumps({"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"scripts/pr-safety-check.sh missing or not executable"},"systemMessage":"gh pr create blocked: restore scripts/pr-safety-check.sh and chmod +x it."}))'
  rm -f "${err_file}"
  exit 0
fi

if ! "${script}" >/dev/null 2>"${err_file}"; then
  reason="$(tail -c 1500 "${err_file}" 2>/dev/null || true)"
  rm -f "${err_file}"
  python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"PR safety checks failed"},"systemMessage":sys.argv[1]}))' \
    "gh pr create blocked by PR safety checks (rh-pre-commit + secret scan). Fix findings and retry. Output:
${reason}"
  exit 0
fi

rm -f "${err_file}"
python3 -c 'import json; print(json.dumps({"hookSpecificOutput":{"permissionDecision":"allow"}}))'
exit 0
