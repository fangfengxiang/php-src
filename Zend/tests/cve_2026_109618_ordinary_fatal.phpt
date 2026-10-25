--TEST--
Ordinary fatal errors preserve PHP 5.6 shutdown and destructor behavior
--FILE--
<?php
class FatalCleanup {
    public function __destruct() {
        echo "UNEXPECTED DESTRUCTOR\n";
    }
}
$cleanup = new FatalCleanup;
register_shutdown_function(function () {
    echo "NORMAL SHUTDOWN\n";
});
trigger_error('ordinary fatal', E_USER_ERROR);
echo "UNREACHABLE\n";
?>
--EXPECTF--
Fatal error: ordinary fatal in %s on line %d
NORMAL SHUTDOWN
