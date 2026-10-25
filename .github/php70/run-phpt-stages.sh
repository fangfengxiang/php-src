#!/bin/sh
set -eu
ci_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if test "${PHP70_BUILD_DONE:-0}" != 1; then sh /harness/build.sh "$1"; fi
cd /work/source
export TEST_PHP_EXECUTABLE=/work/install/bin/php
export TEST_PHP_CGI_EXECUTABLE=/work/install/bin/php-cgi
export TEST_PHPDBG_EXECUTABLE=/work/install/bin/phpdbg
export NO_INTERACTION=1 REPORT_EXIT_STATUS=1
# The eight positive progress tests require the feature deliberately disabled by
# this mitigation. Keep an explicit inventory, not a directory-wide exclusion.
python3 - "$ci_root" <<'PY'
from pathlib import Path
import json
import sys
excluded = set((Path(sys.argv[1]) / 'progress-compatibility.txt').read_text().splitlines())
assert len(excluded) == 8 and all(Path(p).is_file() for p in excluded)
security = sorted({str(p) for pattern in (
    'Zend/tests/cve_2026_109618_*.phpt',
    'ext/session/tests/rfc1867_upload_progress_disabled.phpt',
    'tests/basic/rfc1867_duplicate_headers.phpt',
    'tests/basic/rfc1867_empty_file_nested_name.phpt',
    'tests/basic/rfc1867_max_multipart_body_parts*.phpt',
) for p in Path('.').glob(pattern)})
assert len(security) == 14, security
integration = sorted(str(p) for d in ('Zend/tests', 'ext/session/tests', 'tests/basic')
                     for p in Path(d).rglob('*.phpt') if str(p) not in excluded)
for name, tests in (('security', security), ('integration', integration)):
    Path('/work/logs', name + '-tests.txt').write_text('\n'.join(tests) + '\n')
Path('/work/logs/progress-compatibility.json').write_text(json.dumps({
    'excluded_positive_progress_tests': sorted(excluded),
    'reason': 'Hardened PHP 7.0 deliberately disables session upload progress',
    'required_replacement': 'ext/session/tests/rfc1867_upload_progress_disabled.phpt',
}, indent=2))
PY
result=0
for stage in ${PHP70_STAGES:-security integration}; do
    export TEST_PHP_JUNIT="/work/logs/$stage.xml"
    status=0
    /work/install/bin/php -n -d variables_order="${RUNNER_VARIABLES_ORDER:-GPCS}" run-tests.php -q -n --offline \
        -r "/work/logs/$stage-tests.txt" -w "/work/logs/$stage-failures.txt" \
        > "/work/logs/$stage.log" 2>&1 || status=$?
    echo "$status" > "/work/logs/$stage-exit-status.txt"
    tail -65 "/work/logs/$stage.log"
    # A missing/incomplete XML report must not pass even if the runner exits 0.
    python3 "$ci_root/check-phpt.py" "$stage" || result=1
    if test "$status" != 0; then result=1; fi
done
python3 - <<'PY'
from pathlib import Path
import shutil
for suffix in ('*.diff', '*.out', '*.exp', '*.log'):
    for source in Path('.').rglob(suffix):
        target = Path('/work/logs/diagnostics') / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
PY
exit "$result"
