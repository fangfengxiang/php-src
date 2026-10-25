# PHP 5.6 native boundary probe

`php56_probe.c` is a disposable CLI test extension, compiled from scratch by
`../php56-native.py` against the configured headers of the selected source tree.
It must not be installed in a serving PHP process. It deliberately terminates
individual child processes to inspect the patched failure path.

Run inside the `linux/amd64` build container with this branch's CLI:

```sh
python3 /work/docs/security/testing/php56-native.py \
  --src /work/.security-build/x64-hardened/src \
  --output /work/.security-build/evidence/x64-hardened-native
```

The output directory must not exist. `--compile-only` builds the extension and
records source/header/binary SHA-256 digests without executing PHP. The harness
records the complete compiler and CLI argument arrays, stdout, stderr, timeouts,
exit status, marker presence, expected observations, and a combined `result.json`.
It requires PHP 5.6.40 / module API 20131226; no host PHP or PHP 7 extension is used.

Coverage and interpretation:

- `safe_emalloc(SIZE_MAX, 2, 0)` and `(1, SIZE_MAX, 1)` call the real multiply and
  addition overflow guards. `safe_emalloc_string(1, INT_MAX, 1)` calls the real
  ZE2 string-length guard without allocating a giant string.
- `pemalloc(SIZE_MAX, 1)` uses the branch's freshly compiled inline system
  allocation wrapper. The impossible request makes the real system `malloc`
  fail; this is neither physical memory exhaustion nor injected failure.
- Concat/add-string/add-char checks use deliberately synthetic length metadata
  and tiny buffers to reach guards. These test guard ordering only. They are
  not real huge-string workloads, remote inputs, or evidence of an RCE exploit.
- `php_register_variable_safe` creates actual nested, appended, numeric and
  scalar-replacement arrays. Snapshots inspect capacity, mask and element count
  through insertion and growth. The ordinary array/root table remains 8 buckets
  (mask 0 before allocation, 7 after insertion); input child tables start at 2
  buckets (mask 1 after insertion) and grow to 4 on the third distinct element.
  Duplicate-key overwrite and registered values are checked too. No table
  metadata is modified by the probe.
- Every failure case must exit 1 with its expected diagnostic and bypass both
  PHP shutdown and C `atexit` markers. Normal exit and ordinary user fatal are
  positive controls proving both markers work. Each case has its own CLI process.

The harness pins `USE_ZEND_ALLOC=1` and `ZEND_DONT_UNLOAD_MODULES=1`. The latter
keeps the extension's `atexit` callback mapped through normal process exit;
without it Zend may unload the extension before libc calls its callback. This
setting does not intercept allocation or alter request shutdown. Its value is
recorded in the JSON evidence.

This probe does not cover FPM/mod_php request reuse, physical host OOM, ZTS,
32-bit/Windows targets, or arbitrary third-party allocators. A passing result
must not be presented as proof that those targets or a remote exploit were tested.
