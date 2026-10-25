--TEST--
RFC1867 retains the first relevant header and ignores unused and duplicate headers
--INI--
file_uploads=1
--POST_RAW--
Content-Type: multipart/form-data; boundary=php56-security
--php56-security
Content-Disposition: form-data; name="field"
X-Unused: ignored
 continuation-ignored
content-disposition: form-data; name="wrong"

value
--php56-security
Content-Disposition: form-data; name="upload"; filename="first.txt"
Content-Disposition: form-data; name="wrong"; filename="second.txt"
Content-Type: text/plain
content-type: application/octet-stream
X-Unused: ignored

hello
--php56-security--
--FILE--
<?php
var_dump($_POST, array_keys($_FILES));
var_dump($_FILES['upload']['name'], $_FILES['upload']['type'],
    $_FILES['upload']['size'], $_FILES['upload']['error']);
var_dump(file_get_contents($_FILES['upload']['tmp_name']));
?>
--EXPECT--
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
string(5) "hello"
