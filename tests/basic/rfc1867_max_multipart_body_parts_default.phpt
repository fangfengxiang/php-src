--TEST--
RFC1867 derived multipart part limit uses input and upload limits
--INI--
file_uploads=1
error_reporting=E_ALL&~E_NOTICE
max_input_vars=1
max_file_uploads=1
max_multipart_body_parts=-1
--POST_RAW--
Content-Type: multipart/form-data; boundary=php70-security
--php70-security
Content-Disposition: form-data; name="empty1"; filename=""


--php70-security
Content-Disposition: form-data; name="empty2"; filename=""


--php70-security
Content-Disposition: form-data; name="blocked"

value
--php70-security--
--FILE--
<?php
var_dump($_POST, array_keys($_FILES));
?>
--EXPECTF--
Warning: %sMultipart body parts limit exceeded 2.%s
array(0) {
}
array(2) {
  [0]=>
  string(6) "empty1"
  [1]=>
  string(6) "empty2"
}
