#!/usr/bin/env bash
# Print `export` lines for a rollout's settings, for `eval`:
#   eval "$(scripts/rollout-env.sh rollouts/demo-hospital)"
# Reads rollout.env line by line (never `source`: it strips JSON quotes and expands `$`), and
# sets ROLLOUT_DIR to the directory so `frontdesk-api seed` / `rollout apply` find its data.
set -euo pipefail
dir="${1:?usage: rollout-env.sh <rollout directory>}"
dir="$(cd "$dir" && pwd)"
[[ -f "$dir/rollout.env" ]] || { echo "no rollout.env in $dir" >&2; exit 1; }
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "${line// }" || "$line" == \#* ]] && continue
  printf 'export %s=%q\n' "${line%%=*}" "${line#*=}"
done < "$dir/rollout.env"
printf 'export ROLLOUT_DIR=%q\n' "$dir"
