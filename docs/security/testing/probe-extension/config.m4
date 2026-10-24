PHP_ARG_ENABLE(security-probe, build the benign backport verification probe,
[  --enable-security-probe    Build the backport verification probe], no)

if test "$PHP_SECURITY_PROBE" != "no"; then
  PHP_NEW_EXTENSION(security_probe, security_probe.c, $ext_shared)
fi
