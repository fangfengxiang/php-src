#!/bin/sh
# Invoked in a disposable, network-isolated Docker container.
set -eu
mode=${1:-debug}
sh /harness/build.sh "$mode"
if test "$mode" = asan; then
    export CFLAGS='-O1 -g3 -fcommon -fno-omit-frame-pointer -fsanitize=address'
    export LDFLAGS='-fsanitize=address'
    export RUNNER_VARIABLES_ORDER=EGPCS
fi
export ASAN_OPTIONS=detect_leaks=0:abort_on_error=1:allocator_may_return_null=1
sh /harness/build-probe.sh
native_option=
fpm_option=
if test "$mode" = legacy; then
    native_option=--legacy
    fpm_option=--expect-baseline
fi
python3 /harness/native-invariants.py --php /work/install/bin/php \
    --module /work/probe/modules/security_probe.so --output /work/logs/native.json $native_option
python3 /harness/fpm-invariants.py --fpm /work/install/sbin/php-fpm \
    --output /work/logs/fpm.json $fpm_option
if test "$mode" = legacy; then exit 0; fi
cd /work/source
# Compare both generated headers byte-for-byte with the reviewed files.
cp Zend/zend_vm_execute.h /work/logs/zend_vm_execute.h.expected
cp Zend/zend_vm_opcodes.h /work/logs/zend_vm_opcodes.h.expected
/work/install/bin/php -n Zend/zend_vm_gen.php > /work/logs/vm-generation.log 2>&1
cmp Zend/zend_vm_execute.h /work/logs/zend_vm_execute.h.expected
cmp Zend/zend_vm_opcodes.h /work/logs/zend_vm_opcodes.h.expected
sh /harness/run-phpt.sh Zend/tests/cve_2026_109618_*.phpt \
    ext/session/tests/rfc1867_upload_progress_disabled.phpt \
    tests/basic/rfc1867_duplicate_headers.phpt \
    tests/basic/rfc1867_empty_file_nested_name.phpt \
    tests/basic/rfc1867_max_multipart_body_parts*.phpt
if test "$mode" = asan; then
    for item in log xml; do mv /work/logs/phpt.$item /work/logs/zend-mm-phpt.$item; done
    for item in failures.txt exit-status.txt; do
        mv /work/logs/phpt-$item /work/logs/zend-mm-phpt-$item
    done
    export USE_ZEND_ALLOC=0 RUNNER_VARIABLES_ORDER=EGPCS
    python3 /harness/fpm-invariants.py --fpm /work/install/sbin/php-fpm \
        --system-allocator --output /work/logs/fpm-system-allocator.json
    # OOM/overflow assertions depend on Zend MM; exercise input arrays here.
    sh /harness/run-phpt.sh Zend/tests/cve_2026_109618_singleton_input_arrays.phpt \
        tests/basic/rfc1867_empty_file_nested_name.phpt
fi
