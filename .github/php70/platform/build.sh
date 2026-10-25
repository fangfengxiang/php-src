#!/bin/sh
set -eu

# Run inside the toolchain image with source.tar mounted read-only at /input,
# this harness mounted read-only at /harness, and an empty /work output mount.
mode=${1:-debug}
case "$mode" in
    debug|legacy|baseline)
        export CC=gcc
        export CFLAGS='-O0 -g3 -fcommon'
        export LDFLAGS=''
        debug_option=--enable-debug
        ;;
    release)
        export CC=gcc
        export CFLAGS='-O2 -g -fcommon'
        export LDFLAGS=''
        debug_option=--disable-debug
        ;;
    asan)
        export CC=gcc
        export CFLAGS='-O1 -g3 -fcommon -fno-omit-frame-pointer -fsanitize=address'
        export LDFLAGS='-fsanitize=address'
        export ASAN_OPTIONS='detect_leaks=0:abort_on_error=1'
        debug_option=--enable-debug
        ;;
    *) echo "usage: $0 debug|release|asan|legacy|baseline" >&2; exit 2 ;;
esac

security_option=--enable-php70-security
if test "$mode" = legacy; then
    security_option=--disable-php70-security
elif test "$mode" = baseline; then
    security_option=
fi

mkdir -p /work/source /work/logs
tar -xf /input/source.tar -C /work/source
cd /work/source
export PHP_AUTOCONF=autoconf2.69
export PHP_AUTOHEADER=autoheader2.69

{
    date -u
    uname -a
    cat /etc/os-release
    "$CC" --version
    "$PHP_AUTOCONF" --version
    bison --version
    re2c --version
    if command -v dpkg-query >/dev/null; then
        dpkg-query -W
    else
        rpm -qa
    fi
} > /work/logs/toolchain.txt 2>&1

echo "Generating PHP 7.0 build configuration ($mode)"
./buildconf --force > /work/logs/buildconf.log 2>&1
echo "Configuring PHP 7.0.33 ($mode)"
./configure --prefix=/work/install "$debug_option" $security_option \
    --enable-cli --enable-cgi --enable-fpm --without-pear --without-pcre-jit \
    --with-zlib --enable-pcntl --enable-posix --enable-sockets \
    > /work/logs/configure.log 2>&1
make clean > /work/logs/clean.log 2>&1
echo "Compiling PHP 7.0.33 ($mode, ${BUILD_JOBS:-1} jobs)"
make -j"${BUILD_JOBS:-1}" > /work/logs/make.log 2>&1
echo "Installing PHP 7.0.33 ($mode)"
make install > /work/logs/install.log 2>&1
# Refuse to test with a host/system PHP or a different PHP branch.
/work/install/bin/php -n -r 'if (PHP_VERSION_ID !== 70033) { fwrite(STDERR, "Expected branch-built PHP 7.0.33\n"); exit(1); }'
/work/install/bin/php -n -v > /work/logs/version.txt 2>&1
/work/install/bin/php -n -m > /work/logs/modules.txt 2>&1
echo "$mode build complete"
