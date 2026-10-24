#!/usr/bin/env python3
"""Run small-cgroup PHP 7.0 runtime checks; never cap a compiler build here."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='php70-security-toolchain:latest')
    parser.add_argument('--install', required=True, help='hardened PHP 7.0 install directory')
    parser.add_argument('--output', required=True, help='new directory for JSON and raw logs')
    parser.add_argument('--memory-mib', type=int, nargs='+', default=[64, 96, 128])
    args = parser.parse_args()
    if any(size < 32 or size > 256 for size in args.memory_mib):
        parser.error('runtime caps must be between 32 and 256 MiB')
    docker = shutil.which('docker')
    if not docker:
        parser.error('docker CLI not found')
    install = Path(args.install).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    harness = Path(__file__).resolve().parent
    def run(arguments, timeout=120):
        return subprocess.run([docker] + arguments, text=True, capture_output=True,
                              timeout=timeout, check=True).stdout.strip()
    image = json.loads(run(['image', 'inspect', args.image]))[0]
    result = {'image_id': image['Id'], 'image_tags': image.get('RepoTags'),
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'binaries_sha256': {}, 'cases': []}
    for name in ('bin/php', 'sbin/php-fpm'):
        result['binaries_sha256'][name] = hashlib.sha256((install / name).read_bytes()).hexdigest()
    cli = output / 'bounded-oom.php'
    cli.write_text('''<?php
register_shutdown_function(function () { file_put_contents('/results/cli-shutdown-marker', 'called'); });
echo "bounded pressure started\\n";
$chunks = array();
for ($i = 0; $i < 512; $i++) { $chunks[] = str_repeat('x', 1024 * 1024); usleep(2000); }
echo "ALLOCATION_BOUND_REACHED\\n";
''')
    cases = [('fpm-%s-%dm' % (kind, size), size, limit)
             for size in args.memory_mib for kind, limit in (('zend', '16M'), ('kernel', '-1'))]
    cases.append(('cli-kernel-%dm' % min(args.memory_mib), min(args.memory_mib), None))
    result.update(planned_case_count=len(cases), completed_case_count=0, completed=False, **{'pass': False})
    for name, size, limit in cases:
        case = {'name': name, 'memory_mib': size, 'pass': False}
        container_name = 'php70-pressure-' + uuid.uuid4().hex[:12]
        container = None
        try:
            command = ['run', '-d', '--name', container_name, '--network', 'none',
                       '--memory', '%dm' % size, '--memory-swap', '%dm' % size,
                       '--pids-limit', '32', '--mount', 'type=bind,src=%s,dst=/opt/php70,readonly' % install,
                       '--mount', 'type=bind,src=%s,dst=/harness,readonly' % harness,
                       '--mount', 'type=bind,src=%s,dst=/results' % output]
            if limit is None:
                command += ['--entrypoint', '/opt/php70/bin/php', args.image,
                            '-n', '-d', 'memory_limit=-1', '/results/bounded-oom.php']
            else:
                command += ['--entrypoint', 'python3', args.image, '/harness/fpm-memory-pressure.py',
                            '--fpm', '/opt/php70/sbin/php-fpm', '--memory-limit=' + limit,
                            '--container-bytes', str(size * 1024 * 1024),
                            '--output', '/results/' + name + '.json']
            container = run(command)
            case['container_id'] = container
            case['wait_exit_code'] = int(run(['wait', container], timeout=90))
            state = json.loads(run(['inspect', container]))[0]
            case['docker_state'] = {key: state['State'][key] for key in
                                    ('Status', 'ExitCode', 'OOMKilled', 'Error', 'StartedAt', 'FinishedAt')}
            case['docker_limits'] = {key: state['HostConfig'][key] for key in
                                     ('Memory', 'MemorySwap', 'NetworkMode', 'PidsLimit')}
            logs = run(['logs', container])
            (output / (name + '.container.log')).write_text(logs + '\n')
            correct_limits = (case['docker_limits']['Memory'] == size * 1024 * 1024 and
                              case['docker_limits']['MemorySwap'] == size * 1024 * 1024 and
                              case['docker_limits']['NetworkMode'] == 'none')
            if limit is None:
                case['pass'] = (correct_limits and case['wait_exit_code'] == 137 and
                                case['docker_state']['OOMKilled'] and
                                'bounded pressure started' in logs and
                                'ALLOCATION_BOUND_REACHED' not in logs and
                                not (output / 'cli-shutdown-marker').exists())
            else:
                report_path = output / (name + '.json')
                case['fpm'] = json.loads(report_path.read_text()) if report_path.exists() else None
                fpm_log = report_path.with_suffix('.fpm.log')
                case['fpm_log'] = fpm_log.read_text() if fpm_log.exists() else ''
                # Docker OOMKilled may also be true when a child was killed. The
                # in-cgroup counter and exact FPM victim distinguish this case.
                case['pass'] = (correct_limits and case['wait_exit_code'] == 0 and
                                case['fpm'] is not None and case['fpm']['pass'])
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            case['error'] = '%s: %s' % (type(error).__name__, error)
        finally:
            if container:
                subprocess.run([docker, 'rm', '-f', container], text=True, capture_output=True)
            result['cases'].append(case)
            result['completed_case_count'] = len(result['cases'])
            result['completed'] = len(result['cases']) == result['planned_case_count']
            result['pass'] = result['completed'] and all(item['pass'] for item in result['cases'])
            result['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({'case': name, 'pass': case['pass']}), flush=True)
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
