--TEST--
CVE-2026-109618 OOM exits without request shutdown callbacks or destructors
--SKIPIF--
<?php
if (getenv('USE_ZEND_ALLOC') === '0') {
    die('skip Zend MM disabled');
}
?>
--INI--
memory_limit=8M
--FILE--
<?php
class OomCleanup {
    public function __destruct() {
        echo "UNSAFE DESTRUCTOR\n";
    }
}
$cleanup = new OomCleanup;
register_shutdown_function(function () {
    echo "UNSAFE SHUTDOWN\n";
});
$buffer = str_repeat('x', 32 * 1024 * 1024);
echo "UNREACHABLE\n";
?>
--EXPECTF--
Fatal error: Allowed memory size of %d bytes exhausted%S(tried to allocate %d bytes) in %s on line %d
