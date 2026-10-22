#!/usr/bin/env python3
"""Benign FastCGI lifecycle checks; only a private Unix socket is used."""

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import tempfile
import time


def record(kind, payload=b""):
    padding = (-len(payload)) % 8
    return struct.pack("!BBHHBB", 1, kind, 1, len(payload), padding, 0) + payload + b"\0" * padding


def pair(name, value):
    name, value = name.encode(), value.encode()
    def length(n):
        return bytes([n]) if n < 128 else struct.pack("!I", n | 0x80000000)
    return length(len(name)) + length(len(value)) + name + value


def recv_exact(sock, count):
    data = b""
    while len(data) < count:
        piece = sock.recv(count - len(data))
        if not piece:
            return None
        data += piece
    return data


def request(address, script, query="", body=b"", content_type=None, length=True, extra_params=None):
    params = {
        "GATEWAY_INTERFACE": "CGI/1.1", "SERVER_SOFTWARE": "backport-tests",
        "SERVER_PROTOCOL": "HTTP/1.1", "SERVER_NAME": "localhost",
        "SERVER_ADDR": "127.0.0.1", "SERVER_PORT": "0",
        "REMOTE_ADDR": "127.0.0.1", "REMOTE_PORT": "1",
        "REQUEST_METHOD": "POST" if content_type else "GET",
        "SCRIPT_FILENAME": str(script), "SCRIPT_NAME": "/probe.php",
        "REQUEST_URI": "/probe.php?" + query, "QUERY_STRING": query,
    }
    if extra_params:
        params.update(extra_params)
    if content_type:
        params["CONTENT_TYPE"] = content_type
    if length:
        params["CONTENT_LENGTH"] = str(len(body))
    output, error, ended = bytearray(), bytearray(), False
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(20)
        sock.connect(str(address))
        sock.sendall(record(1, struct.pack("!HB5x", 1, 0)))
        sock.sendall(record(4, b"".join(pair(k, v) for k, v in params.items())) + record(4))
        try:
            for offset in range(0, len(body), 65535):
                sock.sendall(record(5, body[offset:offset + 65535]))
            sock.sendall(record(5))
        except (BrokenPipeError, ConnectionResetError):
            pass  # Expected when a fail-stop worker dies while reading a body.
        while True:
            try:
                header = recv_exact(sock, 8)
                if header is None:
                    break
                version, kind, ident, count, padding, unused = struct.unpack("!BBHHBB", header)
                payload = recv_exact(sock, count)
                if payload is None:
                    break
                recv_exact(sock, padding)
            except (ConnectionResetError, BrokenPipeError):
                break
            if kind == 6:
                output.extend(payload)
            elif kind == 7:
                error.extend(payload)
            elif kind == 3:
                ended = True
                break
    raw = output.decode("utf-8", "replace")
    data = raw.partition("\r\n\r\n")[2]
    return {"raw": raw, "body": data, "stderr": error.decode("utf-8", "replace"), "ended": ended}


def result_json(response):
    return json.loads(response["body"])


def multipart(parts):
    boundary = "php70-security-benign-boundary"
    data = bytearray()
    for name, value, filename in parts:
        data.extend(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + name + "\"").encode())
        if filename is not None:
            data.extend(("; filename=\"" + filename + "\"\r\nContent-Type: text/plain").encode())
        data.extend(b"\r\n\r\n" + value + b"\r\n")
    data.extend(("--" + boundary + "--\r\n").encode())
    return bytes(data), "multipart/form-data; boundary=" + boundary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fpm", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect-baseline", action="store_true")
    parser.add_argument("--system-allocator", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    process = None
    with tempfile.TemporaryDirectory(prefix="php70-fpm-", dir="/tmp") as temporary:
        root = Path(temporary)
        address = root / "fpm.sock"
        script = root / "probe.php"
        marker = root / "shutdown-marker"
        session = root / "sessions"
        session.mkdir()
        script.write_text("""<?php
$action = isset($_GET['action']) ? $_GET['action'] : 'normal';
if ($action === 'fatal' || $action === 'oom') {
    register_shutdown_function(function () { file_put_contents(__DIR__ . '/shutdown-marker', 'called'); });
    if ($action === 'fatal') {
        set_error_handler(function () { return false; });
        set_exception_handler(function ($e) {});
        trigger_error('benign lifecycle probe', E_USER_ERROR);
    }
    $data = str_repeat('x', 64 * 1024 * 1024);
    echo 'UNREACHABLE';
} else {
    $result = array('pid' => getmypid());
    if ($action === 'session') {
        session_id('backportprobe'); session_start();
        $_SESSION['count'] = isset($_SESSION['count']) ? $_SESSION['count'] + 1 : 1;
        $result['session_count'] = $_SESSION['count']; session_write_close();
    }
    if ($action === 'upload') {
        $result['post'] = $_POST; $result['files'] = array();
        foreach ($_FILES as $key => $file) {
            $result['files'][$key] = array('error' => $file['error'], 'name' => $file['name'],
                'data' => is_uploaded_file($file['tmp_name']) ? file_get_contents($file['tmp_name']) : null);
        }
    }
    if ($action === 'progress') {
        session_id('progressprobe'); session_start();
        $result['has_progress'] = isset($_SESSION['upload_progress_benign']); session_write_close();
    }
    header('Content-Type: application/json'); echo json_encode($result);
}
""")
        config = root / "fpm.conf"
        config.write_text("""[global]
daemonize = no
error_log = {root}/fpm.log
log_level = notice
[probe]
user = nobody
group = nogroup
listen = {socket}
pm = static
pm.max_children = 1
pm.max_requests = 0
catch_workers_output = yes
clear_env = no
php_admin_value[memory_limit] = 16M
php_admin_value[post_max_size] = 64M
php_admin_value[upload_max_filesize] = 1M
php_admin_value[session.save_path] = {session}
php_admin_value[session.upload_progress.enabled] = 1
php_admin_value[session.upload_progress.cleanup] = 0
php_admin_value[display_errors] = 1
php_admin_value[log_errors] = 1
""".format(root=root, socket=address, session=session))
        # Run an unprivileged child against only this private directory.
        root.chmod(0o777)
        session.chmod(0o777)
        environment = dict(os.environ)
        if args.system_allocator:
            environment["USE_ZEND_ALLOC"] = "0"
        else:
            environment.pop("USE_ZEND_ALLOC", None)
        logfile = output.with_suffix(".fpm.log")
        with logfile.open("wb") as logs:
            process = subprocess.Popen([args.fpm, "-n", "-F", "-R", "-y", str(config)], stdout=logs, stderr=logs, env=environment)
            try:
                for unused in range(100):
                    if address.exists():
                        break
                    if process.poll() is not None:
                        raise RuntimeError("FPM startup failed: " + logfile.read_text())
                    time.sleep(0.05)
                def call(query="", **kwargs):
                    return request(address, script, query, **kwargs)
                first = result_json(call())
                pid = first["pid"]
                for unused in range(5):
                    assert result_json(call())["pid"] == pid
                results.append({"check": "five consecutive normal requests use same worker", "pid": pid, "pass": True})
                for expected in (1, 2):
                    response = result_json(call("action=session"))
                    assert response["pid"] == pid and response["session_count"] == expected, response
                results.append({"check": "normal session write and read", "pass": True})
                body, kind = multipart([("field", b"value", None), ("upload", b"benign upload\n", "probe.txt")])
                response = result_json(call("action=upload", body=body, content_type=kind))
                assert response["post"] == {"field": "value"} and response["files"]["upload"] == {"error": 0, "name": "probe.txt", "data": "benign upload\n"}, response
                results.append({"check": "ordinary multipart field and file", "pass": True})
                # Bounded parser-memory pressure with unknown headers only.
                # There are no objects, addresses, shell commands or gadgets.
                header_boundary = "benign-header-pressure"
                body = (b"--" + header_boundary.encode() + b"\r\n" +
                        b"X-Ignored: x\r\n" * 150000 +
                        b'Content-Disposition: form-data; name="field"\r\n\r\nvalue\r\n--' +
                        header_boundary.encode() + b"--\r\n")
                response = call("action=upload", body=body, content_type="multipart/form-data; boundary=" + header_boundary)
                after = result_json(call())
                if args.expect_baseline:
                    assert after["pid"] != pid, (response, after)
                else:
                    assert result_json(response)["post"] == {"field": "value"} and after["pid"] == pid, (response, after)
                results.append({"check": "unknown multipart headers do not accumulate retained memory", "before_pid": pid, "after_pid": after["pid"], "pass": True})
                pid = after["pid"]
                body, kind = multipart([("PHPSESSID", b"progressprobe", None), ("PHP_SESSION_UPLOAD_PROGRESS", b"benign", None), ("upload", b"x", "probe.txt")])
                response = result_json(call("action=progress", body=body, content_type=kind))
                assert response["has_progress"] == args.expect_baseline, response
                results.append({"check": "upload progress honors mitigation even when configured on", "has_progress": response["has_progress"], "pass": True})
                fatal = call("action=fatal")
                assert "benign lifecycle probe" in fatal["body"] and marker.exists(), fatal
                marker.unlink()
                assert result_json(call())["pid"] == pid
                results.append({"check": "ordinary fatal cleanup and safe worker reuse", "pid": pid, "pass": True})
                # A deprecated iconv INI emits a benign diagnostic before RINIT.
                early = call(extra_params={"PHP_VALUE": "error_reporting=32767\niconv.input_encoding=UTF-8"})
                offset = early["body"].find('{"pid"')
                assert offset >= 0, early
                early_data, unused = json.JSONDecoder().raw_decode(early["body"][offset:])
                assert early_data["pid"] == pid, early
                diagnostic = early["raw"] + early["stderr"] + logfile.read_text(errors="replace")
                if (root / "fpm.log").exists():
                    diagnostic += (root / "fpm.log").read_text(errors="replace")
                assert "iconv.input_encoding is deprecated" in diagnostic, early
                results.append({"check": "early PHP_VALUE diagnostic after fatal and handlers", "pid": pid, "pass": True})
                if not args.system_allocator:
                    oom = call("action=oom")
                    after = result_json(call())
                    if args.expect_baseline:
                        assert marker.exists() and after["pid"] == pid, (oom, after)
                    else:
                        assert not marker.exists() and after["pid"] != pid, (oom, after)
                    results.append({"check": "script memory_limit OOM matches expected lifecycle", "before_pid": pid, "after_pid": after["pid"], "shutdown_called": marker.exists(), "pass": True})
                    if marker.exists():
                        marker.unlink()
                    pid = after["pid"]
                    # A large plain field triggers OOM during request startup,
                    # without manipulating layouts, dangling pointers or objects.
                    body, kind = multipart([("large", b"x" * (32 * 1024 * 1024), None)])
                    startup_oom = call("action=upload", body=body, content_type=kind)
                    after = result_json(call())
                    # PHP 7.0 FPM already retires a child after a failed startup;
                    # the new hard stop additionally protects cleanup itself.
                    assert after["pid"] != pid, (startup_oom, after)
                    assert result_json(call("action=session"))["session_count"] == 3
                    results.append({"check": "startup multipart OOM cannot reuse worker", "before_pid": pid, "after_pid": after["pid"], "pass": True})
                else:
                    results.append({"check": "memory_limit OOM", "skip": "USE_ZEND_ALLOC=0 intentionally disables Zend memory_limit"})
            finally:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if (root / "fpm.log").exists():
                    with logfile.open("ab") as logs:
                        logs.write((root / "fpm.log").read_bytes())
    output.write_text(json.dumps({"baseline": args.expect_baseline, "system_allocator": args.system_allocator, "checks": results}, indent=2) + "\n")
    print(json.dumps({"output": str(output), "checks_passed": len([r for r in results if r.get("pass")])}))


if __name__ == "__main__":
    main()
