#!/usr/bin/env bash
# Pings every service listed in a JSON config and reports the results.
# Usage: scripts/ping.sh [config.json]
#
# Config sources (first match wins):
#   1. $SERVICES_JSON env var (e.g. from a repo secret, for private URLs)
#   2. the file passed as $1 (default: services.json)
#
# Each entry: { "name", "url", "method"?, "expected_status"?, "timeout"? }

set -uo pipefail

CONFIG_FILE="${1:-services.json}"
DEFAULT_TIMEOUT="${PING_TIMEOUT:-30}"
RETRIES="${PING_RETRIES:-2}"

if [[ -n "${SERVICES_JSON:-}" ]]; then
  config="$SERVICES_JSON"
  echo "Using services from SERVICES_JSON secret"
else
  config="$(cat "$CONFIG_FILE")"
  echo "Using services from $CONFIG_FILE"
fi

if ! echo "$config" | jq -e 'type == "array"' >/dev/null; then
  echo "::error::Service config must be a JSON array"
  exit 1
fi

failures=0
summary="| Service | Status | Expected | Time (s) | Result |\n|---|---|---|---|---|\n"

while IFS= read -r svc; do
  name=$(jq -r '.name // .url' <<<"$svc")
  url=$(jq -r '.url' <<<"$svc")
  method=$(jq -r '.method // "GET"' <<<"$svc")
  expected=$(jq -r '.expected_status // 200' <<<"$svc")
  timeout=$(jq -r ".timeout // $DEFAULT_TIMEOUT" <<<"$svc")

  [[ -n "${SERVICES_JSON:-}" && -n "${GITHUB_ACTIONS:-}" ]] && echo "::add-mask::$url"

  out=$(curl -sS -o /dev/null -X "$method" \
    --max-time "$timeout" \
    --retry "$RETRIES" --retry-delay 5 --retry-all-errors \
    -A "pinger-licking-good/1.0" \
    -w '%{http_code} %{time_total}' \
    "$url" 2>/dev/null)
  status=${out%% *}
  time=${out##* }
  [[ -z "$status" ]] && status="000"

  if [[ "$status" == "$expected" ]]; then
    result="✅ up"
    echo "✅ $name -> $status (${time}s)"
  else
    result="❌ down"
    failures=$((failures + 1))
    echo "::error title=$name is down::Got HTTP $status, expected $expected"
  fi
  summary+="| $name | $status | $expected | $time | $result |\n"
done < <(echo "$config" | jq -c '.[]')

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf "## Ping results\n\n%b" "$summary" >>"$GITHUB_STEP_SUMMARY"
fi

if (( failures > 0 )); then
  echo "$failures service(s) failed"
  exit 1
fi
echo "All services are up"
