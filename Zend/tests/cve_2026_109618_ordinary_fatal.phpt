--TEST--
Ordinary fatal errors still run registered request shutdown functions
--FILE--
<?php
register_shutdown_function(function () {
    echo "NORMAL SHUTDOWN\n";
});
trigger_error('ordinary fatal', E_USER_ERROR);
echo "UNREACHABLE\n";
?>
--EXPECTF--
Fatal error: ordinary fatal in %s on line %d
NORMAL SHUTDOWN
