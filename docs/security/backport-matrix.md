# PHP 7.0.33 security backport matrix

Research date: 2026-10-22. This is a source-level adaptation plan for an
**unofficial PHP 7.0.33 security backport**, not evidence of a complete fix or a
new PHP project release. Runtime results belong in [verification.md](verification.md).

## Pinned evidence and scope

| Source | Exact revision | Authority and use |
| --- | --- | --- |
| PHP 7.0.33 target | `bf574c2b67a1f786e36cf679f41b758b973a82c4` | Local unmodified baseline; `main/php_version.h` reports `7.0.33`. |
| PHP 7.4 EOL mitigation | [`712e60f9edfd03f0960fc4fc3c2c375f42b90aa2`](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2), parent `004cb827501d1ddaf98daacb185a53e0816f78a7` | Official source on `PHP-7.4-CVE-2026-109618-109619`; commit explicitly describes a minimal mitigation for EOL versions. All 17 changed files were inspected. |
| PHP 8.0 EOL mitigation | [`82f8f31b16a035c1b67cc253e79f7cc288f4cc20`](https://github.com/php/php-src/commit/82f8f31b16a035c1b67cc253e79f7cc288f4cc20), parent `670052c427eb08a67577789e3b00e56a4fd640a7` | Official source on `PHP-8.0-CVE-2026-109618-109619`, rather than the ordinary `PHP-8.0` branch; same 17 changed files and same EOL strategy. |
| PHP 7.1 community adaptation | [PR #24500](https://github.com/php/php-src/pull/24500), base `1d9205b665d898453cdd32036ad9b687cf6278fe`, implementation [`ec412a8051824bf84d03bb30f892ba212f748dd8`](https://github.com/php/php-src/commit/ec412a8051824bf84d03bb30f892ba212f748dd8) | Community reference only. PR was closed without merging. The maintainer declined a release for unsupported 7.1. Its 36-file aggregate diff includes tests and release metadata. |
| PHP 7.1 PR second commit | [`2a00e50a69682745e7fb42f6ec92836973ba6ffe`](https://github.com/php/php-src/commit/2a00e50a69682745e7fb42f6ec92836973ba6ffe) | Changes the version to `7.1.34`. Do not copy this release claim or versioning into 7.0. |
| Supported PHP complete fix | [`01a40e89fbfc499936e3b05888d8f00bfde886df`](https://github.com/php/php-src/commit/01a40e89fbfc499936e3b05888d8f00bfde886df), PHP 8.2.35 | Architectural reference: delayed OOM, VM unwind, hard memory limit, and broader global reset. It is not the direct transplantation target. |
| Official advisories | [CVE-2026-109618](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w), [CVE-2026-109619](https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp), [PHP announcement](https://www.php.net/archive/2026.php) | Security claims and limits. Session upload progress is one producer/consumer path, not the whole stale-global vulnerability class. |

The upstream file inventory, not the initial task checklist, is authoritative.
In particular, `Zend/zend_llist.c`, `Zend/zend_multiply.h`,
`Zend/zend_strtod.c`, `main/SAPI.c`, `main/php_variables.c`, and
`Zend/zend_API.h` are necessary review items. PHP 7.0 additionally needs
`Zend/zend_API.c` and `Zend/zend_string.h` because later convenience APIs and
the string length bound do not exist in this baseline.

## Why PHP 8.0 and PHP 7.4 use a different strategy from supported PHP

The 7.4 and 8.0 patches route allocator failures and related integer-overflow
fatal paths to `zend_mm_safe_error_ex()`, which formats into a fixed stack
buffer, writes to stderr, and calls `_exit(1)`. It does not run PHP error
handlers, shutdown functions, request destructors, or process `atexit`
handlers. This makes an unsafe partial operation unable to continue into
cleanup or another request in that worker. Normal successful allocations
retain their existing semantics. Availability changes: an FPM master must
replace the exited child, and in-process SAPIs lose the containing worker.

Supported PHP 8.2 uses `zend_mm_check_limit()` to queue a delayed soft OOM;
allocation can complete so code can establish a consistent state. At a safe
point the engine raises an unwind exit. A second hard limit terminates the
process. Its broader reset also covers many extensions and startup consumers.
PHP 7.0 has neither that allocator state nor that VM protocol. Adding them
would exceed this minimal backport and risk Zend structure/ABI changes.
Matching an EOL mitigation is therefore not equivalent to porting the
complete supported-version state-reset fix.

## Complete 17-file official patch disposition

“No layout change” below means the proposed patch does not add, remove,
reorder, or resize public structure fields. It is not a claim that arbitrary
third-party extensions have been tested. Test names describe required
coverage; execution status is recorded separately.

| Official file / mechanism | PHP 7.4 and 8.0 logic | PHP 7.1 adaptation | PHP 7.0 source facts, adaptation and final decision | ABI / behavior / verification |
| --- | --- | --- | --- | --- |
| `Zend/zend_API.h` — singleton input array | Add `array_init_singleton()` using `zend_new_array_singleton()`. | Declare `_array_init_singleton()` and use the older file/line API. | 7.0 `array_init()` calls `_array_init()`; there is no `zend_new_array()` API. Use 7.1's wrapper pattern with a new implementation in `zend_API.c`. | Additive function/macro only; no existing signature or layout change. Test first string/integer key, growth, COW, serialize, sort, delete/reinsert. |
| `Zend/zend_alloc.c` — fail-stop | Add fixed-buffer `zend_mm_safe_error_ex()`, use it from `zend_mm_safe_error()` and integer-overflow failures; change allocator panic and system-allocation failure termination from `exit()` to `_exit()`. | Move declarations to start of block; add missing huge-allocation rounding overflow check. | Same central `zend_mm_safe_error()` exists, including the old error/bailout/reentry sequence. Replace that sequence. Existing filename/line accessors are available. 7.0 huge allocation has no `new_size < size` guard; add it before limit checks. Preserve GC retry and successful allocation paths. | Additive exported helper; private heap layout unchanged. OOM now exits immediately. Test memory-limit exhaustion, physical allocation failure if controllable, debug build, system-allocation path, and FPM child replacement. |
| `Zend/zend_alloc.h` — helper declaration | Declare `zend_mm_safe_error_ex()` inside C linkage. | Same declaration. | Directly applicable; needed by multiply/string/VM/hash callers and extensions compiling those headers. | Additive export; check declarations on normal/debug compilers and extension loading. |
| `Zend/zend_execute_API.c` — shutdown state | Clear user error/exception handlers and stacks on the fast-shutdown branch; reset error-handling mode and exception; clear object-store buckets and top. | No corresponding 7.4 fast-shutdown branch; append unconditional resets after shutdown work. | 7.0 `shutdown_executor()` uses several `zend_try` blocks. Handlers can survive an interrupted destructor. Clear the same fields after those blocks. `zend_objects_store_destroy()` normally nulls buckets but does not reset `top`, and can be bypassed by bailout; set buckets NULL and top 1 unconditionally. Do not copy weakref or fast-shutdown APIs. | No field/layout changes. The final reset abandons already invalid request state rather than calling more destructors. Test normal/fatal sessions, handlers, shutdown diagnostics, same-worker requests. Residual pre-RINIT consumers still require audit. |
| `Zend/zend_hash.c` — capacity failures and singleton constructor | Route `zend_hash_check_size()`, packed growth and hash resize overflow to fail-stop; add `zend_new_array_singleton()` with one-bucket initial size. | Route the three overflow sites; move singleton constructor to `zend_API.c`. | Same three overflow sites exist. Use `zend_mm_safe_error_ex()`. Keep 7.0's existing allocation representation and use the API helper for singleton creation. | No HashTable layout changes. Correct 7.0's existing `%zu`/`uint32_t` diagnostic mismatch when touching these sites. Require debug tests of packed→hash conversion and one→two→many growth. |
| `Zend/zend_hash.h` — singleton declaration | Add declaration of `zend_new_array_singleton()`. | Not changed; older API adaptation is declared in `zend_API.h`. | **No change required** because that 7.4 constructor does not exist. The equivalent exported declaration is in `zend_API.h`. | Explicitly mapped, not silently omitted. |
| `Zend/zend_llist.c` — destroy tombstones | After destroying nodes, null `head` and `tail`, then clear count. | Same. | Directly applicable to 7.0 `zend_llist_destroy()`; prevents reachable list endpoints retaining freed nodes on normal completion. | No struct change. Normal list and request shutdown regressions; this alone cannot make a destructor interrupted by fatal error safe. |
| `Zend/zend_multiply.h` — size arithmetic | `zend_safe_address_guarded()` and `zend_safe_addmult()` use fail-stop rather than an error bailout. | Same. | Same helpers exist. Change both fatal paths; do not change arithmetic or successful results. | Inline API code changes but no signatures/layout changes. Exercise `safe_emalloc` overflow in a bounded native harness where possible. |
| `Zend/zend_strtod.c` — dtoa allocation | Both `Balloc()` allocation-failure branches call the fail-stop helper. | Same. | Same branches exist; change both. Preserve lock release before termination. | No ABI change. Number/string conversion regressions; deterministic native allocation failure injection if available. |
| `Zend/zend_types.h` — small hash reset | SSE `HT_HASH_RESET` assumes at least 64 bytes; use `memset` below 64 for singleton hash tables. | No change; older implementation already uses `memset`. | **No change required**: 7.0 `HT_HASH_RESET` is already generic `memset` over `HT_HASH_SIZE`. It accepts a one-bucket hash. `HT_HASH_RESET_PACKED` still reserves its two-index prefix through `HT_MIN_MASK=-2`. | No layout change; do not transplant SSE code. Validate both string-key singleton and packed integer-key growth under debug/ASan. |
| `Zend/zend_vm_def.h` — concat overflow | Fail-stop existing/additional `ZSTR_MAX_LEN` guards on `CONCAT` and `FAST_CONCAT` allocation paths. | Add three guards; older FAST_CONCAT implementation has fewer optimized paths. | 7.0 lacks `ZSTR_MAX_LEN` and all corresponding guards. Add the macro in `zend_string.h`, then guard both CONCAT paths and the FAST_CONCAT allocation path present in 7.0. Do not import later opcode implementations. | No VM struct changes. Ordinary concat, referenced values, CV/TMP/CONST operands, and overflow harness. |
| `Zend/zend_vm_execute.h` — generated handlers | Regenerate corresponding specialized handlers. | Regenerate with 7.1's own generator; aggregate diff contains a minor generator formatting difference. | Regenerate with **7.0's** `Zend/zend_vm_gen.php` after editing `zend_vm_def.h`; inspect that all generated guards match. Never paste a 7.4/8.0 generated header. | No opcode numbering or calling convention change. Build and run VM tests; deterministic regeneration is a release check. |
| `ext/session/session.c` — upload progress | Keep chaining `php_session_rfc1867_orig_callback`, then unconditionally return before Session progress logic even if enabled in INI. | Same behavior, uses `|| 1` rather than `|| true`. | 7.0 callback chaining and `PS(rfc1867_progress)` access order match. Force return before reading/creating progress state. Preserve the original callback chain and normal Session RINIT/RSHUTDOWN behavior. Existing upload-progress INI must not re-enable the feature. | Deliberate feature removal from this build. Session structures unchanged. Test enabled and disabled INI, ordinary session read/write, ordinary upload; update obsolete positive upload-progress tests transparently. Third-party callback chain remains a separate lifecycle trust boundary. |
| `main/SAPI.c` — freed pointers | After `efree`, set request-info auth user/password/digest, content-type duplicate and current-user pointers to NULL. | Same. | Same members and cleanup blocks exist. Directly reuse pointer resets. | No SAPI structure/signature change. Same-worker authentication, content-type and ordinary request regressions. |
| `main/main.c` — request tombstones / part directive | Add `max_multipart_body_parts` for 7.4; undefine each destroyed HTTP global; reset `modules_activated` at end of shutdown. 8.0 already has its multipart part-count directive. | Same 7.4 additions. | Same shutdown loops/flag exist. Add unbound INI entry rather than adding a core-global field. Undefine zvals after successful destruction and reset activation flag at end. OOM exits; other fatal interruption can still bypass individual destructors and must not be assumed fully covered. | No `php_core_globals` layout change. New system/per-directory directive. Test startup/shutdown and boundary requests. |
| `main/php_variables.c` — reduce input memory amplification | Replace four input-array initialization sites with singleton initialization (three nested paths and initial POST/GET/COOKIE array). | Same locations with older destructor APIs preserved. | Corresponding sites exist. Change initialization only, preserve 7.0 `zval_dtor`/`zval_ptr_dtor`, symbol-table and parsing semantics. | No API/layout change; smaller initial allocation is observable only through memory behavior. Test deep nesting, repeated fields, arrays, cookies, GET, POST, growth/COW. |
| `main/rfc1867.c` — parser amplification | Retain only first Content-Disposition/Content-Type; ignore unused/duplicate headers; use `size_t` in `substring_conf`; 7.4 adds multipart part limit with default input+upload limits. 8.0 already has part-count machinery. | Same, places declarations at start of scope. | Directly map header filter and static-function width fixes. Count all parts with Content-Disposition, including `filename=""`, before allocating field/file metadata; use the existing common cleanup label. Adapt counter types safely as described below. | Only private helper signatures change. Intended compatibility changes: new part ceiling and bounded retained header count. Test first relevant header wins, folded headers, unused headers, empty files, normal files/fields and limit cleanup. This does not impose a total streamed body-byte ceiling. |

## Additional PHP 7.0 adaptation files

| File | Required adaptation | Reason, risk and test |
| --- | --- | --- |
| `Zend/zend_API.c` | Implement `_array_init_singleton()` by `_array_init(arg, 0 ...)`, then set `Z_ARRVAL_P(arg)->nTableSize = 1`. | Reuses 7.0's initialized metadata and destructor fields. `array_init_size(1)` alone is insufficient: `zend_hash_check_size()` rounds it to `HT_MIN_SIZE=8`. No struct changes. The 7.1 reference uses exactly this older API pattern. Require small-array mutation/COW tests. |
| `Zend/zend_string.h` | Add `ZSTR_MAX_LEN` as `SIZE_MAX - ZEND_MM_ALIGNED_SIZE(_ZSTR_HEADER_SIZE + 1)`. | Available in later versions and added by 7.1 PR; bounds concatenation while allowing space for header, NUL and alignment. Macro only; no string representation changes. Actual 7.0 allocation arithmetic and supported platforms must compile. |
| New/updated PHPT and integration tests | Add OOM no-cleanup, singleton arrays, Session progress disabled, duplicate/ignored headers, multipart limits, and same-worker lifecycle/FPM tests; adjust expectations for deliberately changed OOM behavior. | 7.1 adds useful test inputs, but its tests do not establish PHP 7.0 security. Upload-progress tests that assert removed behavior must be explicitly updated/identified; do not hide unrelated failures. |
| Security and release documentation | Record provenance, feature loss, worker exit behavior, limitations and exact commands/results. | Do not copy the 7.1 PR's unofficial `7.1.34` metadata or suggest PHP 7.0 is supported. Retain PHP 7.0 API/version identity and label artifacts as unofficial backports. |

## OOM entrance equivalence and coverage limits

PHP 7.0 uses the same main fail-stop interception point as the 7.4 EOL patch:

```text
emalloc / ecalloc / erealloc
  -> Zend MM allocation/reallocation
  -> new chunk / huge allocation / growing huge reallocation
  -> GC retry where already implemented
  -> zend_mm_safe_error() on finite limit or failed OS allocation
  -> [patched] zend_mm_safe_error_ex() -> _exit(1)

safe_emalloc / safe_malloc and HashTable / concat overflow
  -> guarded arithmetic failure
  -> [patched] zend_mm_safe_error_ex() -> _exit(1)

persistent/system zend_malloc / zend_realloc failure
  -> zend_out_of_memory() -> [patched] _exit(1)
```

Evidence at the unmodified 7.0 baseline: `zend_mm_safe_error()` at
`Zend/zend_alloc.c:375`; new-chunk limit/system failures near lines 1032–1052;
huge-realloc limit near lines 1535–1537; huge allocation limit/system failure
near lines 1781–1801; `_emalloc()` near line 2465; `zend_out_of_memory()` and
system wrappers near lines 2874–2902. These are baseline positions and may
move after changes.

This is not one universal entrance for every extension allocation. Custom
Zend MM handlers (`zend_mm_set_custom_handlers`), raw `malloc()` users,
third-party extension error paths, and OS-level process termination have
their own contracts. `USE_ZEND_ALLOC=0` reaches the system wrappers; it must
not be assumed to enforce PHP's finite `memory_limit`. Allocation overflow
guards in hash/string/VM/multiply are distinct paths and must all be mapped.
Normal application `E_ERROR`, parse failure and timeout are not allocator
failure and must not all be changed into `_exit()` indiscriminately.

An existing binary extension can remain loadable while retaining the old
header-inlined overflow paths from its original build, notably
`zend_safe_address_guarded()` and `zend_safe_addmult()`. Loading such an
extension without an ABI error is not evidence that those call sites use
the patched fail-stop helper. Rebuild third-party extensions against the
patched headers for that coverage; record the extension inventory and
tested binaries separately. Intercepting every ordinary fatal error to
compensate would change semantics beyond the official minimal patch and
is not part of this adaptation.

The fixed-buffer reporter avoids Zend allocation and `zend_error()`
recursion. It still calls libc formatting/stderr functions, matching the
official minimal backport; do not claim async-signal safety or prove freedom
from arbitrary heap corruption from this alone. A no-limit compile
configuration (`ZEND_MM_LIMIT=0`) requires extra build review: the 7.0
conditional call sites use a different argument form and must compile with
the helper's declaration. Record any untested build configuration.

## Multipart counter adaptation and remaining streamed-body gap

Upstream 7.4 uses `int` counters and a predecrement. PHP 7.0's `INI_INT()`
returns `zend_long`; truncating extreme configuration values to `int`,
adding input and upload limits without checking overflow, or decrementing a
minimum signed value is avoidable undefined/implementation-defined
behavior. Use a `zend_long` part counter, saturate the derived nonnegative
sum at `ZEND_LONG_MAX`, and compare with zero before decrementing. Keep
default `-1` semantics and honor explicit nonnegative part limits. This is
a narrow arithmetic adaptation, not a new upload policy; boundary tests
must include zero, default, explicit and large values.

The existing 7.0 RFC1867 `fill_buffer()` calls `sapi_module.read_post()`
directly and increments `SG(read_post_bytes)`. It does **not** use
`sapi_read_standard_form_data()`'s post-read limit enforcement. The initial
`rfc1867_post_handler()` check compares `Content-Length` with
`SG(post_max_size)` only. The official minimal 7.4/8.0 changes do not add a
streamed decoded-byte check. Therefore an unavailable/inaccurate
Content-Length is not made safe merely by this parser backport. Retained
header count and multipart part limits reduce amplification; very large
headers/field bodies can still consume memory and cause the patched worker
to fail-stop. Enforce decoded body size in the front end for deployments;
any additional core stream limit must be separately designed and tested,
rather than claimed as already supplied by this patch.

## Lifecycle limitations and release decision

The official stale-state advisory includes non-OOM fatal interruptions and
nonfatal diagnostics during late cleanup, plus early INI diagnostics in
some SAPIs. Disabling Session upload progress removes its known early
producer/consumer, and the explicit Executor/SAPI/core/list resets remove
specific stale references. The preserved original multipart callback can
still execute before module RINIT; third-party callbacks and other early
extension entry points cannot be declared safe by disabling Session alone.

FPM's startup-failure behavior also matters: a multipart startup failure
already makes the FPM child exit; the public advisory distinguishes this
from mod_php and from FPM application-stage producer paths. Reusing an FPM
child after a successful request, failing during startup, failing after
startup, and master replacement are separate integration-test cases.

Decision: port every applicable mechanism of the official EOL mitigation,
with the PHP 7.0 adaptations above, while keeping Zend layouts/API numbers
unchanged. Do not introduce PHP 8's delayed-OOM VM state or present this as
the complete supported-version fix. A source review or successful compile
does not qualify the result for release. Until new security tests, required
regressions, worker lifecycle checks, and memory instrumentation have real
results, this remains a candidate unofficial mitigation with documented
coverage limits.
