--TEST--
RFC1867 explicit zero multipart part limit rejects the first part
--INI--
file_uploads=1
error_reporting=E_ALL&~E_NOTICE
max_multipart_body_parts=0
--POST_RAW--
Content-Type: multipart/form-data; boundary=php70-security
--php70-security
Content-Disposition: form-data; name="blocked"

value
--php70-security
Content-Disposition: form-data; name="empty"; filename=""


--php70-security--
--FILE--
<?php var_dump($_POST, $_FILES); ?>
--EXPECTF--
Warning: %sMultipart body parts limit exceeded 0.%s
array(0) {
}
array(0) {
}
