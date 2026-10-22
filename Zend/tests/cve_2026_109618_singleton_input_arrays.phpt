--TEST--
Singleton input arrays preserve packed, sparse, mixed, copy-on-write and append behavior
--FILE--
<?php
function check($condition) {
    if (!$condition) {
        throw new Exception('input array mismatch');
    }
}
foreach (array('a', '0', '7', '999') as $first) {
    $fields = array('root[' . $first . ']=first');
    $expected = array($first => 'first');
    for ($i = 0; $i < 150; $i++) {
        $key = $i % 2 ? 'key' . $i : $i;
        $fields[] = 'root[' . $key . ']=' . $i;
        $expected[$key] = (string) $i;
    }
    parse_str(implode('&', $fields), $out);
    check($out['root'] === $expected);
    $copy = $out;
    $out['root']['extra'] = 'new';
    check(!isset($copy['root']['extra']));
    check(unserialize(serialize($copy)) === $copy);
    ksort($copy['root']);
    ksort($expected);
    check($copy['root'] === $expected);
    foreach (array_keys($copy['root']) as $key) {
        unset($copy['root'][$key]);
    }
    $copy['root'][] = 'after-empty';
    check(count($copy['root']) === 1);
}
parse_str('packed[]=zero&packed[]=one&packed[]=two', $out);
check($out === array('packed' => array('zero', 'one', 'two')));
parse_str('single[0]=zero', $out);
$copy = $out;
$out['single'][] = 'one';
check($out['single'] === array('zero', 'one'));
check($copy['single'] === array('zero'));
parse_str('sparse[999]=last', $out);
$out['sparse'][] = 'next';
check($out['sparse'] === array(999 => 'last', 1000 => 'next'));
parse_str('x=old&x[a][b][c]=new&list[][]=one&list[][]=two', $out);
check($out === array('x' => array('a' => array('b' => array('c' => 'new'))),
    'list' => array(array('one'), array('two'))));
echo "OK\n";
?>
--EXPECT--
OK
