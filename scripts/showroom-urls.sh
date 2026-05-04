#!/usr/bin/env bash
#
# Discover showroom URLs for a Babylon workshop GUID or ResourceClaim (provision) GUID.
#
# Prerequisites:
#   - oc CLI logged in to the Babylon cluster
#   - jq installed
#
# Usage:
#   showroom-urls.sh -w <workshop-guid>         # search by workshop GUID
#   showroom-urls.sh -r <rc-guid>               # search by ResourceClaim provision GUID
#   showroom-urls.sh -w <guid> -n <namespace>   # limit workshop search to a namespace
#
set -euo pipefail

WORKSHOP_GUID=""
RC_GUID=""
NAMESPACE=""

usage() {
    cat <<'EOF'
Usage: showroom-urls.sh [OPTIONS]

Discover showroom / lab UI URLs from Babylon ResourceClaims.

Options:
  -w GUID   Workshop GUID  (babylon.gpte.redhat.com/workshop-id label)
  -r GUID   ResourceClaim provision GUID  (job_vars.guid / provision_data.guid)
  -n NS     Restrict search to a single namespace (optional, workshop mode only)
  -h        Show this help

At least one of -w or -r is required.

Examples:
  showroom-urls.sh -w abc-12345
  showroom-urls.sh -r xyz-67890
  showroom-urls.sh -w abc-12345 -n my-namespace
EOF
    exit 1
}

while getopts "w:r:n:h" opt; do
    case "$opt" in
        w) WORKSHOP_GUID="$OPTARG" ;;
        r) RC_GUID="$OPTARG" ;;
        n) NAMESPACE="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

if [[ -z "$WORKSHOP_GUID" && -z "$RC_GUID" ]]; then
    echo "Error: provide at least -w <workshop-guid> or -r <rc-guid>" >&2
    echo "" >&2
    usage
fi

for cmd in oc jq; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: '$cmd' is required but not found in PATH" >&2
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# jq filter: extract showroom URLs from a single ResourceClaim JSON document.
# Mirrors soundcheck/babylon_service.py extract_showroom_urls().
# ---------------------------------------------------------------------------
read -r -d '' EXTRACT_URLS <<'JQEOF' || true
def url_keys: ["showroom_primary_view_url","bookbag_url","lab_ui_url","labUserInterfaceUrl"];

.metadata.name as $rc |
(.metadata.annotations // {}) as $ann |

[
  # 1) From AnarchySubject provision_data
  ( .status.resources[]?
    | select(.state.kind == "AnarchySubject")
    | .state.spec.vars.provision_data // {}
    | . as $pd
    | (
        ([url_keys[] as $k | $pd[$k] | select(. != null and . != "")] | .[0]) as $url
        | select($url != null)
        | {url: $url, label: $rc}
      ),
      (
        ($pd.users // {}) | to_entries[] |
        .key as $user |
        (.value | select(type == "object")) as $ud |
        ([url_keys[] as $k | $ud[$k] | select(. != null and . != "")] | .[0]) as $url
        | select($url != null)
        | {url: $url, label: "\($rc)/\($user)"}
      )
  ),

  # 2) Single annotation
  ( $ann["babylon.gpte.redhat.com/labUserInterfaceUrl"]
    | select(. != null and . != "")
    | {url: ., label: "\($rc) (annotation)"}
  ),

  # 3) Multi-user annotation (JSON object)
  ( $ann["babylon.gpte.redhat.com/labUserInterfaceUrls"]
    | select(. != null and . != "")
    | fromjson | to_entries[]
    | select(.value != null and .value != "")
    | {url: .value, label: "\($rc)/\(.key) (annotation)"}
  )
]

# Deduplicate by url, preserving first occurrence
| reduce .[] as $x ({}; if .[$x.url] then . else .[$x.url] = $x end)
| [to_entries[] | .value]
| sort_by(.label)[]
| "\(.label)\t\(.url)"
JQEOF

# ---------------------------------------------------------------------------
# Workshop GUID path: list Workshops by label, then GET each ResourceClaim.
# ---------------------------------------------------------------------------
search_by_workshop_guid() {
    local guid="$1"
    local ns_args=()
    if [[ -n "$NAMESPACE" ]]; then
        ns_args=(-n "$NAMESPACE")
    else
        ns_args=(-A)
    fi

    local ws_json
    ws_json=$(oc get workshops.babylon.gpte.redhat.com "${ns_args[@]}" \
        -l "babylon.gpte.redhat.com/workshop-id=${guid}" \
        -o json 2>/dev/null) || {
        echo "Error: failed to list Workshops (check oc login / permissions)" >&2
        return 1
    }

    local count
    count=$(echo "$ws_json" | jq '.items | length')

    if [[ "$count" -eq 0 ]]; then
        echo "No Workshops found for workshop GUID '${guid}'" >&2
        return 1
    fi

    echo "Found ${count} Workshop(s) for GUID '${guid}'" >&2

    echo "$ws_json" | jq -r '
        .items[] |
        .metadata.namespace as $ns |
        .metadata.name as $ws |
        (.status.resourceClaims // {}) | keys[] |
        "\($ns)\t\(.)\t\($ws)"
    ' | while IFS=$'\t' read -r ns rc_name ws_name; do
        echo "  Workshop: ${ws_name}  ->  ResourceClaim: ${ns}/${rc_name}" >&2
        oc get resourceclaims.poolboy.gpte.redhat.com "$rc_name" -n "$ns" -o json 2>/dev/null \
            | jq -r "$EXTRACT_URLS" 2>/dev/null || {
            echo "  Warning: could not fetch ResourceClaim ${ns}/${rc_name}" >&2
        }
    done
}

# ---------------------------------------------------------------------------
# RC GUID path: list all ResourceClaims, filter by provision GUID.
# Mirrors babylon_service._search_cluster_for_rc_guid().
# NOTE: can be slow on large clusters — lists every ResourceClaim.
# ---------------------------------------------------------------------------
search_by_rc_guid() {
    local guid="$1"

    echo "Searching all ResourceClaims for provision GUID '${guid}' (this may take a moment)..." >&2

    local all_rcs
    all_rcs=$(oc get resourceclaims.poolboy.gpte.redhat.com -A -o json 2>/dev/null) || {
        echo "Error: failed to list ResourceClaims (check oc login / permissions)" >&2
        return 1
    }

    local matched
    matched=$(echo "$all_rcs" | jq -c --arg guid "$guid" '
        [.items[] | select(
            any(.status.resources[]?;
                .state != null and (
                    .state.spec.vars.job_vars.guid == $guid or
                    .state.spec.vars.provision_data.guid == $guid
                )
            )
        )]
    ')

    local count
    count=$(echo "$matched" | jq 'length')

    if [[ "$count" -eq 0 ]]; then
        echo "No ResourceClaims found matching provision GUID '${guid}'" >&2
        return 1
    fi

    echo "Found ${count} matching ResourceClaim(s)" >&2

    echo "$matched" | jq -c '.[]' | while read -r rc_json; do
        echo "$rc_json" | jq -r "$EXTRACT_URLS" 2>/dev/null || true
    done
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print_results() {
    local results="$1"
    if [[ -n "$results" ]]; then
        echo ""
        printf "%-40s %s\n" "LABEL" "URL"
        printf "%-40s %s\n" "-----" "---"
        echo "$results" | while IFS=$'\t' read -r label url; do
            printf "%-40s %s\n" "$label" "$url"
        done
        return 0
    fi
    return 1
}

found_any=false

if [[ -n "$WORKSHOP_GUID" ]]; then
    results=$(search_by_workshop_guid "$WORKSHOP_GUID" 2> >(cat >&2)) || true
    if print_results "$results"; then
        found_any=true
    fi
fi

if [[ -n "$RC_GUID" ]]; then
    results=$(search_by_rc_guid "$RC_GUID" 2> >(cat >&2)) || true
    if print_results "$results"; then
        found_any=true
    fi
fi

if [[ "$found_any" == false ]]; then
    echo "" >&2
    echo "No showroom URLs found." >&2
    exit 1
fi
