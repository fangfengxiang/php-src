--TEST--
RFC1867 part limit preserves completed form fields and uploaded file data
--INI--
file_uploads=1
max_multipart_body_parts=2
--POST_RAW--
Content-Type: multipart/form-data; boundary=php70-retained-data
--php70-retained-data
Content-Disposition: form-data; name="field"

value
--php70-retained-data
Content-Disposition: form-data; name="upload"; filename="first.txt"
Content-Type: text/plain

hello
--php70-retained-data
Content-Disposition: form-data; name="blocked"

ignored
--php70-retained-data
Content-Disposition: form-data; name="blocked_file"; filename="ignored.txt"
Content-Type: text/plain

ignored
--php70-retained-data--
--FILE--
<?php
var_dump($_POST, array_keys($_FILES));
var_dump($_FILES['upload']['name'], $_FILES['upload']['type'],
    $_FILES['upload']['size'], $_FILES['upload']['error']);
var_dump(is_uploaded_file($_FILES['upload']['tmp_name']));
var_dump(file_get_contents($_FILES['upload']['tmp_name']));
?>
--EXPECTF--
Warning: %sMultipart body parts limit exceeded 2.%s
array(1) {
  ["field"]=>
  string(5) "value"
}
array(1) {
  [0]=>
  string(6) "upload"
}
string(9) "first.txt"
string(10) "text/plain"
int(5)
int(0)
bool(true)
string(5) "hello"
