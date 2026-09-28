#!/usr/bin/env bash
# Cursor beforeShellExecution: block `gh pr create` until PR safety checks pass.
set -euo pipefail

input="$(cat)"
command="$(printf '%s' "${input}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("command",""))' 2>/dev/null || true)"

# Only gate PR creation (not view/list/diff)
if ! printf '%s' "${command}" | grep -Eq '(^|[[:space:]]|[;&|])gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)'; then
  printf '%s\n' '{"permission":"allow"}'
  exit 0
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
script="${ROOT}/scripts/pr-safety-check.sh"
if [ ! -x "${script}" ]; then
  printf '%s\n' '{"permission":"deny","user_message":"PR blocked: scripts/pr-safety-check.sh missing or not executable.","agent_message":"Install/configure rh-pre-commit and ensure scripts/pr-safety-check.sh is executable before gh pr create."}'
  exit 0
fi

err_file="$(mktemp)"
out_file="$(mktemp)"
if ! "${script}" >"${out_file}" 2>"${err_file}"; then
  python3 - "${err_file}" <<'PY'
import json, sys
path = sys.argv[1]
reason = open(path, "r", errors="replace").read()[-1500:]
print(json.dumps({
  "permission": "deny",
  "user_message": "PR creation blocked by PR safety checks (rh-pre-commit + secret scan).",
  "agent_message": "gh pr create denied. Fix findings, then retry. Output:\n" + reason,
}))
PY
  rm -f "${err_file}" "${out_file}"
  exit 0
fi
rm -f "${err_file}" "${out_file}"
printf '%s\n' '{"permission":"allow"}'
exit 0
