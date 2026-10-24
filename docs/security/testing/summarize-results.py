#!/usr/bin/env python3
"""Summarize real PHPT results and keep failed assertions visible."""
import argparse
import json
from pathlib import Path
import re

p=argparse.ArgumentParser()
p.add_argument('--artifacts',required=True)
p.add_argument('--output',required=True)
p.add_argument('--baseline-folder',default='baseline-debug')
p.add_argument('--hardened-folder',default='patched-debug')
p.add_argument('--initial-summary')
p.add_argument('--legacy-folder',default='mode-legacy')
p.add_argument('--asan-folder',default='patched-asan')
p.add_argument('--release-folder',default='patched-release')
a=p.parse_args()
root=Path(a.artifacts)
def parse(folder,name='phpt.log'):
    source=root/folder/'logs'/name
    text=source.read_text(errors='replace')
    metrics={}
    labels={'total':'Number of tests','skipped':'Tests skipped','warned':'Tests warned',
            'failed':'Tests failed','expected_fail':'Expected fail','passed':'Tests passed'}
    for key,label in labels.items():
        values=re.findall(r'^'+label+r'\s*:\s*(\d+)',text,re.M)
        metrics[key]=int(values[-1]) if values else None
    if any(v is None for v in metrics.values()):
        raise RuntimeError('Incomplete PHPT summary: '+str(source))
    cases={}
    for status,path in re.findall(r'(?:^|\r|\n)(PASS|FAIL|SKIP|XFAIL|WARN|BORK) .*?\[([^\]\r\n]+\.phpt)\]',text):
        cases[path]=status
    return {'summary':metrics,'failures':sorted(n for n,s in cases.items() if s=='FAIL')},cases
def optional(folder,name='phpt.log'):
    if not (root/folder/'logs'/name).exists():
        return {'not_executed':True,'summary':None,'failures':[]}
    return parse(folder,name)[0]

baseline,b=parse(a.baseline_folder);hardened,h=parse(a.hardened_folder)
changes=[{'path':n,'baseline':b.get(n,'NEW'),'hardened':status} for n,status in h.items() if b.get(n)!=status]
new_failures=sorted(set(hardened['failures'])-set(baseline['failures']))
explanations={}
for n in new_failures:
    if n.startswith('ext/session/tests/rfc1867'):
        reason='Intended compatibility change: hardened mode disables Session Upload Progress; original positive expectations are kept unchanged.'
    elif n=='tests/lang/bug45392.phpt':
        reason='Intended stderr diagnostic formatting: upstream fail-stop reporter adds an initial newline; output assertion differs by one blank line.'
    else:
        reason='UNEXPLAINED'
    diff=root/a.hardened_folder/'logs/test-diffs'/Path(n).with_suffix('.diff')
    if not diff.exists():
        diff=root/a.hardened_folder/'source'/Path(n).with_suffix('.diff')
    explanations[n]={'reason':reason,'diff':diff.read_text(errors='replace') if diff.exists() else None}
result={'baseline_full':baseline,'hardened_full':hardened,'status_changes':changes,'new_failure_analysis':explanations,
        'new_unexplained_failures':[n for n,v in explanations.items() if v['reason']=='UNEXPLAINED'],
        'legacy_targeted':optional(a.legacy_folder),
        'hardened_security':{k:optional(folder,'security-phpt.log') for k,folder in [('debug',a.hardened_folder),('asan',a.asan_folder),('release',a.release_folder)]},
        'asan_system_allocator_security':optional(a.asan_folder,'system-phpt.log')}
result['comparison_folders']={'baseline':a.baseline_folder,'hardened':a.hardened_folder}
if a.initial_summary:
    initial=json.loads(Path(a.initial_summary).read_text())
    result['initial_bind_mount_run']={'baseline':initial['baseline_full']['summary'],'hardened':initial['hardened_full']['summary']}
Path(a.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'baseline':baseline['summary'],'hardened':hardened['summary'],
                  'new_failures':new_failures,'unexplained':result['new_unexplained_failures']},indent=2))
