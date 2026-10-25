#!/usr/bin/env python3
"""Run PHP 5.6.40 PHPTs using only binaries built in --src.

Run:     php56-phpt.py --src SOURCE --output NEW_DIR --targeted
Compare: php56-phpt.py --compare BASELINE/result.json HARDENED/result.json

--full enumerates explicit test roots, never the source root or sibling builds.
Use a fresh source/build copy for each run: run-tests.php writes test artifacts.
The raw log and JUnit are retained; result.json has statuses keyed by PHPT path.
An unchanged baseline failure is not classified as a regression by this tool.
"""

import argparse
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def compare(paths, output):
    before, after = [json.loads(path.read_text()) for path in paths]
    old, new = before["tests"], after["tests"]
    changes = {path: {"baseline": old[path]["status"], "hardened": new[path]["status"]}
               for path in sorted(old.keys() & new.keys())
               if old[path]["status"] != new[path]["status"]}
    result = {
        "baseline": str(paths[0].resolve()), "hardened": str(paths[1].resolve()),
        "baseline_complete": before.get("complete", False),
        "hardened_complete": after.get("complete", False),
        "common_tests": len(old.keys() & new.keys()),
        "unchanged_tests": len(old.keys() & new.keys()) - len(changes),
        "status_changes": changes,
        "added_tests": {path: new[path] for path in sorted(new.keys() - old.keys())},
        "removed_tests": {path: old[path] for path in sorted(old.keys() - new.keys())},
        "interpretation": "Status differences require causal review; additions are separate from common-test changes.",
    }
    if output:
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "comparison.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["baseline_complete"] and result["hardened_complete"] else 2


def select_tests(src, full):
    if full:
        roots = [src / "Zend/tests", src / "tests", src / "ext"]
        roots += sorted(path / "tests" for path in (src / "sapi").iterdir()
                        if path.is_dir() and not path.is_symlink() and (path / "tests").is_dir())
        tests = set()
        for root in roots:
            if not root.is_dir() or root.is_symlink():
                continue
            for directory, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = sorted(name for name in dirs
                                 if name not in (".git", ".security-build")
                                 and not (Path(directory) / name).is_symlink())
                for name in names:
                    path = Path(directory) / name
                    if name.endswith(".phpt") and not path.is_symlink():
                        tests.add(path.relative_to(src).as_posix())
        return sorted(tests), [str(root.relative_to(src)) for root in roots]
    patterns = ["Zend/tests/cve_2026_109618*.phpt",
                "tests/basic/rfc1867_duplicate_headers.phpt",
                "tests/basic/rfc1867_max_multipart_body_parts*.phpt",
                "ext/session/tests/rfc1867_upload_progress_disabled.phpt"]
    tests = set()
    for pattern in patterns:
        matches = list(src.glob(pattern))
        if not matches:
            raise ValueError("No targeted test matches " + pattern)
        tests.update(path.relative_to(src).as_posix() for path in matches)
    return sorted(tests), patterns


def parse_statuses(log, src):
    # run-tests prints a progress counter before each result, separated by CR.
    # Preserve the full status, including combinations such as WARN&FAIL.
    status = r"(?:PASS|FAIL|SKIP|BORK|WARN|XFAIL|LEAK|REDIR)"
    # PHPT titles can contain brackets and embedded newlines. A bracket inside
    # a title must not be interpreted as the beginning of its result pathname.
    title = r"((?:(?!\nTEST \d+/\d+).)*?)"
    pattern = re.compile(r"^(" + status + r"(?:&" + status + r")*) " + title
                         + r" \[([^\[\]\r\n]*\.phpt)\]([^\r\n]*)$", re.MULTILINE | re.DOTALL)
    records = {}
    for match in pattern.finditer(log.replace("\r", "\n")):
        state, title, filename, detail = match.groups()
        path = Path(filename)
        if path.is_absolute():
            try:
                filename = path.relative_to(src).as_posix()
            except ValueError:
                raise ValueError("Result outside --src: " + filename)
        else:
            filename = path.as_posix()
        records[filename] = {"status": state, "title": title, "detail": detail.strip()}
    return records


def run(args, parser):
    src = args.src.resolve(strict=True)
    if '#define PHP_VERSION "5.6.40"' not in (src / "main/php_version.h").read_text():
        parser.error("--src must contain PHP 5.6.40")
    binaries = {"cli": src / "sapi/cli/php", "cgi": src / "sapi/cgi/php-cgi"}
    for name, path in binaries.items():
        if not path.is_file() or not os.access(path, os.X_OK) or path.is_symlink():
            parser.error("Missing built " + name + " executable: " + str(path))
    if not (src / "run-tests.php").is_file() or not (src / "main/php_config.h").is_file():
        parser.error("--src must be configured and built")
    tests, roots = select_tests(src, args.full)
    if not tests:
        parser.error("No PHPT files selected")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = output / "selected-tests.txt"
    manifest.write_text("".join(test + "\n" for test in tests))
    env = os.environ.copy()
    for key in ("TEST_PHP_ARGS", "TEST_PHP_EXTRA_ARGS", "TEST_PHP_LOG_FORMAT",
                "TEST_PHP_JUNIT", "TEST_PHP_VALGRIND", "TEST_PHPDBG_EXECUTABLE"):
        env.pop(key, None)
    env.update({"TEST_PHP_EXECUTABLE": str(binaries["cli"]),
                "TEST_PHP_CGI_EXECUTABLE": str(binaries["cgi"]),
                "NO_INTERACTION": "1", "REPORT_EXIT_STATUS": "1", "SKIP_ONLINE_TESTS": "1",
                "TEST_PHP_JUNIT": str(output / "junit.xml"), "PHP_INI_SCAN_DIR": "",
                "USE_ZEND_ALLOC": "1", "LC_ALL": "C"})
    # -r reads a list without rewriting it (-l also opens the list for writing).
    command = [str(binaries["cli"]), "-n", str(src / "run-tests.php"),
               "--offline", "-n", "-r", str(manifest)]
    evidence = {"schema_version": 1, "scope": "PHP 5.6.40 real PHPT execution; no remote exploit proof",
                "src": str(src), "mode": "full" if args.full else "targeted", "selection_roots": roots,
                "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "host": platform.platform(), "machine": platform.machine(), "command": command,
                "environment": {key: env[key] for key in ("TEST_PHP_EXECUTABLE", "TEST_PHP_CGI_EXECUTABLE",
                    "NO_INTERACTION", "REPORT_EXIT_STATUS", "SKIP_ONLINE_TESTS", "TEST_PHP_JUNIT",
                    "PHP_INI_SCAN_DIR", "USE_ZEND_ALLOC", "LC_ALL")},
                "binary_sha256": {name: sha256(path) for name, path in binaries.items()},
                "source_sha256": {name: sha256(src / name) for name in
                    ("run-tests.php", "main/php_config.h", "main/php_version.h")},
                "selected_count": len(tests), "selected_tests": tests, "tests": {}, "complete": False}
    evidence["runner_sha256"] = sha256(Path(__file__).resolve())
    write_json(output / "result.json", evidence)
    # Verify actual executables, rather than inferring their version from headers.
    evidence["binary_versions"] = {}
    for name, path in binaries.items():
        proc = subprocess.run([str(path), "-n", "-v"], cwd=src, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        text = proc.stdout.decode("utf-8", errors="replace")
        (output / (name + "-version.log")).write_bytes(proc.stdout)
        evidence["binary_versions"][name] = {"exit_code": proc.returncode, "output": text}
        if proc.returncode or not text.startswith("PHP 5.6.40 "):
            evidence["error"] = "Unexpected " + name + " binary version"
            write_json(output / "result.json", evidence)
            return 2
    interrupted = False
    with (output / "run-tests.log").open("wb") as log:
        proc = subprocess.Popen(command, cwd=src, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            interrupted = True
            proc.terminate()
            code = proc.wait()
    evidence["exit_code"] = code
    evidence["interrupted"] = interrupted
    evidence["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    evidence["tests"] = parse_statuses((output / "run-tests.log").read_text(errors="replace"), src)
    evidence["missing_results"] = [path for path in tests if path not in evidence["tests"]]
    for path in evidence["missing_results"]:
        evidence["tests"][path] = {"status": "NOT_RUN", "detail": "No result in runner output"}
    evidence["status_counts"] = dict(Counter(record["status"] for record in evidence["tests"].values()))
    evidence["complete"] = (not interrupted and code in (0, 1) and not evidence["missing_results"]
                            and (output / "junit.xml").is_file())
    evidence["junit_sha256"] = sha256(output / "junit.xml") if (output / "junit.xml").is_file() else None
    evidence["raw_log_sha256"] = sha256(output / "run-tests.log")
    write_json(output / "result.json", evidence)
    print(json.dumps({key: evidence[key] for key in ("src", "mode", "exit_code", "complete", "status_counts")}))
    return code if evidence["complete"] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--output", type=Path, help="New evidence directory")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--targeted", action="store_true")
    group.add_argument("--full", action="store_true")
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("BASELINE", "HARDENED"))
    args = parser.parse_args()
    if args.compare:
        if args.src or args.targeted or args.full:
            parser.error("--compare cannot be combined with a test run")
        return compare(args.compare, args.output)
    if not args.src or not args.output or not (args.targeted or args.full):
        parser.error("A run requires --src, --output and --targeted or --full")
    return run(args, parser)


if __name__ == "__main__":
    sys.exit(main())
