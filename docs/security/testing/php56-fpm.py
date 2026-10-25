#!/usr/bin/env python3
"""Exercise the PHP 5.6 mitigation through one isolated FPM worker.

Use the FPM built from this branch, inside the same network-disabled container
used for the build. This program uses only an AF_UNIX FastCGI socket; it starts
and stops its own FPM master. Every generated file is retained below the supplied
evidence directory. It does not run a remote exploit or inject allocator faults.

Example:
  python3 docs/security/testing/php56-fpm.py \
    --fpm /work/.security-build/hardened/src/sapi/fpm/php-fpm \
    --evidence-dir /work/.security-build/results/fpm-debug --skip-early-ini

Omit --skip-early-ini for a build configured with iconv. The early diagnostic
case requires a real Zend E_DEPRECATED from iconv.input_encoding, rather than
an FPM configuration error that never enters Zend error handling.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import traceback


FCGI_BEGIN_REQUEST = 1
FCGI_END_REQUEST = 3
FCGI_PARAMS = 4
FCGI_STDIN = 5
FCGI_STDOUT = 6
FCGI_STDERR = 7
SID = "php56-cve2026regression"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fcgi_record(kind, data=b""):
    padding = (-len(data)) % 8
    return struct.pack("!BBHHBB", 1, kind, 1, len(data), padding, 0) + data + b"\0" * padding


def fcgi_length(length):
    if length < 128:
        return bytes([length])
    return struct.pack("!I", length | 0x80000000)


def recv_exact(connection, length):
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            return bytes(data)
        data.extend(chunk)
    return bytes(data)


def config_string(value):
    value = str(value)
    if any(ord(character) < 32 for character in value):
        raise ValueError("FPM configuration paths must not contain control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


PHP_SCRIPT = r'''<?php
define('EVIDENCE_DIR', @@EVIDENCE@@);
header('Content-Type: application/json');
function answer($values) {
    $values['pid'] = getmypid();
    $values['php_version'] = PHP_VERSION;
    $values['sapi'] = PHP_SAPI;
    echo json_encode($values), "\n";
}
function started($name) {
    file_put_contents(EVIDENCE_DIR . '/' . $name . '.started.json',
        json_encode(array('pid' => getmypid(), 'memory_limit' => ini_get('memory_limit'))));
}
$action = isset($_GET['action']) ? $_GET['action'] : 'probe';
switch ($action) {
case 'probe':
    answer(array('ok' => true, 'iconv' => extension_loaded('iconv'),
        'session' => extension_loaded('session'), 'json' => extension_loaded('json'),
        'upload_progress_ini' => ini_get('session.upload_progress.enabled')));
    break;
case 'session-write':
    session_start();
    $_SESSION['ordinary'] = array('value' => 'retained', 'count' => 1);
    $sid = session_id();
    session_write_close();
    answer(array('session_id' => $sid));
    break;
case 'session-read':
    session_start();
    $values = $_SESSION;
    $sid = session_id();
    session_write_close();
    answer(array('session_id' => $sid, 'values' => $values));
    break;
case 'upload':
    session_start();
    $progress = isset($_SESSION['upload_progress_security-test']);
    $ordinary = isset($_SESSION['ordinary']) ? $_SESSION['ordinary'] : null;
    session_write_close();
    $upload = isset($_FILES['sample']) ? $_FILES['sample'] : null;
    $valid = $upload && $upload['error'] === UPLOAD_ERR_OK;
    answer(array('field' => isset($_POST['field']) ? $_POST['field'] : null,
        'progress_exists' => $progress, 'ordinary_session' => $ordinary,
        'upload_progress_ini' => ini_get('session.upload_progress.enabled'),
        'filename' => $upload ? $upload['name'] : null,
        'upload_error' => $upload ? $upload['error'] : null,
        'size' => $upload ? $upload['size'] : null,
        'is_uploaded_file' => $valid && is_uploaded_file($upload['tmp_name']),
        'contents' => $valid ? file_get_contents($upload['tmp_name']) : null));
    break;
case 'fatal':
    register_shutdown_function(function () {
        file_put_contents(EVIDENCE_DIR . '/ordinary.shutdown.marker',
            (string)getmypid() . "\n", FILE_APPEND);
    });
    started('ordinary');
    trigger_error('PHP56_FPM_ORDINARY_FATAL', E_USER_ERROR);
    echo 'UNREACHABLE';
    break;
case 'seed-handlers':
    set_error_handler(function ($number, $message) {
        file_put_contents(EVIDENCE_DIR . '/previous-handler.marker', $message . "\n", FILE_APPEND);
        return false;
    });
    set_exception_handler(function ($exception) {
        file_put_contents(EVIDENCE_DIR . '/previous-exception-handler.marker',
            $exception->getMessage() . "\n", FILE_APPEND);
    });
    answer(array('handlers_installed' => true));
    break;
case 'oom':
    register_shutdown_function(function () {
        file_put_contents(EVIDENCE_DIR . '/oom.shutdown.marker', (string)getmypid() . "\n");
    });
    class OomCleanup {
        public function __destruct() {
            file_put_contents(EVIDENCE_DIR . '/oom.destructor.marker', (string)getmypid() . "\n");
        }
    }
    $cleanup = new OomCleanup;
    started('oom');
    $buffer = str_repeat('x', 32 * 1024 * 1024);
    echo 'UNREACHABLE';
    break;
default:
    answer(array('unknown_action' => $action));
}
'''


class Harness:
    def __init__(self, arguments, evidence):
        self.arguments = arguments
        self.evidence = evidence
        self.socket_path = evidence / "fpm.sock"
        self.script = evidence / "request.php"
        self.process = None
        self.output_stream = None
        self.request_number = 0
        self.result = {
            "status": "running",
            "pass": False,
            "evidence_dir": str(evidence),
            "checks": [],
            "scope": "Real PHP 5.6.40 FPM requests; one static worker; AF_UNIX only; no fault injection",
        }

    def check(self, name, condition, **details):
        self.result["checks"].append(dict(check=name, status="passed" if condition else "failed", **details))
        if not condition:
            raise AssertionError(name + ": " + json.dumps(details, sort_keys=True))

    def logs(self):
        return "\n".join(
            path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            for path in self.log_paths()
        )

    def log_paths(self):
        return [self.evidence / name for name in ("fpm.log", "php-error.log", "master-output.log")]

    def log_snapshot(self):
        return {path: path.stat().st_size if path.exists() else 0 for path in self.log_paths()}

    def logs_since(self, offsets):
        excerpts = []
        for path, offset in offsets.items():
            if path.exists():
                with path.open("rb") as stream:
                    stream.seek(offset)
                    excerpt = stream.read().decode("utf-8", errors="replace")
                    if excerpt:
                        excerpts.append("=== " + path.name + " ===\n" + excerpt)
        return "\n".join(excerpts)

    def wait_for(self, predicate, description):
        deadline = time.monotonic() + self.arguments.timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if self.process.poll() is not None:
                raise RuntimeError("FPM master exited while waiting for " + description)
            time.sleep(0.05)
        raise TimeoutError("Timed out waiting for " + description)

    def start(self):
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError("AF_UNIX path is too long; supply a shorter evidence directory: " + str(self.socket_path))
        for name in ("sessions", "uploads", "tmp", "requests"):
            (self.evidence / name).mkdir()
        quoted_php_path = "'" + str(self.evidence).replace("\\", "\\\\").replace("'", "\\'") + "'"
        self.script.write_text(PHP_SCRIPT.replace("@@EVIDENCE@@", quoted_php_path), encoding="utf-8")
        config = "\n".join([
            "[global]",
            "daemonize = no",
            "error_log = " + config_string(self.evidence / "fpm.log"),
            "pid = " + config_string(self.evidence / "master.pid"),
            "log_level = notice",
            "[security-test]",
            "listen = " + config_string(self.socket_path),
            "listen.mode = 0600",
            "pm = static",
            "pm.max_children = 1",
            "pm.max_requests = 0",
            "catch_workers_output = yes",
            "clear_env = no",
            "request_terminate_timeout = 0",
            "rlimit_core = 0",
            "chdir = " + config_string(self.evidence),
            "security.limit_extensions = .php",
            "php_admin_flag[log_errors] = on",
            "php_admin_flag[display_errors] = off",
            "php_admin_flag[html_errors] = off",
            "php_admin_value[error_log] = " + config_string(self.evidence / "php-error.log"),
            "php_admin_value[date.timezone] = UTC",
            "php_value[error_reporting] = 32767",
            "php_value[memory_limit] = 32M",
            "php_value[max_execution_time] = 0",
            "php_value[cgi.fix_pathinfo] = 0",
            "php_value[always_populate_raw_post_data] = -1",
            "php_value[session.save_handler] = files",
            "php_value[session.save_path] = " + config_string(self.evidence / "sessions"),
            "php_value[session.use_cookies] = 1",
            "php_value[session.use_only_cookies] = 1",
            "php_value[session.use_strict_mode] = 0",
            "php_value[session.gc_probability] = 0",
            "php_value[session.upload_progress.enabled] = 1",
            "php_value[session.upload_progress.cleanup] = 0",
            "php_value[session.upload_progress.name] = PHP_SESSION_UPLOAD_PROGRESS",
            "php_value[session.upload_progress.prefix] = upload_progress_",
            "php_value[session.upload_progress.freq] = 0",
            "php_value[file_uploads] = 1",
            "php_value[upload_tmp_dir] = " + config_string(self.evidence / "uploads"),
            "",
        ])
        config_path = self.evidence / "fpm.conf"
        config_path.write_text(config, encoding="utf-8")
        binary = Path(self.arguments.fpm).resolve()
        version = subprocess.run([str(binary), "-n", "-v"], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, check=False, timeout=self.arguments.timeout)
        (self.evidence / "binary-version.log").write_bytes(version.stdout)
        if version.returncode != 0:
            raise RuntimeError("FPM -n -v failed; see binary-version.log")
        command = [str(binary), "-n", "-F", "-y", str(config_path)]
        if os.geteuid() == 0:
            command.append("-R")
        self.result.update(binary=str(binary), binary_sha256=sha256(binary),
                           harness_sha256=sha256(Path(__file__)), command=command)
        self.output_stream = (self.evidence / "master-output.log").open("wb")
        environment = dict(os.environ, USE_ZEND_ALLOC="1", TMPDIR=str(self.evidence / "tmp"))
        self.process = subprocess.Popen(command, cwd=str(self.evidence), env=environment,
                                        stdout=self.output_stream, stderr=subprocess.STDOUT,
                                        start_new_session=True)
        self.result["master_pid"] = self.process.pid
        self.wait_for(self.socket_path.exists, "FPM Unix socket")

    def request(self, action, body=b"", content_type=None, php_value=None):
        self.request_number += 1
        prefix = self.evidence / "requests" / ("%02d-%s" % (self.request_number, action))
        query = "action=" + action
        parameters = {
            "GATEWAY_INTERFACE": "CGI/1.1", "SERVER_SOFTWARE": "php56-regression-harness",
            "SERVER_PROTOCOL": "HTTP/1.1", "REQUEST_METHOD": "POST" if body else "GET",
            "SCRIPT_FILENAME": str(self.script), "SCRIPT_NAME": "/request.php",
            "DOCUMENT_ROOT": str(self.evidence), "REQUEST_URI": "/request.php?" + query,
            "QUERY_STRING": query, "SERVER_NAME": "localhost", "SERVER_PORT": "80",
            "REMOTE_ADDR": "127.0.0.1", "REMOTE_PORT": "12345",
            "CONTENT_LENGTH": str(len(body)), "HTTP_COOKIE": "PHPSESSID=" + SID,
        }
        if content_type:
            parameters["CONTENT_TYPE"] = content_type
        if php_value:
            parameters["PHP_VALUE"] = php_value
        encoded = bytearray()
        for key, value in parameters.items():
            key_bytes, value_bytes = key.encode("utf-8"), value.encode("utf-8")
            encoded += fcgi_length(len(key_bytes)) + fcgi_length(len(value_bytes)) + key_bytes + value_bytes
        wire = fcgi_record(FCGI_BEGIN_REQUEST, struct.pack("!HB5x", 1, 0))
        for offset in range(0, len(encoded), 65535):
            wire += fcgi_record(FCGI_PARAMS, encoded[offset:offset + 65535])
        wire += fcgi_record(FCGI_PARAMS)
        for offset in range(0, len(body), 65535):
            wire += fcgi_record(FCGI_STDIN, body[offset:offset + 65535])
        wire += fcgi_record(FCGI_STDIN)
        prefix.with_suffix(".request.json").write_text(json.dumps(parameters, indent=2) + "\n", encoding="utf-8")
        prefix.with_suffix(".request-body.bin").write_bytes(body)
        response = {"action": action, "ended": False, "termination": "eof"}
        output, errors = bytearray(), bytearray()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.arguments.timeout)
                connection.connect(str(self.socket_path))
                connection.sendall(wire)
                while True:
                    header = recv_exact(connection, 8)
                    if not header:
                        break
                    if len(header) != 8:
                        raise RuntimeError("Truncated FastCGI record header")
                    version, kind, request_id, length, padding, unused = struct.unpack("!BBHHBB", header)
                    if version != 1 or request_id != 1:
                        raise RuntimeError("Unexpected FastCGI version or request ID")
                    data = recv_exact(connection, length)
                    if len(data) != length or len(recv_exact(connection, padding)) != padding:
                        raise RuntimeError("Truncated FastCGI record content")
                    if kind == FCGI_STDOUT:
                        output += data
                    elif kind == FCGI_STDERR:
                        errors += data
                    elif kind == FCGI_END_REQUEST:
                        if len(data) != 8:
                            raise RuntimeError("Invalid FastCGI END_REQUEST")
                        app_status, protocol_status = struct.unpack("!IB3x", data)
                        response.update(ended=True, termination="end_request", app_status=app_status,
                                        protocol_status=protocol_status)
                        break
        except (ConnectionResetError, BrokenPipeError) as error:
            response["termination"] = type(error).__name__
        finally:
            prefix.with_suffix(".stdout.bin").write_bytes(output)
            prefix.with_suffix(".stderr.bin").write_bytes(errors)
            write_json(prefix.with_suffix(".response.json"), response)
        response["stdout"] = bytes(output)
        response["stderr"] = bytes(errors)
        return response

    def json_request(self, action, **arguments):
        response = self.request(action, **arguments)
        if not response["ended"] or response.get("protocol_status") != 0 or response.get("app_status") != 0:
            raise AssertionError("Incomplete or unsuccessful FastCGI response: " + action)
        raw = response["stdout"]
        separator = b"\r\n\r\n" if b"\r\n\r\n" in raw else b"\n\n"
        headers, found, body = raw.partition(separator)
        if not found:
            raise AssertionError("Missing CGI response headers: " + action)
        if re.search(br"(?im)^Status:\s*[45]\d\d", headers):
            raise AssertionError("HTTP error response: " + action)
        values = json.loads(body.decode("utf-8"))
        if values.get("php_version") != "5.6.40" or values.get("sapi") != "fpm-fcgi":
            raise AssertionError("Expected the branch PHP 5.6.40 FPM binary: " + str(values))
        return values

    def run(self):
        if self.arguments.early_ini_only:
            first = self.json_request("probe")
            self.check("iconv is present for the real early INI diagnostic", first["iconv"])
            seeded = self.json_request("seed-handlers")
            before = self.log_snapshot()
            early = self.json_request("probe", php_value="iconv.input_encoding=UTF-8")
            self.wait_for(lambda: "Use of iconv.input_encoding is deprecated" in self.logs_since(before),
                          "iconv early INI diagnostic")
            diagnostic = self.logs_since(before)
            (self.evidence / "early-ini-diagnostic.log").write_text(diagnostic, encoding="utf-8")
            after = self.json_request("probe")
            self.check("early diagnostic actually executed on the same worker",
                       first["pid"] == seeded["pid"] == early["pid"] == after["pid"], pid=after["pid"])
            self.check("previous request handlers are not called by early diagnostics",
                       not (self.evidence / "previous-handler.marker").exists()
                       and not (self.evidence / "previous-exception-handler.marker").exists())
            self.result.update(scope="ordinary early INI diagnostic comparison; no OOM or upload-progress test executed",
                               status="passed", **{"pass": True})
            return
        initial = [self.json_request("probe") for unused in range(5)]
        pid = initial[0]["pid"]
        self.check("five consecutive requests use the same worker", all(item["pid"] == pid for item in initial), pid=pid)
        self.check("required Session and JSON extensions are present", initial[0]["session"] and initial[0]["json"])
        written = self.json_request("session-write")
        read = self.json_request("session-read")
        expected_session = {"ordinary": {"value": "retained", "count": 1}}
        self.check("normal Session roundtrip on the same worker",
                   written["session_id"] == SID and read["session_id"] == SID
                   and read["values"] == expected_session and written["pid"] == read["pid"] == pid,
                   pid=read["pid"])

        boundary = "php56-security-harness"
        parts = []
        for name, value in (("PHPSESSID", "ignored-form-sid"),
                            ("PHP_SESSION_UPLOAD_PROGRESS", "security-test"), ("field", "normal-field")):
            parts.append("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, name, value))
        parts.append('--%s\r\nContent-Disposition: form-data; name="sample"; filename="sample.txt"\r\n'
                     'Content-Type: text/plain\r\n\r\nupload-data\n\r\n--%s--\r\n' % (boundary, boundary))
        upload = self.json_request("upload", body="".join(parts).encode("ascii"),
                                   content_type="multipart/form-data; boundary=" + boundary)
        self.check("normal multipart field and uploaded file",
                   upload["pid"] == pid and upload["field"] == "normal-field" and upload["upload_error"] == 0
                   and upload["filename"] == "sample.txt" and upload["size"] == 12
                   and upload["contents"] == "upload-data\n" and upload["is_uploaded_file"] is True,
                   pid=upload["pid"])
        self.check("built-in upload progress stays disabled with INI enabled",
                   upload["upload_progress_ini"] == "1" and upload["progress_exists"] is False
                   and upload["ordinary_session"] == expected_session["ordinary"])

        fatal = self.request("fatal")
        self.wait_for(lambda: (self.evidence / "ordinary.shutdown.marker").exists(), "ordinary fatal shutdown callback")
        fatal_started = json.loads((self.evidence / "ordinary.started.json").read_text())
        after_fatal = self.json_request("probe")
        self.check("ordinary fatal calls shutdown and keeps the same worker",
                   fatal["ended"] and fatal_started["pid"] == after_fatal["pid"] == pid
                   and "PHP56_FPM_ORDINARY_FATAL" in self.logs(), pid=after_fatal["pid"])

        seeded = self.json_request("seed-handlers")
        self.check("error and exception handlers can be installed before the next request",
                   seeded["handlers_installed"] and seeded["pid"] == pid)
        if self.arguments.skip_early_ini:
            self.result["checks"].append({"check": "early PHP_VALUE Zend diagnostic after handlers",
                                          "status": "skipped", "reason": "Explicit --skip-early-ini; rerun with iconv enabled"})
        else:
            self.check("iconv is present for the real early INI diagnostic", initial[0]["iconv"])
            before = self.log_snapshot()
            early = self.json_request("probe", php_value="iconv.input_encoding=UTF-8")
            self.wait_for(lambda: "Use of iconv.input_encoding is deprecated" in self.logs_since(before),
                          "iconv early INI diagnostic")
            diagnostic = self.logs_since(before)
            (self.evidence / "early-ini-diagnostic.log").write_text(diagnostic, encoding="utf-8")
            after_early = self.json_request("probe")
            self.check("early PHP_VALUE Zend diagnostic and subsequent requests keep the same worker",
                       early["pid"] == after_early["pid"] == pid
                       and not (self.evidence / "previous-handler.marker").exists()
                       and not (self.evidence / "previous-exception-handler.marker").exists(), pid=after_early["pid"])

        oom = self.request("oom", php_value="memory_limit=8M")
        started = json.loads((self.evidence / "oom.started.json").read_text())
        self.check("OOM request actually entered the original worker at memory_limit 8M",
                   started["pid"] == pid and started["memory_limit"] == "8M", pid=started["pid"])
        exit_pattern = re.compile(r"child\s+%d\s+exited with code 1\b" % pid)
        self.wait_for(lambda: bool(exit_pattern.search(self.logs())), "FPM logging old child exit code 1")
        after_oom = self.json_request("probe")
        following = self.json_request("probe")
        self.check("OOM exits child with code 1 and master supplies a stable replacement",
                   not oom["ended"] and self.process.poll() is None and after_oom["pid"] != pid
                   and following["pid"] == after_oom["pid"] and "Allowed memory size" in self.logs(),
                   old_pid=pid, new_pid=after_oom["pid"], master_pid=self.process.pid,
                   fastcgi_termination=oom["termination"])
        self.check("OOM bypasses PHP shutdown callbacks and destructors",
                   not (self.evidence / "oom.shutdown.marker").exists()
                   and not (self.evidence / "oom.destructor.marker").exists())
        recovered = self.json_request("session-read")
        self.check("normal Session data survives worker replacement",
                   recovered["pid"] == after_oom["pid"] and recovered["session_id"] == SID
                   and recovered["values"] == expected_session, pid=recovered["pid"])
        self.result["pass"] = True
        self.result["status"] = "passed_with_skips" if self.arguments.skip_early_ini else "passed"

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGQUIT)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait(timeout=5)
            self.result["master_exit_status_after_cleanup"] = self.process.returncode
        if self.output_stream is not None:
            self.output_stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fpm", required=True, help="PHP 5.6.40 FPM binary built from this branch")
    parser.add_argument("--evidence-dir", required=True, help="Retain all generated files under this directory")
    parser.add_argument("--timeout", type=float, default=15, help="Seconds per request or lifecycle wait (default: 15)")
    parser.add_argument("--early-ini-only", action="store_true", help="Only compare ordinary early INI diagnostics; no OOM or upload-progress case")
    parser.add_argument("--skip-early-ini", action="store_true", help="Explicitly leave the iconv-dependent early INI case unverified")
    arguments = parser.parse_args()
    if arguments.timeout <= 0:
        parser.error("--timeout must be positive")
    binary = Path(arguments.fpm).resolve()
    if not binary.is_file() or not os.access(str(binary), os.X_OK):
        parser.error("--fpm must point to an executable file")
    root = Path(arguments.evidence_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="fpm-", dir=str(root)))
    harness = Harness(arguments, evidence)
    try:
        harness.start()
        harness.run()
    except Exception as error:
        harness.result.update(status="failed", **{"pass": False}, error=str(error))
        (evidence / "harness-error.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        try:
            harness.stop()
        except Exception as error:
            harness.result.update(status="failed", **{"pass": False}, cleanup_error=str(error))
        write_json(evidence / "results.json", harness.result)
    print(json.dumps(harness.result, indent=2, sort_keys=True))
    return 0 if harness.result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
