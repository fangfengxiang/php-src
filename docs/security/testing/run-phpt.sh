#!/bin/sh
set -eu
cd /work/source
export TEST_PHP_EXECUTABLE=/work/install/bin/php
export TEST_PHP_CGI_EXECUTABLE=/work/install/bin/php-cgi
export TEST_PHPDBG_EXECUTABLE=/work/install/bin/phpdbg
export NO_INTERACTION=1
export REPORT_EXIT_STATUS=1
export TEST_PHP_JUNIT=/work/logs/phpt.xml
runner=run-tests.php
if test "${USE_ZEND_ALLOC:-1}" = 0; then
    # The 7.0 runner otherwise forces Zend MM back on at every SKIPIF.
    # Adapt only a temporary runner, without changing PHPT or runtime checks.
    python3 - <<'PY'
from pathlib import Path
source = Path('run-tests.php').read_text()
old = "$env['USE_ZEND_ALLOC'] = '1';"
assert source.count(old) == 2
Path('run-tests-system-allocator.php').write_text(source.replace(old,
    "$env['USE_ZEND_ALLOC'] = getenv('USE_ZEND_ALLOC') === '0' ? '0' : '1';"))
PY
    runner=run-tests-system-allocator.php
fi
# No public network is available in the calling --network none container.
set +e
# PHP 7.0's runner constructs child environments from $_ENV. Use EGPCS when
# sanitizer/allocator environment flags must reach the tested subprocesses.
/work/install/bin/php -n -d variables_order="${RUNNER_VARIABLES_ORDER:-GPCS}" "$runner" -q -n --offline \
    -w /work/logs/phpt-failures.txt "$@" > /work/logs/phpt.log 2>&1
status=$?
set -e
echo "$status" > /work/logs/phpt-exit-status.txt
tail -70 /work/logs/phpt.log
exit "$status"
