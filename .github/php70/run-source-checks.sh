#!/bin/sh
# PHP-source checks belong here; external runtime probes run in /harness.
set -eu
mode=${1:-debug}
ci_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export ASAN_OPTIONS=detect_leaks=0:abort_on_error=1:allocator_may_return_null=1
if test "$mode" = asan; then export RUNNER_VARIABLES_ORDER=EGPCS; fi
cd /work/source
cp Zend/zend_vm_execute.h /work/logs/zend_vm_execute.h.expected
cp Zend/zend_vm_opcodes.h /work/logs/zend_vm_opcodes.h.expected
/work/install/bin/php -n Zend/zend_vm_gen.php > /work/logs/vm-generation.log 2>&1
cmp Zend/zend_vm_execute.h /work/logs/zend_vm_execute.h.expected
cmp Zend/zend_vm_opcodes.h /work/logs/zend_vm_opcodes.h.expected
PHP70_BUILD_DONE=1 PHP70_STAGES=security sh "$ci_root/run-phpt-stages.sh" "$mode"
if test "$mode" = asan; then
    export USE_ZEND_ALLOC=0 RUNNER_VARIABLES_ORDER=EGPCS
    sh "$ci_root/run-phpt.sh" Zend/tests/cve_2026_109618_singleton_input_arrays.phpt \
        tests/basic/rfc1867_empty_file_nested_name.phpt
    python3 - <<'PY_CHECK'
from xml.etree import ElementTree
cases = ElementTree.parse('/work/logs/phpt.xml').findall('.//testcase')
if len(cases) != 2 or any(c.find(k) is not None for c in cases for k in ('failure', 'error', 'skipped')):
    raise SystemExit('System allocator PHPT must complete with 2 passes and no skips')
PY_CHECK
fi
