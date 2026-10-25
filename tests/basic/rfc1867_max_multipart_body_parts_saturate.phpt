--TEST--
RFC1867 derived multipart limit saturates instead of overflowing
--SKIPIF--
<?php if (PHP_INT_SIZE != 8) die('skip requires 64-bit integers'); ?>
--INI--
file_uploads=1
max_input_vars=9223372036854775807
max_file_uploads=20
max_multipart_body_parts=-1
--POST_RAW--
Content-Type: multipart/form-data; boundary=php56-security
--php56-security
Content-Disposition: form-data; name="field"

value
--php56-security--
--FILE--
<?php var_dump($_POST); ?>
--EXPECT--
array(1) {
  ["field"]=>
  string(5) "value"
}
