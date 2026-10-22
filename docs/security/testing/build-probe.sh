#!/bin/sh
set -eu
mkdir -p /work/probe
cp /harness/probe-extension/* /work/probe/
cd /work/probe
export PHP_AUTOCONF=autoconf2.69
export PHP_AUTOHEADER=autoheader2.69
/work/install/bin/phpize > /work/logs/probe-build.log 2>&1
./configure --with-php-config=/work/install/bin/php-config --enable-security-probe \
    >> /work/logs/probe-build.log 2>&1
make -j2 >> /work/logs/probe-build.log 2>&1
/work/install/bin/php -n -d extension=/work/probe/modules/security_probe.so \
    -r 'echo json_encode(security_probe()), "\n";' > /work/logs/probe-abi.json
