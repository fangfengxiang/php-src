--TEST--
RFC1867 derived zero multipart part limit rejects the first part
--INI--
file_uploads=1
error_reporting=E_ALL&~E_NOTICE
max_input_vars=0
max_file_uploads=0
max_multipart_body_parts=-1
--POST_RAW--
Content-Type: multipart/form-data; boundary=php70-derived-zero
--php70-derived-zero
Content-Disposition: form-data; name="blocked"

value
--php70-derived-zero
Content-Disposition: form-data; name="upload"; filename="test.txt"
Content-Type: text/plain

hello
--php70-derived-zero--
--FILE--
<?php var_dump($_POST, $_FILES); ?>
--EXPECTF--
Warning: %sMultipart body parts limit exceeded 0.%s
array(0) {
}
array(0) {
}
