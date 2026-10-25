#!/usr/bin/env python3
"""Build and run the test-only PHP 5.6 native boundary extension.

Example inside the linux/amd64 build container:
  python3 /work/docs/security/testing/php56-native.py \
    --src /work/.security-build/x64-hardened/src \
    --output /work/.security-build/evidence/x64-hardened-native

The extension is freshly compiled against --src, without phpize or a host PHP.
--compile-only writes build evidence without executing the PHP CLI.
This checks fail-stop boundaries and ZE2 table invariants, not remote RCE.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _hash_stream(stream)


def _hash_stream(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def run(command, directory, name, env=None, timeout=30):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, timeout=timeout, check=False)
        result = {"command": command, "started_utc": started,
                  "exit_code": proc.returncode, "timed_out": False,
                  "stdout": proc.stdout.decode("utf-8", errors="replace"),
                  "stderr": proc.stderr.decode("utf-8", errors="replace")}
    except subprocess.TimeoutExpired as error:
        result = {"command": command, "started_utc": started, "exit_code": None,
                  "timed_out": True,
                  "stdout": (error.stdout or b"").decode("utf-8", errors="replace"),
                  "stderr": (error.stderr or b"").decode("utf-8", errors="replace")}
    (directory / (name + ".stdout")).write_text(result["stdout"])
    (directory / (name + ".stderr")).write_text(result["stderr"])
    (directory / (name + ".command.json")).write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, required=True, help="Configured and built source tree for this branch")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; existing directories are rejected")
    parser.add_argument("--php", type=Path, help="Defaults to --src/sapi/cli/php")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"), help="Compiler command, split with shlex")
    parser.add_argument("--cflags", default="-O2 -g -Wall -Wextra", help="Additional extension C flags")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    src = args.src.resolve(strict=True)
    php = (args.php or src / "sapi/cli/php").resolve(strict=True)
    source = Path(__file__).resolve().parent / "probe/php56_probe.c"
    for header in ("main/php_config.h", "main/php_version.h", "Zend/zend_modules.h", "Zend/zend_alloc.h"):
        if not (src / header).is_file():
            parser.error("Missing configured PHP source header: " + str(src / header))
    if '#define PHP_VERSION "5.6.40"' not in (src / "main/php_version.h").read_text():
        parser.error("--src must be a PHP 5.6.40 source tree")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    extension = output / "php56_probe.so"
    includes = [src, src / "main", src / "Zend", src / "TSRM", src / "ext", src / "ext/date/lib"]
    command = (shlex.split(args.cc) + shlex.split(args.cflags) + ["-fPIC", "-shared", "-DCOMPILE_DL_PHP56_PROBE=1"]
               + ["-I" + str(path) for path in includes] + [str(source), "-o", str(extension)])
    evidence = {
        "scope": "PHP 5.6.40 native CLI boundary checks; not a remote exploit or RCE proof",
        "src": str(src), "php": str(php), "host": platform.platform(),
        "machine": platform.machine(), "python": sys.version,
        "sha256": {str(path): sha256(path) for path in
                   [source, Path(__file__).resolve(), php, src / "main/php_config.h",
                    src / "main/php_version.h", src / "Zend/zend_modules.h", src / "Zend/zend_alloc.h",
                    src / "Zend/zend_alloc.c", src / "Zend/zend_operators.c", src / "main/php_variables.c"]},
        "cases": {},
    }

    def finish(code):
        evidence["passed"] = code == 0
        (output / "result.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"output": str(output), "passed": code == 0,
                          "cases": {key: value.get("passed") for key, value in evidence["cases"].items()}}))
        return code

    evidence["build"] = run(command, output, "build", timeout=120)
    if evidence["build"]["exit_code"] != 0:
        return finish(1)
    evidence["sha256"][str(extension)] = sha256(extension)
    if args.compile_only:
        evidence["scope"] += "; compile-only, no PHP or runtime test executed"
        evidence["runtime_executed"] = False
        return finish(0)
    evidence["runtime_executed"] = True
    env = os.environ.copy()
    # Pin the allocator used by the tested branch. An inherited USE_ZEND_ALLOC=0
    # would silently change the meaning of the ordinary memory_limit control.
    env["USE_ZEND_ALLOC"] = "1"
    # Keep the test callback mapped until libc runs atexit handlers. Otherwise
    # Zend's normal module teardown may dlclose the extension before atexit.
    # This changes library unloading only, not the allocator or request path.
    env["ZEND_DONT_UNLOAD_MODULES"] = "1"
    evidence["test_environment"] = {"USE_ZEND_ALLOC": "1", "ZEND_DONT_UNLOAD_MODULES": "1"}
    base = [str(php), "-n", "-d", "extension=" + str(extension), "-d", "display_errors=stderr",
            "-d", "log_errors=0", "-d", "memory_limit=-1"]

    def php_case(name, body):
        php_marker = output / (name + ".php-shutdown.marker")
        native_marker = output / (name + ".native-atexit.marker")
        prefix = ("if (!php56_probe_arm_atexit(" + json.dumps(str(native_marker)) + ")) { exit(90); }\n"
                  "register_shutdown_function(function () { file_put_contents(" + json.dumps(str(php_marker))
                  + ", \"php-shutdown\\n\"); });\n")
        script = output / (name + ".php")
        script.write_text("<?php\n" + prefix + body + "\n")
        result = run(base + [str(script)], output, name, env)
        result["php_shutdown"] = php_marker.exists()
        result["native_atexit"] = native_marker.exists()
        evidence["cases"][name] = result
        return result

    info = run(base + ["-r", "echo json_encode(php56_probe_build_info()), \"\\n\";"], output, "build-info", env)
    evidence["build_info_execution"] = info
    try:
        evidence["build_info"] = json.loads(info["stdout"])
        valid_info = (info["exit_code"] == 0 and evidence["build_info"]["php_version"] == "5.6.40"
                      and evidence["build_info"]["module_api"] == 20131226)
    except (KeyError, ValueError):
        valid_info = False
    if not valid_info:
        return finish(1)

    for name, body, expected_exit in (
        ("normal_exit_control", "echo \"normal\\n\";", 0),
        ("ordinary_fatal_control", "trigger_error(\"ordinary-fatal-control\", E_USER_ERROR);", 255),
    ):
        result = php_case(name, body)
        result["classification"] = "real CLI execution; lifecycle marker positive control"
        result["passed"] = result["exit_code"] == expected_exit and result["php_shutdown"] and result["native_atexit"]

    for name, diagnostic in (
        ("safe_mul_overflow", "Possible integer overflow in memory allocation"),
        ("safe_add_overflow", "Possible integer overflow in memory allocation"),
        ("safe_string_int_max", "String allocation overflow"),
        ("system_malloc_size_max", "Out of memory"),
        ("synthetic_concat_separate", "String size overflow"),
        ("synthetic_concat_in_place", "String size overflow"),
        ("synthetic_add_string", "String size overflow"),
        ("synthetic_add_char", "String size overflow"),
        ("synthetic_concat_negative", "String size overflow"),
    ):
        result = php_case(name, "php56_probe_boundary(" + json.dumps(name) + ");")
        if name.startswith("synthetic_"):
            result["classification"] = "synthetic string metadata boundary probe; no real giant string or remote exploit"
        elif name == "system_malloc_size_max":
            result["classification"] = "real libc malloc(SIZE_MAX) failure; impossible size, not physical RAM exhaustion or injected failure"
        else:
            result["classification"] = "real allocator API boundary call, no huge allocation required"
        result["passed"] = (result["exit_code"] == 1 and diagnostic in result["stderr"]
                            and not result["php_shutdown"] and not result["native_atexit"])

    table = run(base + ["-r", "echo json_encode(php56_probe_input_tables()), \"\\n\";"], output, "input-tables", env)
    table["classification"] = "real php_register_variable_safe calls and ZE2 HashTable metadata inspection"
    expected = {
        "root_empty": (8, 0, 0), "ordinary_empty": (8, 0, 0), "ordinary_one": (8, 7, 1),
        "root_one": (8, 7, 1), "nested_one": (2, 1, 1), "nested_two": (2, 1, 2),
        "nested_three": (4, 3, 3), "nested_overwrite": (4, 3, 3),
        "append_outer_one": (2, 1, 1), "append_inner_one": (2, 1, 1),
        "numeric_three": (4, 3, 3), "scalar_replaced_by_array": (2, 1, 1),
    }
    table["expected_snapshots"] = {key: dict(zip(("capacity", "mask", "elements"), values))
                                   for key, values in expected.items()}
    table["expected_registered"] = {
        "nested": {"first": "replacement", "second": "two", "third": "three"},
        "append": [{"leaf": "value"}], "numeric": ["zero", "one", "two"], "replace": {"leaf": "array"},
    }
    try:
        table["decoded"] = json.loads(table["stdout"])
        table["passed"] = (table["exit_code"] == 0 and table["decoded"]["snapshots"] == table["expected_snapshots"]
                           and table["decoded"]["registered"] == table["expected_registered"])
    except (KeyError, ValueError):
        table["passed"] = False
    evidence["cases"]["input_tables"] = table
    return finish(0 if all(case["passed"] for case in evidence["cases"].values()) else 1)


if __name__ == "__main__":
    sys.exit(main())
