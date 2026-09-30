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
    # Existing Claude safety greps, corrected for grep -E.
    # Build patterns from fragments so this script does not self-match when
    # the heuristic scan runs against its own added lines.
    p_akia='AKIA[0-9A-Z]{16}'
    p_asia='ASIA[0-9A-Z]{16}'
    p_pem='-----BEGIN (RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----'
    p_aws_name='aws_secret_access_key'
    p_gh='gh[pousr]_[A-Za-z0-9_]{20,}'
    pattern1="${p_akia}|${p_asia}|${p_pem}|${p_aws_name}|${p_gh}"
    p_assign_aws='(aws_secret_access_key|secret_access_key)[[:space:]]*[=:][[:space:]]*[^[:space:]]{8,}'
    p_assign_pw='password[[:space:]]*[=:][[:space:]]*[^[:space:]{]{6,}'
    p_assign_tok='token[[:space:]]*[=:][[:space:]]*[^[:space:]{]{16,}'
    pattern2="${p_assign_aws}|${p_assign_pw}|${p_assign_tok}"
    # Ignore hits that are only this gate's own pattern definitions.
    # Note: grep -n prefixes "N:", so anchors must allow that before the "+".
    filter_self() {
      /usr/bin/grep -inE "$1" "${added}" | /usr/bin/grep -Ev 'scripts/pr-safety-check\.sh|^[0-9]+:\+[ ]*p_(akia|asia|pem|aws_name|gh|assign_)|^[0-9]+:\+[ ]*pattern[12]=' || true
    }
    hits=0
    strict_hits="$(filter_self "${pattern1}")"
    if [ -n "${strict_hits}" ]; then
      echo "Heuristic secret pattern match (strict):" >&2
      echo "${strict_hits}" | head -50 >&2 || true
      hits=1
    fi
    assign_hits="$(filter_self "${pattern2}")"
    if [ -n "${assign_hits}" ]; then
      echo "Heuristic secret pattern match (assignment):" >&2
      echo "${assign_hits}" | head -50 >&2 || true
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
