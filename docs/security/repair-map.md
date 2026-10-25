# PHP 7.0 安全回移植逐点对照

此表落实新增代码组织要求；先完成 `root-cause.md`、`backport-matrix.md` 的源码比较，
再确定下述实现。原始位置均为 `bf574c2b67a`，新位置以函数名定位，避免生成代码导致行号漂移。

## 统一模式与策略

`Zend/zend_security.h::php70_security_is_hardened()` 返回编译期常量。
默认 hardened；`./configure --disable-php70-security` 生成**仅供隔离比较的、不安全的
legacy 构建**。没有运行期 INI 开关、动态 Hook 或函数指针替换。
唯一新增共享头用于 Zend MM、VM、SAPI 和扩展共同的只读模式判断，其余新增函数均在原源码文件内。OOM 路径不会读取配置、
调用 PHP 错误处理器或为模式选择分配内存。修改模式必须清理对象文件并重新编译；
外部扩展也必须使用同模式头文件重新编译，不能混用内联保护代码。

* **A：抽取/新增小函数。** 同一原文件内实现，原位置判断模式；保留原始 legacy 路径。
* **B：原地检查。** 涉及局部变量所有权、VM 操作数、已有错误/清理跳转时，不为了抽取改变控制流。
* **C：固定不变量。** 类型宽度、存储对齐和生成工具正确性不能随请求切换，直接修复并说明边界。

上游列中 `74` 指 [PHP 7.4 提交 712e60f9edfd03f0960fc4fc3c2c375f42b90aa2](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2)。
这仍是 EOL 最小缓解，不等同于受支持 PHP 的完整修复。

| 原始函数与基线位置 | 修复函数/位置 | 策略 | 上游依据与原始风险 | legacy / hardened 差异 | 验证入口 |
| --- | --- | --- | --- | --- | --- |
| 构建选项、无原模式 API | `configure.in`; `php70_security_is_hardened()` | A | 所有防御点统一决策，避免 OOM 中读取配置 | 编译期 0 / 1；默认 1 | 两种构建、probe 的 hardened 字段 |
| `zend_mm_safe_error`, `Zend/zend_alloc.c:375` | 同文件 `zend_mm_safe_error_hardened()` | A | 74 同文件：OOM bailout 可进入不完整对象清理 | 原 overflow/error/try/catch/bailout 保留 / 固定栈缓冲诊断后 `_exit(1)` | hard_oom PHPT；FPM worker 重建 |
| `zend_mm_panic`, `zend_alloc.c:362` | 原位模式判断 | B | 74：`exit` 回调可能消费不可信堆 | 原 `exit(1)` / `_exit(1)`；不移动 Debug 信号逻辑 | 静态审查；未注入真实堆破坏 |
| `zend_out_of_memory`, `zend_alloc.c:2874` | 原位模式判断 | B | 74：系统 allocator 失败也不能运行退出回调 | 原 stderr+exit / stderr+_exit | native system_malloc probe |
| `zend_mm_alloc_heap`, `zend_alloc.c:1373` | `zend_mm_safe_error_hardened()` 调用 | B | 74：Debug 元数据对齐溢出独立于 memory_limit 入口 | 原错误表达式保留 / fail-stop | Debug 编译；size overflow/native probe |
| `zend_mm_alloc_huge`, `zend_alloc.c:1762` | 原位 rounding guard | B | 74 已有检查、7.1 补缺；7.0 尺寸舍入可能溢出 | 原路径 / 检查 new_size < size 后 fail-stop | 原生 huge guard；未通过超大真实分配验证 |
| `_estrdup`, `_estrndup`, `zend_strndup`, `zend_alloc.c:2561–2613` | `zend_mm_safe_error_hardened()` 调用 | B | 74：长度加一溢出不能 bailout；新诊断修正 varargs 类型 | 保留原表达式 / 官方安全诊断并退出 | estrndup、zend_strndup native probe |
| `zend_safe_address_guarded`, `zend_safe_addmult`, `zend_multiply.h:269,282` | `zend_mm_safe_error_hardened()` 调用 | B | 74：乘加溢出可中断对象初始化 | 原错误函数保留 / fail-stop | size_overflow PHPT；inline_guard probe |
| `zend_hash_check_size`, packed grow, resize，`zend_hash.c:97,187,871` | 同一原位检查调用 reporter | B | 74：容量计算错误不能恢复清理 | 原错误表达式保留 / 正确类型诊断并退出 | 数组回归；容量错误静态检查 |
| `Balloc`, `zend_strtod.c:603,616` 两处分配失败 | 同文件错误点调用 reporter | B | 74：dtoa allocator 失败可污染清理 | 原 fatal / fail-stop；两者都先释放 dtoa 锁 | 数字转换原测试；未做 dtoa 故障注入 |
| `_array_init`, `zend_API.c:1057`; input 初始化四点 | `_array_init_singleton()`；原输入位置分支 | A/B | 74 的 singleton API；7.1 旧 API 适配 | 原 array_init / 初始化容量为 1，成功解析语义一致 | singleton_input_arrays PHPT；原生 table-size probe |
| `zend_hash_real_init_ex`, `zend_hash_packed_to_hash`, `zend_hash.c:130,209` | 原位最少两个 hash 索引前缀 | C | 74 的 mask 为 -2*capacity，7.0 为 -capacity；照搬 7.1 会让单 bucket 地址偏移 4，违反 64 位对齐 | 两种模式都保持 Bucket 对齐；legacy 原容量 >=8 不变 | 修改前 native probe 实测余数 4；修改后要求余数 0 |
| `HT_HASH_RESET`, `zend_types.h:253`; `zend_hash.h` | 沿用现有实现 | C/无需改动 | 74 的 SSE reset 需补小表处理，7.0 已是通用 memset；singleton 声明转至旧 API | 无结构体变化，无复制新版本 HashTable | 公共头逐字对比、probe sizeof、数组测试 |
| `ZEND_CONCAT`, `ZEND_FAST_CONCAT`, `zend_vm_def.h:258,2690` | 原位 guard + reporter；7.0 生成器再生成 | B | 74：长度相加可能溢出，必须保持操作数生命周期 | 原分配路径 / 在分配前额外检查 | VM 原测试、普通拼接、size overflow；未伪造字符串元数据 |
| `zend_string.h` 长度界限 | `ZSTR_MAX_LEN` | C | 74 已有、7.1 补充：header/NUL/对齐空间是表示不变量 | 两种模式定义同一界限，只有 hardened guard 使用 | 构建、VM 回归、32 位未执行 |
| `zend_vm_gen.php:643` 的 preg_match_all `/me` | 修正为 `/m` | C | `/e` 不适用于该匹配；不修正无法可靠生成当前头文件 | 构建工具修正，不改变语言语义 | 用 PHP 7.0 基线二进制重复生成 |
| `shutdown_executor`, `zend_execute_API.c:250` | `zend_executor_reset_hardened()` | A | 74：清理后仍可达的 error/exception/stack/object 状态 | 完整原清理顺序保留 / 清理结束后额外无析构重置 | FPM 普通 fatal 后同 worker；handler 回归 |
| `zend_llist_destroy`, `zend_llist.c:104` | 原位 head/tail 重置 | B | 74：释放的链表节点地址不应仍可达 | 原 count 清零 / 端点也清零 | 原链表相关请求/上传回归；静态生命周期审查 |
| `sapi_deactivate`, `main/SAPI.c:504` | 五个 efree 后原位重置 | B | 74：auth/content_type/current_user 的请求指针残留 | 保留原释放点 / 每次释放后立即 NULL，避免抽取延后重置 | 同 worker 正常/Session/上传；SAPI 头静态对比 |
| `php_request_shutdown`, `main/main.c:1781` | http_globals 逐项原位 UNDEF；结束时 flag 重置 | B | 74：下一请求启动前仍可能访问全局槽位 | 原销毁顺序 / 销毁成功后立即 tombstone | 同 worker、fatal/OOM 区分、原 PHPT |
| `php_session_rfc1867_callback`, `session.c:2955` | 原位 hardened 提前 return | B | 74：RINIT 前访问 Session/decoder；一个 return 不值得抽取空函数 | 原 enabled 判断和完整 progress 逻辑保留 / 无条件禁用 progress；仍先调用原 callback chain | upload_progress_disabled PHPT；FPM 开启 INI 也无 progress |
| `multipart_buffer_headers`, `rfc1867.c:410` | `php_mime_should_save_hdr_hardened()`，原位 buffer 分支 | A/B | 74：无限保留无关/重复头导致放大 | 原保存逻辑 / 仅保存首个必要头；buffer 所有权不移动 | duplicate_headers PHPT；header-pressure FPM |
| `substring_conf`, `rfc1867.c:525`; 两个调用者 | 同文件 `substring_conf_hardened()`；两个原调用点判断模式 | A | 74：strlen/指针差截断为 int；可用独立 helper 安全保留原始契约 | legacy 原函数/转换逐字保留；hardened 使用 size_t；无公开 ABI 变化 | 合法上传、引号文件名原 PHPT；超大头未分配 |
| `rfc1867_post_handler`, `rfc1867.c:688` | `php_multipart_parts_limit_hardened()`, `php_multipart_validate_hardened()` | A | 74 加 part 上限；7.0 适配避免 int 缩窄、sum/predecrement 溢出 | 原无限 part 路径 / 全部 Content-Disposition part 计数，含空 filename；拒绝仍走原 cleanup label | explicit/zero/default/large/saturate 六组 PHPT |

## 不能从本表推导的保证

legacy 是有意保留的原始易受攻击行为，不能当作生产回退开关。
C 类修正使它成为保留原始行为的比较构建，而非逐字节相同的 PHP 7.0.33。
两种构建都包含新增 helper/API 与 `max_multipart_body_parts` 的注册；legacy 解析器不使用此限制。
不提供请求内切换；运行期切换会使先前构造的表、状态和内联扩展代码不一致。

保留的第三方 multipart callback、custom allocator、非 OOM fatal 的其他发布者/消费者，
仍需单独审计。此回移植没有补 decoded body 的实际字节上限。
测试的最终通过/失败/未执行情况以 `verification.md` 为准；上表是覆盖映射，不是测试通过声明。
