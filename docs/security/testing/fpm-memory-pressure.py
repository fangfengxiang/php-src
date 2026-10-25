#!/usr/bin/env python3
"""Bounded, benign allocation pressure inside one memory-limited cgroup v2."""

import argparse
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import tempfile
import time


def cgroup():
    root = Path('/sys/fs/cgroup')
    result = {}
    for name in ('memory.max', 'memory.current', 'memory.peak', 'memory.swap.max',
                 'memory.events', 'memory.oom.group'):
        raw = (root / name).read_text().strip()
        result[name] = (dict((key, int(value)) for key, value in
                            (line.split() for line in raw.splitlines()))
                        if name == 'memory.events' else int(raw))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fpm', required=True)
    parser.add_argument('--memory-limit', choices=('16M', '-1'), required=True)
    parser.add_argument('--container-bytes', type=int, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        'fcgi', Path(__file__).with_name('fpm-invariants.py'))
    fcgi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fcgi)
    output = Path(args.output)
    report = {'php_memory_limit': args.memory_limit, 'allocation_bound_mib': 512,
              'chunk_mib': 1, 'checks': [], 'pass': False}
    master = None
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='php70-pressure-', dir='/tmp') as temporary:
        root = Path(temporary)
        root.chmod(0o777)
        script = root / 'probe.php'
        address = root / 'fpm.sock'
        marker = root / 'shutdown-marker'
        log = root / 'fpm.log'
        script.write_text('''<?php
if (isset($_GET['pressure'])) {
    file_put_contents(__DIR__ . '/pressure-pid', (string) getmypid());
    register_shutdown_function(function () {
        file_put_contents(__DIR__ . '/shutdown-marker', 'called');
    });
    $chunks = array();
    for ($i = 0; $i < 512; $i++) {
        $chunks[] = str_repeat('x', 1024 * 1024);
        usleep(2000);
    }
    echo 'ALLOCATION_BOUND_REACHED';
} else {
    session_id('pressureprobe'); session_start();
    $_SESSION['count'] = isset($_SESSION['count']) ? $_SESSION['count'] + 1 : 1;
    echo json_encode(array('pid' => getmypid(), 'count' => $_SESSION['count'],
        'php_version' => PHP_VERSION, 'memory_limit' => ini_get('memory_limit')));
    session_write_close();
}
''')
        config = root / 'fpm.conf'
        worker_group = grp.getgrgid(pwd.getpwnam('nobody').pw_gid).gr_name
        config.write_text('''[global]
daemonize = no
error_log = {root}/fpm.log
log_level = notice
[probe]
user = nobody
group = {worker_group}
listen = {socket}
pm = static
pm.max_children = 1
pm.max_requests = 0
catch_workers_output = yes
php_admin_value[memory_limit] = {limit}
php_admin_value[session.save_path] = {root}
php_admin_value[display_errors] = 0
php_admin_value[log_errors] = 1
'''.format(root=root, socket=address, limit=args.memory_limit, worker_group=worker_group))
        def check(name, condition):
            report['checks'].append({'check': name, 'pass': bool(condition)})
            if not condition:
                raise AssertionError(name)
        try:
            report['cgroup_before'] = cgroup()
            check('cgroup memory cap matches requested bytes',
                  report['cgroup_before']['memory.max'] == args.container_bytes)
            check('cgroup swap disabled', report['cgroup_before']['memory.swap.max'] == 0)
            environment = dict(os.environ)
            environment.pop('USE_ZEND_ALLOC', None)
            with (root / 'console.log').open('wb') as console:
                master = subprocess.Popen([args.fpm, '-n', '-F', '-R', '-y', str(config)],
                                          stdout=console, stderr=console, env=environment)
                report['master_pid'] = master.pid
                for unused in range(100):
                    if address.exists() or master.poll() is not None:
                        break
                    time.sleep(0.05)
                before = [fcgi.result_json(fcgi.request(address, script)) for unused in range(3)]
                report['runtime'] = before[0]
                check('PHP 7.0.33 uses the intended memory_limit',
                      before[0]['php_version'] == '7.0.33' and before[0]['memory_limit'] == args.memory_limit)
                check('normal requests reuse one worker and persist session',
                      len({item['pid'] for item in before}) == 1 and
                      [item['count'] for item in before] == [1, 2, 3])
                report['worker_before'] = before[-1]['pid']
                report['pressure_response'] = fcgi.request(address, script, 'pressure=1')
                check('allocation stopped before bounded loop completed',
                      'ALLOCATION_BOUND_REACHED' not in report['pressure_response']['raw'] and
                      (root / 'pressure-pid').read_text() == str(report['worker_before']))
                after = None
                for unused in range(100):
                    if master.poll() is not None:
                        break
                    try:
                        after = fcgi.result_json(fcgi.request(address, script))
                        break
                    except (OSError, ValueError):
                        time.sleep(0.05)
                check('master survives pressure', master.poll() is None)
                check('replacement worker serves persisted session',
                      after is not None and after['pid'] != report['worker_before'] and after['count'] == 4)
                report['replacement_response'] = after
                again = fcgi.result_json(fcgi.request(address, script))
                check('replacement worker remains usable', again['pid'] == after['pid'] and again['count'] == 5)
                report['worker_after'] = after['pid']
                check('no PHP shutdown callback after OOM', not marker.exists())
                report['cgroup_after'] = cgroup()
                report['oom_kill_delta'] = (report['cgroup_after']['memory.events']['oom_kill'] -
                                            report['cgroup_before']['memory.events']['oom_kill'])
                logs = log.read_text()
                if args.memory_limit == '16M':
                    check('Zend OOM has no kernel OOM kill', report['oom_kill_delta'] == 0)
                    check('Zend fail-stop logged exit code 1',
                          re.search(r'child %d exited with code 1\b' % report['worker_before'], logs) is not None
                          and 'Allowed memory size of 16777216 bytes exhausted' in logs)
                else:
                    check('kernel cgroup OOM kill counted', report['oom_kill_delta'] >= 1)
                    check('kernel victim is the old FPM worker',
                          re.search(r'child %d exited on signal 9\b' % report['worker_before'], logs) is not None)
                report['pass'] = True
        except Exception as error:
            report['error'] = '%s: %s' % (type(error).__name__, error)
        finally:
            report['harness_forced_master_kill'] = False
            if master is not None and master.poll() is None:
                master.send_signal(signal.SIGTERM)
                try:
                    master.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    report['harness_forced_master_kill'] = True
                    master.kill()
                    master.wait()
                    report['pass'] = False
            report['master_final_exit_code'] = master.returncode if master else None
            report['elapsed_seconds'] = round(time.monotonic() - started, 3)
            output.with_suffix('.fpm.log').write_text(log.read_text() if log.exists() else '')
            output.with_suffix('.console.log').write_text((root / 'console.log').read_text()
                                                        if (root / 'console.log').exists() else '')
            output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'pass': report['pass']}))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
