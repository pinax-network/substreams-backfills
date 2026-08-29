#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_dir/uniswap-v3/npm-observation-plan"
destination=${1:-}
python_bin=${PYTHON:-python3}

fail() {
    echo "Uniswap V3 NPM observation-plan materialization failed: $*" >&2
    exit 1
}

[[ -n "$destination" ]] || fail "pass an explicit destination directory"
destination=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "destination cannot be resolved safely"

if [[ -e "$destination" ]]; then
    [[ -d "$destination" ]] || fail "destination exists and is not a directory"
    [[ -z "$(find "$destination" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
        || fail "destination must be empty"
fi

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-npm-observation-plan.py"
"$repo_dir/scripts/materialize-uniswap-v3-npm-resolved-inputs.sh" "$destination"
resolved_after_inputs=$(
    "$python_bin" "$repo_dir/scripts/resolve-materialization-destination.py" \
        --repository "$repo_dir" "$destination"
) || fail "materialized destination failed the containment recheck"
[[ "$resolved_after_inputs" == "$destination" ]] \
    || fail "materialized destination resolved to a different path"

for overlay_destination in "$destination/src" "$destination/configs" "$destination/tests"; do
    [[ -d "$overlay_destination" && ! -L "$overlay_destination" ]] \
        || fail "overlay destination must be a real directory: $overlay_destination"
done

[[ -f "$destination/tests/npm_resolved_inputs.rs" && ! -L "$destination/tests/npm_resolved_inputs.rs" ]] \
    || fail "inherited resolved-input harness is missing or unsafe"
rm "$destination/tests/npm_resolved_inputs.rs"

for target in \
    "$destination/src/npm_observation_plan.rs" \
    "$destination/src/uniswap.npm.plan.v1.rs" \
    "$destination/configs/npm-observation-plan-v1.json" \
    "$destination/tests/npm_observation_plan.rs"; do
    [[ ! -e "$target" ]] || fail "observation-plan target already exists: $target"
done

cp "$overlay_dir/src/npm_observation_plan.rs" "$destination/src/npm_observation_plan.rs"
cp "$overlay_dir/src/uniswap.npm.plan.v1.rs" "$destination/src/uniswap.npm.plan.v1.rs"
cp "$overlay_dir/npm-observation-plan-v1.json" "$destination/configs/npm-observation-plan-v1.json"
cp "$overlay_dir/tests/npm_observation_plan.rs" "$destination/tests/npm_observation_plan.rs"

"$python_bin" "$repo_dir/scripts/verify-uniswap-v3-npm-observation-plan.py" \
    --runtime "$destination"
"$repo_dir/scripts/verify-uniswap-v3-import.sh"

echo "materialized host-only Uniswap V3 NPM observation plan at $destination"
