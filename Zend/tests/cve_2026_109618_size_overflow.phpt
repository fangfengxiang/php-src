--TEST--
CVE-2026-109618 allocation size overflow exits without request cleanup
--FILE--
<?php
register_shutdown_function(function () {
    echo "UNSAFE SHUTDOWN\n";
});
/* Overflow the checked size calculation without allocating a large buffer. */
str_repeat('xxxx', PHP_INT_MAX);
echo "UNREACHABLE\n";
?>
--EXPECTF--
Fatal error: Possible integer overflow in memory allocation (%d * %d + %d) in %s on line %d
