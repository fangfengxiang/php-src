# PHP 7.0.33 security backport: root cause and lifecycle audit

分析日期：2026-10-22。此文件先于 C 源码修改完成。

基线为 `php-7.0.33`，提交
`bf574c2b67a1f786e36cf679f41b758b973a82c4`。以下 `文件:行` 均指这个
**未修改基线**，避免补丁插入行导致证据漂移。永久源码链接格式为
[`php/php-src@bf574c2`](https://github.com/php/php-src/tree/bf574c2b67a1f786e36cf679f41b758b973a82c4)。
最终补丁的适配决策见 `backport-matrix.md`；动态验证结果另见
`verification.md`。静态审计不等于漏洞完整修复或可发布证明。

## 证据等级与上游边界

* **官方事实**：PHP 官方公告和 PHP 项目的安全公告、提交。
* **源码事实**：基线中可定位的控制流、字段和分配器行为。
* **推断**：由源码建立的潜在生产者/消费者关系，未运行复现时不能标为确认可利用。
* **背景文章**：用户提供的解释和图片用于提出审计问题，不作为补丁正确性依据。

[PHP 官方 2026-10-21 公告](https://www.php.net/archive/2026.php)
提供 PHP 7.4、8.0、8.1 的最小源码回移植；PHP 7.0 没有官方修复发布。
本项目只能称作 **PHP 7.0.33 非官方安全回移植版本**，不涵盖其停止维护后的
其他漏洞。

[CVE-2026-109618 官方公告](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w)
描述 OOM 非局部跳转使中间状态被析构，当前受支持版本使用 VM 安全点延迟处理
soft OOM，并在 hard OOM 时立即终止。该设计不能直接等同于旧分支的最小回移植。

[CVE-2026-109619 官方公告](https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp)
将问题定义为请求内存释放后仍存在全局引用，后续请求在正常初始化之前消费它；
已确认的消费者包括早期 INI 诊断和 Session Upload Progress。

[PHP 7.4 官方修复 712e60f9ed](https://github.com/php/php-src/commit/712e60f9ed)
提交题为 `Avoid state corruption via bailout`，明确标为 EOL 版本的最小缓解。
应逐文件移植其机制，不把 PHP 8 的 VM 或结构布局复制到 PHP 7.0。

## 从所有权和可达性推导防御不变量

PHP 的 worker 比请求活得久。`PS(...)`、`EG(...)`、`PG(...)` 和扩展全局槽位
可以持续存在；其保存的字符串、数组、对象、引用和回调可能属于请求堆。
“worker 全局槽位仍存在”不代表“槽位指向的对象仍存在”。

1. 结构被发布到符号表、数组或全局槽位时，必须已经满足所有读取和析构不变量。
   发布后再分配内存的代码，不能假定后面的初始化一定执行。
2. 请求堆释放之前必须解除 worker 对请求对象的全部可达引用；销毁旧对象与重置
   槽位是两项不同操作。清理本身也可能触发诊断、回调或 bailout。
3. 正常 RINIT 的重置太晚，不能保护发生于 RINIT 之前的消费者。
4. 对不可信中间状态，如果无法证明安全清理，终止 worker 是合理的 fail-stop
   边界。`_exit()` 避免继续运行 PHP 析构和 C `atexit` 回调。
5. 限制 multipart 资源消耗只能减少触发条件；不能代替 allocator fail-stop 与
   跨请求状态重置。只禁用 Session Upload Progress 也不能覆盖全部消费者。

这些是不变量和本项目的防御目标，不是“所有扩展已经满足”的结论。

## PHP 7.0.33 的真实请求调用链

以下链针对正常的非 `APACHE_HOOKS` 分支；历史 hooks 分支见
`main/main.c:1661`、`:1693`，其 `php_start_sapi()` 会先激活模块，不能混同。

```text
SAPI 建立请求信息 / 应用早期 INI 配置
  FPM: init_request_info()                 sapi/fpm/fpm/fpm_main.c:1020,1397,1899
  mod_php: apply_config(conf)              sapi/apache2handler/sapi_apache2.c:577
php_request_startup()                      main/main.c:1581
  PG(modules_activated) = 0                :1607
  zend_activate()                         :1612; Zend/zend.c:955
    gc_reset(), init_compiler()
    init_executor()                       Zend/zend_execute_API.c:128
      VM stack, symbol table
      zend_extension_activator callbacks  :155
      exception/object state setup
    startup_scanner()
  sapi_activate()                         main/main.c:1613; main/SAPI.c:438
    sapi_read_post_data()                  main/SAPI.c:180,475
      select POST entry / post_reader / default_post_reader
    read_cookies(), sapi_module.activate()
    sapi_module.input_filter_init()       main/SAPI.c:487
  output handler / buffer setup           main/main.c:1632
  php_hash_environment()                  main/main.c:1649; main/php_variables.c:667
    memset(PG(http_globals), 0, ...)
    zend_activate_auto_globals()          Zend/zend_compile.c:1557
      non-JIT _POST callback              main/php_variables.c:693,850
        sapi_module.treat_data(PARSE_POST) :701
          php_default_treat_data()        :367,403 (or mbstring replacement)
            sapi_handle_post()            main/SAPI.c:171
              rfc1867_post_handler()      main/rfc1867.c:688
                multipart callbacks / filters / mbstring callbacks
  zend_activate_modules()                 main/main.c:1650; Zend/zend_API.c:2536
    extension RINIT handlers
  PG(modules_activated) = 1                main/main.c:1651
application execution
php_request_shutdown()                    main/main.c:1781
```

`sapi_read_post_data()` 的 reader 与真正 `post_handler` 是两个阶段，不能说
`sapi_activate()` 必然已经完成 multipart 解析。multipart 注册项在
`main/php_content_types.c:24`；其 body handler 由 `_POST` 的非 JIT 初始化触发。
若 `variables_order` 不含 `P`，`php_auto_globals_create_post()` 不走正常 POST
处理分支；因此审计必须明确配置前提。

### 关闭顺序及失败路径

`php_request_startup()` 包含 `zend_try`；catch 只把返回值设为 `FAILURE`
(`main/main.c:1652`)，不会局部修复每个模块的发布状态。

```text
php_request_shutdown()                    main/main.c:1781
  current_execute_data = NULL
  user shutdown functions                 :1795 (modules_activated gate)
  object destructors                      :1800 (no module gate)
  output buffers, timeout reset
  zend_deactivate_modules()               :1827 (modules_activated gate)
    extension RSHUTDOWN handlers           Zend/zend_API.c:2567
  output deactivation, shutdown-function table
  http_globals destructors                main/main.c:1842 (no module gate)
  php_free_request_globals()              :1852
  zend_deactivate()                       :1855; Zend/zend.c:975
    shutdown_executor()                   Zend/zend_execute_API.c:250
    INI deactivation / compiler / resource cleanup
  post-RSHUTDOWN callbacks                 main/main.c:1859
  sapi_deactivate()                       :1864
  virtual cwd / streams
  shutdown_memory_manager(..., 0)          :1877 (no module gate)
```

`zend_try` 只是为某段清理捕获 bailout，使后续清理有机会继续；它不是事务回滚。
部分 RINIT 已执行后发生 bailout，`modules_activated` 仍可能为 0，RSHUTDOWN
集合仍可能跳过。单个 RSHUTDOWN fatal 也可能跳过其后处理。

**SAPI 差异必须保留**：PHP 7.0 FPM 的启动失败分支关闭 FastCGI、调用
`php_module_shutdown()` 并返回 `FPM_EXIT_SOFTWARE`
(`sapi/fpm/fpm/fpm_main.c:1905`)；它不会把这个 child 留在正常接收循环。
mod_php 在外层 `zend_end_try` 后调用 `php_apache_request_dtor()`，后者总是调用
`php_request_shutdown()` (`sapi/apache2handler/sapi_apache2.c:516,629,687,690`)。
因此背景文章中的“启动期 OOM 后同 worker 接第二个请求”不能直接套用于 FPM。
FPM 仍须检查成功 startup 后发布状态再 fatal 的路径，以及早于 startup 的 INI
消费者；启动失败退出不构成一般免疫证明。

## CVE-2026-109618：中间状态与 OOM 控制流

源码事实：`_zend_bailout()` 设置 `CG(unclean_shutdown)`、清除当前执行位置后
`LONGJMP(*EG(bailout), FAILURE)` (`Zend/zend.c:911-926`)。它不会沿调用栈逐层
执行 C 清理，也不会为调用者自动恢复字段不变量。

一个可审计的结构例子是 HashTable。PHP 7.0 `_zend_hash_init()` 设置
`nNumUsed`、`nTableMask`、`arData`、`pDestructor` 等字段
(`Zend/zend_hash.c:173`)；真正分配 buckets 的 `zend_hash_real_init_ex()`
(`:130`) 和 grow (`:187`) 会发生可失败分配。`zend_hash_destroy()`
(`:1248`) 相信 `nNumUsed`、`arData`、flags 和 `pDestructor` 已经一致，并依此
遍历或调用析构函数。数组和 zval 的发布顺序必须逐处对照上游补丁，不能通过
“只是 OOM，正常清理应当没问题”来证明安全。

### PHP 7.0 allocator 的覆盖面

```text
emalloc / ecalloc / safe_emalloc / erealloc / specialized emalloc
  -> _emalloc() / _zend_mm_alloc()         Zend/zend_alloc.c:2463,2312
    -> zend_mm_alloc_heap()               :1373
      small -> alloc_small_slow -> alloc_pages
      large -> alloc_pages
      huge  -> zend_mm_alloc_huge          :1762
    realloc -> zend_mm_realloc_heap       :1471 (huge growth at :1530)
      limit exceeded / underlying chunk mapping failed
        -> zend_mm_safe_error()           :375
          heap->overflow = 1
          zend_error_noreturn(E_ERROR, ...)
          catch; overflow = 0; zend_bailout()
```

`alloc_pages` 的 limit 与底层分配失败路径见 `:1027-1055`；huge 分配见
`:1776-1804`；huge realloc limit 见 `:1530-1543`。这些是真正需要改变恢复语义的
请求 allocator 路径。`heap->overflow` 让错误报告期间越过通常 limit 检查；错误
处理可能分配内存，故不可在新 fail-stop helper 中重新调用 PHP 的常规错误链。

**只改这个 static 函数不够**。以下入口还须独立核对官方改动：

| 入口 | 基线证据 | 处理要求 |
| --- | --- | --- |
| Debug 对齐/元数据尺寸溢出 | `Zend/zend_alloc.c:1383` | 不经 `zend_mm_safe_error`，不能漏测 Debug。 |
| `_estrdup` / `_estrndup` / `zend_strndup` 长度加一溢出 | `Zend/zend_alloc.c:2570,2588,2604` | 原来调用 `zend_error_noreturn`，需按上游转安全终止。 |
| 乘加大小溢出 | `Zend/zend_multiply.h:269,282` | safe allocation 不只包含底层内存失败。 |
| HashTable 尺寸 / grow 溢出 | `Zend/zend_hash.c:106,187` | 在中间状态变化前后可能 fatal，按官方逐项处理。 |
| persistent libc allocator 失败 | `Zend/zend_alloc.c:2874,2880,2896` | `zend_out_of_memory()` 原本 `fprintf` 后 `exit(1)`，应对照 `_exit`。 |
| allocator panic | `Zend/zend_alloc.c:362` | 原本 `exit(1)`；退出回调也不能触碰不可信堆。 |
| custom heap handlers | `Zend/zend_alloc.c:2467,2498`; `Zend/zend_alloc.h:267` | 扩展可替换 malloc/realloc；不假定所有第三方分配器遵守新 helper 语义。 |

普通用户 fatal、parse error、timeout 与内存失败不是同一种错误，不可把所有
`zend_error_noreturn()` 全局替换成进程终止。最小回移植应仅按照上游证据处理
危险 allocation/size 路径，正常分配语义不变。

## CVE-2026-109619：Session 的跨请求生产者/消费者

源码事实：Session MINIT 在 `ext/session/session.c:2746` 保存原 RFC1867 回调并
注册 `php_session_rfc1867_callback`；因此模块 RINIT 之前就有可调用入口。
`session.upload_progress.enabled` 默认 `1`，为 `ZEND_INI_PERDIR` (`:870`)，
应用执行后的 `ini_set()` 并非可靠防御点。

```text
MULTIPART_EVENT_START                    session.c:2970
  ecalloc progress; publish PS(rfc1867_progress)
MULTIPART_EVENT_FORMDATA                 :2978
  collect session-name field and progress key
  early cookie/GET SID lookup            :2876
MULTIPART_EVENT_FILE_START               :3012
  allocate progress arrays
  php_rinit_session(0)                   :3044
    php_rinit_session_globals()          :2645 -> :105
  publish PS(id)                        :3045
  php_session_rfc1867_update()           :3069 -> :2909
    php_session_initialize(); update session; flush
MULTIPART_EVENT_END                      :3105
  if sid and key: cleanup or final update :3108
    php_session_initialize()            :2945 / :2930
  php_rshutdown_session_globals()        :3115 -> :121
  free progress; PS(rfc1867_progress)=NULL :3125
ordinary session RINIT                   :2678 (only later)
```

`php_rinit_session_globals()` 清空 `PS(id)`、`PS(mod_data)`、`PS(session_vars)`
并 `ZVAL_UNDEF(&PS(http_session_vars))` (`:105`)。这些槽位的正常初始化并没有在
所有早期回调入口执行。特别是 END 在只存在 SID 与 progress key 时也会进入
`php_session_rfc1867_cleanup()`，不要求本次已经经过 FILE_START 重置。
FORMDATA 收集 session-name 字段的分支 `:2996` 不受 `use_only_cookies` 门控，
而 cookie/GET 的 `early_find_sid` 有该门控 (`:2886`)；不能把该配置当作上传
回调的通用安全边界。

早期 Session 不只涉及 `PS(id)`。`php_session_initialize()` 在
`ext/session/session.c:502` 打开存储 handler、建立 Session 变量、读取持久化
数据，再在 `:567` 调用 `php_session_decode()` (`:232`)。内置的
`php_serialize`、`php_binary`、`php` decoder 分别在 `:904`、`:966`、`:1062`
使用 `PHP_VAR_UNSERIALIZE_INIT/DESTROY`。

这两个宏在 `ext/standard/php_var.h:91,106` 将请求分配的反序列化上下文发布到
`BG(unserialize).data`，维护 `BG(unserialize).level`，嵌套调用可能复用它。
反序列化可调用对象处理函数、类加载回调和延迟的 `__wakeup`
(`ext/standard/var_unserializer.re:142,447,849,866`)；这些可引入非 OOM fatal。
basic 模块的正常 RINIT 才清零 `BG(serialize_lock)` / `BG(unserialize)`
(`ext/standard/basic_functions.c:3730-3736`)。因此成功 startup 后的解码操作也
可能成为生产者，后续 pre-RINIT Session 解码是需要切断的消费者；不能把
Session 分析缩减成只有两个 `PS` 字段。此处识别的是可中断状态关系，不是已
运行的 PHP 7.0 利用证明。

在存在后续消费者的情况下，状态发布后 fatal 导致 END 未执行、模块关闭被
跳过或某个清理步骤被中断，可能留下指向请求内存的槽位。请求堆整体回收不
会自动把这些全局槽位置空。后续请求在普通 RINIT 之前使用这些槽位构成 UAF
所需的生命周期条件。**这是源码支持的风险链；本审计没有运行命令执行 PoC，
不声称在 PHP 7.0 的每个 SAPI/配置上都已验证可利用。**

关闭 upload progress 时必须在实际 Session 回调入口切断机制，覆盖 INI 设置为
`1` 的情况，并保留普通 `session_start()`、Session 读写与普通上传。仅把默认值改为
`0` 留下重新启用旁路，不满足官方最小缓解的意图。行为兼容性损失必须公开。

## Session 之外的早期入口

| 入口及阶段 | PHP 7.0 源码事实 | 审计判断 |
| --- | --- | --- |
| FPM 每请求 INI，在 `zend_activate()` 前 | `init_request_info()` 解析 `PHP_VALUE` / `PHP_ADMIN_VALUE` (`sapi/fpm/fpm/fpm_main.c:1397,1406,1899`)，回调应用设置 (`:1426`) | 不能仅防 multipart。必须在堆释放前重置 executor 错误/异常状态。前端是否传入这些参数是部署前提。 |
| mod_php 每目录 INI，在 startup 前 | `apply_config(conf)` (`sapi/apache2handler/sapi_apache2.c:577`) 早于 `php_apache_request_ctor()` (`:629`) | 诊断可能早于普通 executor 初始化。不能用隐藏诊断证明安全。 |
| Zend extension activators，在 executor 部分初始化时 | `zend_llist_apply(...zend_extension_activator)` (`Zend/zend_execute_API.c:155`)，而 exception 清零在 `:176` | 需保留官方 executor 重置策略。第三方 Zend 扩展需要独立验证。 |
| SAPI activate 与 input_filter_init，在模块 RINIT 前 | `main/SAPI.c:483-488` | SAPI callback 本来就早于 RINIT，禁用 Session 不会删除这些入口。 |
| `filter` 输入过滤器 | MINIT 注册 (`ext/filter/filter.c:289`)，early init 把六个 `IF_G` zval 标为 UNDEF (`:358`)，输入处理 `:421`，RSHUTDOWN `:313` | 内置扩展已经显式 early reset；这是可借鉴的模式。该事实不构成所有过滤路径无错证明。 |
| `mbstring` 的 treat_data 和 POST handler | 注册 `mbstr_treat_data` (`ext/mbstring/mbstring.c:1558`)，其 `mb_gpc.c:54` 可在 RINIT 前执行；encoding translation 可替换 POST entries (`mbstring.c:1410`) | 输入转换状态与其 RINIT/清理需考虑；未建立独立可利用链，不能无依据宣称同 CVE 已复现。 |
| `mbstring` 的 multipart multibyte hooks | MINIT 注册 `php_rfc1867_set_multibyte_callbacks` (`ext/mbstring/mbstring.c:1581`)，parser 使用 (`main/rfc1867.c:310,711`) | 这些回调也早于模块 RINIT；不应为“仅 Session 早执行”的错误假设重排整体启动顺序。 |
| 自定义 POST handlers / auto-globals / SAPI input filters | 公开注册 API `main/SAPI.h:195-200`；auto-global dispatcher `Zend/zend_compile.c:1557` | 仓库内静态搜索不能穷举部署加载的第三方扩展。 |

PHP 7.0 `PG(last_error_message)` 和 `PG(last_error_file)` 用 libc `strdup()`
(`main/main.c:1037`) 分配，用 `free()` 清理 (`:1427`)，并非 Zend 请求堆对象。
PHP 8.5 的 `fatal_error_backtraces` 字段也不在此基线中。因此不能把新版的
last-error/backtrace 具体生产者照搬为 PHP 7.0 已确认的生产者。
但是 `php_error_cb()` 在 `:1043` 读取 `EG(error_handling)`、`:1065` 使用
`EG(exception)` / `EG(exception_class)`；`zend_error()` 在 `Zend/zend.c:1169`
检查用户错误处理 zval。`shutdown_executor()` 在 bailout 保护块之后没有统一
重置上述全部字段 (`Zend/zend_execute_API.c:250-418`)。这为保留上游更广泛的
executor/global reset 提供了源码理由，仍应逐字段判定 PHP 7.0 的实际拥有权。

## Multipart 资源边界

* 初始 `post_max_size` 检查只比较已声明的 content length
  (`main/rfc1867.c:720`)；无有效声明长度时必须按实际已读字节限制。
* `sapi_read_post_block()` 累计 `SG(read_post_bytes)` (`main/SAPI.c:240`) 但本身
  不限制总量。standard form reader 有实际大小检查 (`:289`)；不能假定
  multipart 也自动经过这个 reader。
* `multipart_buffer_headers()` (`main/rfc1867.c:409`) 循环追加 header linked
  list、复制 key/value，并支持 continuation，但没有 header 数量上限。
* `max_file_uploads` 计数只在创建临时文件后减少 (`:1020`)；空 filename 路径
  (`:1000`) 跳过该减少，却继续构造 `$_FILES` 元数据 (`:1140-1294`)。
* 正常结束时 END 回调在 `:1307`；fatal 的 longjmp 不会“自动走 END”。

应按上游同时限制 header 工作量、实际 body 字节和上传项数量；超限时的清理
必须使用可信状态。上限的有效合法请求变化必须列入兼容性文档和边界测试。

## 验证这些推导所需的证据

最低动态证据包括：普通请求、普通 Session 和上传仍正常；upload progress
无法被重新开启；有限 memory limit 下子进程直接退出且不运行 PHP shutdown
回调；FPM master 替换 child；正常及 fatal 后相同 worker 的连续请求无异常；
早期 INI 诊断消费者；Debug 与 ASan 的代表性异常路径；原有 PHPT 的已解释结果。
必须分别记录“测试不存在”“未执行”“跳过”“失败”和“通过”。

安全测试应观察退出、重置、边界和内存错误，不需要命令执行负载。ASan 没有
报错、编译成功或单次 HTTP 返回成功，都不能单独证明所有跨请求 UAF 已消失。
第三方扩展、自定义 allocator、Windows/ZTS、Apache SAPI 等未经执行的范围应
保留为限制，不把最小回移植表述成 PHP 7.0 的全面安全保证。
