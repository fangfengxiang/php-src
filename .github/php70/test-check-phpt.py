"""Negative controls: incomplete, failed and skipped security runs cannot pass."""
from pathlib import Path
import subprocess
import sys
import tempfile

checker = Path(__file__).with_name('check-phpt.py')
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    for stage, expected, xml, succeeds in (
        ('security', 1, '<testcase name="a"/>', True),
        ('security', 2, '<testcase name="a"/>', False),
        ('security', 1, '<testcase name="a"><failure/></testcase>', False),
        ('security', 1, '<testcase name="a"><error/></testcase>', False),
        ('security', 1, '<testcase name="a"><skipped/></testcase>', False),
        ('integration', 1, '<testcase name="a"><skipped/></testcase>', True),
        ('integration', 1, '<testcase name="a"><failure/></testcase>', False),
        ('security', 1, '<invalid', False),
    ):
        (root / (stage + '-tests.txt')).write_text('a.phpt\n' * expected)
        (root / (stage + '.xml')).write_text('<testsuite>' + xml + '</testsuite>')
        result = subprocess.run([sys.executable, str(checker), stage, temp],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert (result.returncode == 0) == succeeds, (stage, xml, result.stdout)
print('8 PHPT gate controls passed')
