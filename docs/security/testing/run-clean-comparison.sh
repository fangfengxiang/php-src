#!/bin/sh
# A complete fresh baseline/debug comparison in one container. Mount /work/source
# as a private Docker volume and keep /work/logs and /work/install on the host.
set -eu
mode=${1:-debug}
case "$mode" in baseline) fpm_option=--expect-baseline ;; debug) fpm_option= ;; *) exit 2 ;; esac
sh /harness/build.sh "$mode"
cp /work/source/Makefile /work/logs/generated-Makefile
cp /work/source/main/php_config.h /work/logs/generated-php_config.h
cd /work/source
sha256sum Zend/zend_alloc.c Zend/zend_hash.c Zend/zend_vm_def.h Zend/zend_vm_execute.h main/rfc1867.c ext/session/session.c > /work/logs/final-source-sha256.txt
if test -f Zend/zend_security.h; then sha256sum Zend/zend_security.h >> /work/logs/final-source-sha256.txt; fi
export ASAN_OPTIONS='detect_leaks=0:abort_on_error=1:allocator_may_return_null=1'
sh /harness/build-probe.sh
if test "$mode" = debug; then
 python3 /harness/native-invariants.py --php /work/install/bin/php --module /work/probe/modules/security_probe.so --output /work/logs/native-invariants.json > /work/logs/native-invariants.log 2>&1
fi
python3 /harness/fpm-invariants.py --fpm /work/install/sbin/php-fpm --output /work/logs/fpm-early-invariants.json $fpm_option > /work/logs/fpm-early-invariants.log 2>&1
if test "$mode" = debug; then
 set +e
 sh /harness/run-phpt.sh Zend/tests/cve_2026_109618_*.phpt ext/session/tests/rfc1867_upload_progress_disabled.phpt tests/basic/rfc1867_duplicate_headers.phpt tests/basic/rfc1867_empty_file_nested_name.phpt tests/basic/rfc1867_max_multipart_body_parts*.phpt > /work/logs/security-phpt-driver.log 2>&1
 status=$?
 set -e
 for item in log xml; do mv /work/logs/phpt.$item /work/logs/security-phpt.$item; done
 for item in failures.txt exit-status.txt; do mv /work/logs/phpt-$item /work/logs/security-phpt-$item; done
 if test "$status" != 0; then exit "$status"; fi
fi
set +e
sh /harness/run-phpt.sh > /work/logs/full-phpt-driver.log 2>&1
status=$?
set -e
python3 - <<'PY'
from pathlib import Path
import shutil
root=Path('/work/source')
for source in root.rglob('*.diff'):
    target=Path('/work/logs/test-diffs')/source.relative_to(root)
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
PY
printf '%s comparison completed; full PHPT exit=%s\n' "$mode" "$status"
exit "$status"
