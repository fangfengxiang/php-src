#!/usr/bin/env bash
# Build a fresh source copy inside an existing, fixed toolchain container.
# This script installs nothing and makes no network requests. Use --network none
# on the container invocation; record its image digest with the run evidence.
set -euo pipefail

usage() {
    echo "Usage: $0 --src SOURCE --output NEW_DIR --mode Debug|Release --compiler clang|cc [--jobs N]" >&2
    exit 2
}

src= output= mode= compiler= jobs=2
while [[ $# -gt 0 ]]; do
    [[ $# -ge 2 ]] || usage
    case "$1" in
        --src) src=$2 ;;
        --output) output=$2 ;;
        --mode) mode=$2 ;;
        --compiler) compiler=$2 ;;
        --jobs) jobs=$2 ;;
        *) usage ;;
    esac
    shift 2
done
[[ -n "$src" && -n "$output" && "$mode" =~ ^(Debug|Release)$ && "$compiler" =~ ^(clang|cc)$ && "$jobs" =~ ^[1-9][0-9]*$ ]] || usage

# Python performs logging and provenance recording, including failed builds.
exec python3 - "$src" "$output" "$mode" "$compiler" "$jobs" <<'PY'
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

src, output = [Path(value).resolve() for value in sys.argv[1:3]]
mode, compiler, jobs = sys.argv[3:6]
if not (src / "main/php_version.h").is_file() or '#define PHP_VERSION "5.6.40"' not in (src / "main/php_version.h").read_text():
    raise SystemExit("--src must be a fresh PHP 5.6.40 source copy")
if any((src / path).exists() for path in ("Makefile", "sapi/cli/php", "sapi/cgi/php-cgi", "sapi/fpm/php-fpm")):
    raise SystemExit("Use a fresh source copy, not an existing configured or built tree")
if not shutil.which(compiler) or not shutil.which("make"):
    raise SystemExit("Compiler and make must already be installed in the fixed toolchain")
output.mkdir(parents=True, exist_ok=False)
env = os.environ.copy()
# Configure determines Debug/Release flags. Do not inherit local build overrides.
for key in ("CFLAGS", "CPPFLAGS", "LDFLAGS", "CONFIG_SITE", "EXTRA_CFLAGS", "EXTRA_LDFLAGS", "MAKEFLAGS"):
    env.pop(key, None)
env.update({"CC": compiler, "LC_ALL": "C", "CONFIG_SITE": "/dev/null"})
evidence = {"src": str(src), "output": str(output), "mode": mode, "compiler": compiler,
            "machine": platform.machine(), "host": platform.platform(), "commands": [],
            "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "network": "No dependency installation/download commands; caller must disable container networking",
            "passed": False}

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def run(name, command, required=True):
    with (output / (name + ".log")).open("wb") as log:
        result = subprocess.run(command, cwd=src, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    evidence["commands"].append({"name": name, "argv": command, "cwd": str(src), "exit_code": result.returncode})
    if required and result.returncode:
        raise RuntimeError(name + " failed; see " + str(output / (name + ".log")))

code = 1
try:
    evidence["source_sha256"] = {name: sha(src / name) for name in ("configure.in", "main/php_version.h", "Zend/zend_alloc.c", "Zend/zend_operators.c", "main/php_variables.c", "main/rfc1867.c", "ext/session/session.c")}
    for name, command in (("compiler-version", [compiler, "--version"]), ("make-version", ["make", "--version"]),
                          ("autoconf-version", [env.get("PHP_AUTOCONF", "autoconf"), "--version"]),
                          ("bison-version", ["bison", "--version"])):
        if shutil.which(command[0]):
            run(name, command, required=False)
    if shutil.which("dpkg-query"):
        run("installed-packages", ["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], required=False)
    if not (src / "configure").is_file():
        run("buildconf", ["./buildconf", "--force"])
    configure = ["./configure", "--disable-all", "--enable-cli", "--enable-cgi", "--enable-fpm", "--enable-session", "--enable-filter", "--enable-json", "--with-iconv", "--without-pear"]
    if mode == "Debug":
        configure.append("--enable-debug")
    configure.append("CC=" + compiler)
    run("configure", configure)
    run("make", ["make", "-j" + jobs])
    evidence["binary_sha256"] = {name: sha(src / path) for name, path in
        (("cli", "sapi/cli/php"), ("cgi", "sapi/cgi/php-cgi"), ("fpm", "sapi/fpm/php-fpm"))}
    evidence["configuration_sha256"] = {name: sha(src / name) for name in ("config.nice", "main/php_config.h", "Makefile")}
    for name in ("config.nice", "main/php_config.h", "Makefile"):
        shutil.copy2(src / name, output / Path(name).name)
    evidence["passed"] = True
    code = 0
except (OSError, RuntimeError) as error:
    evidence["error"] = str(error)
finally:
    evidence["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "build.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "passed": evidence["passed"], "error": evidence.get("error")}))
sys.exit(code)
PY
