--TEST--
RFC1867 nested empty file controls preserve no-file status across singleton growth
--INI--
file_uploads=1
error_reporting=E_ALL&~E_NOTICE
max_multipart_body_parts=4
--POST_RAW--
Content-Type: multipart/form-data; boundary=php70-nested
--php70-nested
Content-Disposition: form-data; name="upload[a][b][0]"; filename=""
Content-Type: application/octet-stream


--php70-nested
Content-Disposition: form-data; name="upload[a][b][999]"; filename=""
Content-Type: application/octet-stream


--php70-nested
Content-Disposition: form-data; name="upload[a][b][]"; filename=""
Content-Type: application/octet-stream


--php70-nested
Content-Disposition: form-data; name="field[a][b][c]"

value
--php70-nested--
--FILE--
<?php
var_dump($_POST['field']['a']['b']['c']);
foreach (array('name', 'tmp_name', 'error', 'size') as $property) {
    var_dump($_FILES['upload'][$property]['a']['b']);
}
?>
--EXPECT--
string(5) "value"
array(3) {
  [0]=>
  string(0) ""
  [999]=>
  string(0) ""
  [1000]=>
  string(0) ""
}
array(3) {
  [0]=>
  string(0) ""
  [999]=>
  string(0) ""
  [1000]=>
  string(0) ""
}
array(3) {
  [0]=>
  int(4)
  [999]=>
  int(4)
  [1000]=>
  int(4)
}
array(3) {
  [0]=>
  int(0)
  [999]=>
  int(0)
  [1000]=>
  int(0)
}
