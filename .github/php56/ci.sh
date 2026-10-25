#!/usr/bin/env bash
set -euo pipefail
# Only synthetic test evidence is exported; allow the host artifact uploader to read it.
trap 'chmod -R a+rX /work/results' EXIT
for mode in Debug Release; do
    source_dir="/work/source/$mode"
    mkdir -p "$source_dir"
    tar -xf /input/source.tar -C "$source_dir"
    harness="$source_dir/docs/security/testing"
    bash "$harness/php56-build.sh" --src "$source_dir" \
        --output "/work/results/$mode-build" --mode "$mode" --compiler cc --jobs 4
    python3 "$harness/php56-phpt.py" --src "$source_dir" \
        --output "/work/results/$mode-phpt" --targeted
    python3 "$harness/php56-native.py" --src "$source_dir" \
        --output "/work/results/$mode-native" --cc cc
    python3 "$harness/php56-fpm.py" --fpm "$source_dir/sapi/fpm/php-fpm" \
        --evidence-dir "/work/results/$mode-fpm"
done
