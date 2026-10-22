#!/usr/bin/env python3
"""Bounded allocator/ABI checks in an isolated container; no exploit payloads."""
import argparse
import json
import os
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--php', required=True)
p.add_argument('--module', required=True)
p.add_argument('--output', required=True)
p.add_argument('--legacy', action='store_true')
a = p.parse_args()
env = dict(os.environ)
env['ASAN_OPTIONS'] = 'detect_leaks=0:abort_on_error=1:allocator_may_return_null=1'
base = [a.php, '-n', '-d', 'extension=' + a.module]

def run(code, limit='8M'):
    r = subprocess.run(base + ['-d', 'memory_limit=' + limit, '-r', code],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=30)
    return {'returncode': r.returncode, 'stdout': r.stdout.decode(errors='replace'),
            'stderr': r.stderr.decode(errors='replace')}

checks = []
abi = run('echo json_encode(security_probe()), "\\n";')
assert abi['returncode'] == 0, abi
abi = json.loads(abi['stdout'])
assert abi.get('hardened') == (0 if a.legacy else 1), abi
checks.append({'check': 'build mode and ABI sizes', 'pass': True, 'data': abi})
for query in ('x[a]=v', 'x[999]=v', 'x[0]=v'):
    code = 'parse_str(' + json.dumps(query) + ', $v); echo json_encode(security_probe_array($v["x"]));'
    r = run(code)
    assert r['returncode'] == 0, r
    result = json.loads(r['stdout'])
    assert result['arData_mod_pointer_alignment'] == 0, result
    assert result['nTableSize'] == (8 if a.legacy else 1), result
    checks.append({'check': 'singleton alignment ' + query, 'pass': True, 'data': result})
for mode in ('emalloc', 'safe_emalloc', 'estrndup', 'zend_strndup', 'system_malloc',
             'inline_guard', 'huge_rounding', 'metadata_overflow', 'hash_capacity'):
    r = run('register_shutdown_function(function () { echo "PHP SHUTDOWN\\n"; });'
            'security_probe_allocation(' + json.dumps(mode) + '); echo "UNREACHABLE\\n";')
    if a.legacy:
        assert r['returncode'] != 0, (mode, r)
        if mode == 'system_malloc':
            assert 'C EXIT CALLBACK' in r['stderr'], (mode, r)
        else:
            assert 'PHP SHUTDOWN' in r['stdout'], (mode, r)
    else:
        assert r['returncode'] == 1, (mode, r)
        assert 'PHP SHUTDOWN' not in r['stdout'] and 'UNREACHABLE' not in r['stdout'], (mode, r)
        assert 'C EXIT CALLBACK' not in r['stderr'], (mode, r)
    assert 'ERROR: AddressSanitizer' not in r['stderr'], (mode, r)
    checks.append({'check': mode, 'pass': True, **r})
Path(a.output).write_text(json.dumps({'legacy': a.legacy, 'checks': checks}, indent=2) + '\n')
print(json.dumps({'output': a.output, 'passed': len(checks)}))
