#!/usr/bin/env bash
# Shared PR safety gate: rh-pre-commit (via pre-commit) + heuristic secret scan.
# Used by Cursor/Claude hooks and by agents before `gh pr create`.
# Compatible with macOS /bin/bash 3.2.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:${PATH}"

die() {
  echo "PR safety check FAILED: $*" >&2
  exit 1
}

ok() {
  echo "PR safety check: $*"
}

# --- 1) Red Hat rh-pre-commit (and any other configured hooks) ---
if [ -f .pre-commit-config.yaml ]; then
  if ! command -v pre-commit >/dev/null 2>&1; then
    die "pre-commit not on PATH (expected ~/.local/bin/pre-commit). Install: uv tool install pre-commit"
  fi
  ok "running pre-commit on changed files vs upstream..."
  base=""
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    base="$(git merge-base HEAD origin/main 2>/dev/null || true)"
  elif git rev-parse --verify main >/dev/null 2>&1; then
    base="$(git merge-base HEAD main 2>/dev/null || true)"
  fi

  file_list="$(mktemp)"
  {
    if [ -n "${base}" ]; then
      git diff --name-only --diff-filter=ACMR "${base}...HEAD" || true
    fi
    git diff --name-only --diff-filter=ACMR || true
    git diff --cached --name-only --diff-filter=ACMR || true
  } | awk 'NF && !seen[$0]++' >"${file_list}"

  if [ -s "${file_list}" ]; then
    # shellcheck disable=SC2046
    pre-commit run --files $(cat "${file_list}") || {
      rm -f "${file_list}"
      die "pre-commit hooks failed (includes rh-pre-commit secret scan)"
    }
  else
    pre-commit run || {
      rm -f "${file_list}"
      die "pre-commit hooks failed (includes rh-pre-commit secret scan)"
    }
  fi
  rm -f "${file_list}"
  ok "pre-commit passed"
else
  ok "no .pre-commit-config.yaml — skipping pre-commit"
fi

# --- 2) Extra heuristic secret scan on the PR diff (existing Claude safety greps) ---
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
diff_file="${tmpdir}/pr.diff"

base=""
if git rev-parse --verify origin/main >/dev/null 2>&1; then
  base="$(git merge-base HEAD origin/main 2>/dev/null || true)"
elif git rev-parse --verify main >/dev/null 2>&1; then
  base="$(git merge-base HEAD main 2>/dev/null || true)"
fi

{
  if [ -n "${base}" ]; then
    git diff "${base}...HEAD" || true
  fi
  git diff || true
  git diff --cached || true
} >"${diff_file}"

if [ ! -s "${diff_file}" ]; then
  ok "no diff to secret-scan"
else
  ok "running heuristic secret scan on added diff lines..."
  # Only added lines (avoid doc noise). Use ERE grouping — NOT BRE \( \).
  added="${tmpdir}/added.diff"
  /usr/bin/grep -E '^\+' "${diff_file}" | /usr/bin/grep -Ev '^\+\+\+' >"${added}" || true
  if [ ! -s "${added}" ]; then
    ok "no added lines to secret-scan"
  else
    # Existing Claude safety greps, corrected for grep -E:
    # AWS key ids, PEM/SSH blocks, gh tokens, aws secret key names, password/token assignments.
    pattern1='AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN (RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----|aws_secret_access_key|gh[pousr]_[A-Za-z0-9_]{20,}'
    pattern2='(aws_secret_access_key|secret_access_key)[[:space:]]*[=:][[:space:]]*[^[:space:]]{8,}|password[[:space:]]*[=:][[:space:]]*[^[:space:]{]{6,}|token[[:space:]]*[=:][[:space:]]*[^[:space:]{]{16,}'
    hits=0
    if /usr/bin/grep -inE "${pattern1}" "${added}" >/dev/null 2>&1; then
      echo "Heuristic secret pattern match (strict):" >&2
      /usr/bin/grep -inE "${pattern1}" "${added}" | head -50 >&2 || true
      hits=1
    fi
    if /usr/bin/grep -inE "${pattern2}" "${added}" >/dev/null 2>&1; then
      echo "Heuristic secret pattern match (assignment):" >&2
      /usr/bin/grep -inE "${pattern2}" "${added}" | head -50 >&2 || true
      hits=1
    fi
    if [ "${hits}" -ne 0 ]; then
      die "possible secrets in diff — remove/redact before opening a PR"
    fi
    ok "heuristic secret scan clean"
  fi
fi

ok "all checks passed — safe to open PR (still run security-review / bugbot when asked)"
exit 0
