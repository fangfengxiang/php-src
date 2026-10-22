--TEST--
CVE-2026-109619 upload progress cannot be enabled while normal sessions and uploads work
--SKIPIF--
<?php include('skipif.inc'); ?>
--INI--
file_uploads=1
session.save_path=
session.save_handler=files
session.use_cookies=1
session.use_only_cookies=1
session.upload_progress.enabled=1
session.upload_progress.cleanup=0
session.upload_progress.name=PHP_SESSION_UPLOAD_PROGRESS
session.upload_progress.prefix=upload_progress_
session.upload_progress.freq=0
--COOKIE--
PHPSESSID=php70-cve2026109619
--POST_RAW--
Content-Type: multipart/form-data; boundary=php70-security
--php70-security
Content-Disposition: form-data; name="PHPSESSID"

ignored-form-sid
--php70-security
Content-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"

security-test
--php70-security
Content-Disposition: form-data; name="upload"; filename="test.txt"
Content-Type: text/plain

hello
--php70-security--
--FILE--
<?php
session_start();
$sid = session_id();
$progress_exists = isset($_SESSION['upload_progress_security-test']);
$_SESSION['ordinary'] = array('value' => 'retained');
session_write_close();
session_start();
$roundtrip = $_SESSION;
session_destroy();
var_dump($sid, $progress_exists, $_POST['PHP_SESSION_UPLOAD_PROGRESS']);
var_dump($_FILES['upload']['error'], $_FILES['upload']['size']);
var_dump(is_uploaded_file($_FILES['upload']['tmp_name']));
var_dump(file_get_contents($_FILES['upload']['tmp_name']));
var_dump($roundtrip);
?>
--EXPECT--
string(19) "php70-cve2026109619"
bool(false)
string(13) "security-test"
int(0)
int(5)
bool(true)
string(5) "hello"
array(1) {
  ["ordinary"]=>
  array(1) {
    ["value"]=>
    string(8) "retained"
  }
}
