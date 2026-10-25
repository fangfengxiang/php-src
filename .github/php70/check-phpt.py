"""Fail closed on incomplete PHPT runs; security tests cannot be skipped."""
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

stage = sys.argv[1]
root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/work/logs')
expected = root.joinpath(stage + '-tests.txt').read_text().splitlines()
cases = ElementTree.parse(root / (stage + '.xml')).findall('.//testcase')
failures = [case.attrib['name'] for case in cases
            if case.find('failure') is not None or case.find('error') is not None]
skips = [case.attrib['name'] for case in cases if case.find('skipped') is not None]
complete = len(cases) == len(expected)
passed = complete and not failures and (stage != 'security' or not skips)
summary = dict(stage=stage, expected=len(expected), recorded=len(cases),
               complete=complete, failures=failures, skipped=skips, passed=passed)
root.joinpath(stage + '-summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(0 if passed else 1)
