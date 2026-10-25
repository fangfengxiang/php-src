# PHP 5.6.40：先于实现的根因审计

基线：官方 php-5.6.40，4b8f72da5dfb201af4e82dee960261d8657e414f。
审计日期：2026-10-25。本文在运行时代码修改之前建立；验证结果另记。
目标是两个 CVE 的非官方 EOL 最小缓解，不是恢复 PHP 5.6 的官方支持。

## 证据与推导方法

- 鸟哥原文：https://www.laruence.com/2026/10/22/7686.html （已通读）。
  用其“状态发布→可失败工作→清理被跳过→跨请求早期消费者”的问题框架。
  文中以 PHP 8.5 为例的 zend_string、zend_reference、堆布局和利用结果不视为 5.6 事实。
- 官方最小补丁：php/php-src@712e60f9edfd03f0960fc4fc3c2c375f42b90aa2。
- 官方公告：GHSA-w8hw-w9fx-j79w、GHSA-6wmf-4rv5-p3rp。
- 7.0 经验：fangfengxiang/php-src PR #1；7.0 基线 bf574c2b67a1f786e36cf679f41b758b973a82c4。
  只复用审计方法与已审查的清理顺序，不复用其运行结果。

以下行号均指 5.6.40 未修改基线。源码可达性是静态证据，不等于已复现 RCE。

## 请求生命周期与 SAPI

main/main.c:1616 的普通 php_request_startup：PG(modules_activated)=0 (1642)，
zend_activate (1647)，sapi_activate，php_hash_environment (1685)，
zend_activate_modules (1686)，最后 modules_activated=1 (1687)。
main/php_variables.c 的 _POST auto-global 通过 treat_data、sapi_handle_post 进入
main/rfc1867.c:683，multipart 回调早于扩展 RINIT。POST reader 不等于 post handler。

main/main.c:1818 php_request_shutdown 先调用用户 shutdown、对象析构、输出清理，
1866 的扩展 RSHUTDOWN 受 modules_activated 门控；1881 的 HTTP globals 析构及
1921 的请求堆回收不受该门控。zend_try 只捕获 bailout，不回滚此前发布的状态。
APACHE_HOOKS 的独立生命周期必须单列，不据普通流程推导其验证结论。

FPM init_request_info 在 startup 前应用 PHP_VALUE / PHP_ADMIN_VALUE
(sapi/fpm/fpm/fpm_main.c:1434,1920)。startup 失败在 1927-1931 退出 worker，
所以不能声称 FPM 必然复用“pre-RINIT OOM 请求 A”的 worker。
mod_php apply_config (sapi/apache2handler/sapi_apache2.c:566) 早于 request ctor，
请求析构调用 php_request_shutdown (507)。两者都有正常 executor 初始化前的 INI 诊断入口。

## 109618：allocator 与中间状态

Zend/zend.c 的 _zend_bailout 做 LONGJMP，不沿 C 栈回滚。
Zend/zend_alloc.c:1743 的旧版 zend_mm_safe_error 先释放 reserve，设置 overflow，
再经 zend_error_noreturn 和 zend_bailout 恢复到外层。清理可能读取已发布的半初始化数据。
alloc_int (1880) 与 realloc_int 的内存限制/存储失败都到达此处。
true_size 的对齐溢出已有 out_of_memory 分支；保留成功分配、缓存与存储重试路径。

safe_address 在 alloc.c:2461 起有六个架构实现（含 aarch64），均须改变溢出退出语义。
_safe_emalloc_string 的 INT_MAX 表示边界也会 bailout。_estrdup/_estrndup 已通过
safe_address(length,1,1)，无需照搬 PHP 7 的重复 guard；zend_strndup 的原始 malloc
失败返回 NULL 是历史 API 契约，不擅自改成必然退出。
系统分配失败的 exit 在 zend_alloc.h 的 __zend_malloc/__zend_realloc 内，须改为
不调用 atexit 的终止路径；不能只修改 PHP 7 中那个并不存在于 5.6 的函数。

## 109619：具体生产者与消费者

session MINIT (ext/session/session.c:2466) 注册 multipart callback。
FILE_START (2756) 调用 php_rinit_session(0)，发布 PS(id)（char*，不是 zend_string），
随后 update (2624) 调用 php_session_initialize，发布 PS(http_session_vars)（zval*）。
END (2816) 在 sid 与 key 存在时调用 cleanup (2654)，不要求经过 FILE_START。
cleanup 再进入 initialize / decoder；其 php_session_track_init (872) 会读取并析构
旧 PS(http_session_vars)。php_rinit_session_globals (92) 才把这些槽位置空。
若 END 因 bailout 跳过、RSHUTDOWN 因门控或中断未完成，整体堆回收不清空这些槽位。
下一请求的 pre-RINIT END 因而是明确消费者。use_only_cookies 不门控表单 SID 分支。

Session decoder 的 PHP_VAR_UNSERIALIZE_INIT (ext/standard/php_var.h:88) 将请求上下文
发布为 BG(unserialize).var_hash/level，正常 basic RINIT 才重置。用户回调 fatal 是
非 OOM 中断源；单改 OOM 不足。无条件切断内置 upload progress 的早期入口，仍保留
原 callback chain、普通上传与应用阶段 Session。仅修改 INI 默认值会留下重启用旁路。

EG(user_error_handler) 由脚本设置；shutdown_executor 的各 zend_try 可跳过后续清理。
Zend/zend.c:1130 的早期诊断会读它；main/main.c:1079 的错误模式可能引向 exception。
按官方方向在现有 executor 清理结束后无析构重置处理器、栈、error_handling、exception
和 object store。保留原释放顺序，不在 cleanup 前抹掉所有权。
PG(last_error_message/file) 使用 libc strdup/free；不能照搬 PHP 8 backtrace 的请求堆主张。

## 官方 17 文件的 5.6 处置

| 官方文件 | 5.6 决策与必要性 |
|---|---|
| zend_API.h | 无需改动；小输入数组 helper 私有地放在 php_variables.c，不扩展公共 API |
| zend_alloc.c | 固定栈缓冲 stderr + _exit；六个 safe_address、string size guard；panic |
| zend_alloc.h | 新 helper 声明；系统 malloc/realloc 的失败终止在此适配 |
| zend_execute_API.c | 现有全部 cleanup 之后重置指定请求状态 |
| zend_hash.c | 不移植 PHP 7 packed grow/HT_MAX_SIZE：5.6 没有这些路径；CHECK_INIT 使用 pecalloc；resize 原有未检查乘法单列为遗留风险，不宣称已覆盖 |
| zend_hash.h | 无新增构造器需要，保持结构和 API |
| zend_llist.c | destroy 完成后清空 head/tail，保留析构顺序 |
| zend_multiply.h | safe_address 实际位于 alloc.c；不凭空引入新头 |
| zend_strtod.c | 只有一处分配失败，先解锁再安全终止；不改无关 Kmax 错误 |
| zend_types.h | 无 PHP 7 的 SSE HT_HASH_RESET，不适用 |
| zend_vm_def.h | CONCAT 委托 concat_function；改 operators.c 对应的四处字符串分配边界 |
| zend_vm_execute.h | 模板不变，不复制或无故再生成 PHP 7 VM |
| session.c | 先调用原 callback，再无条件返回，禁用内置 upload progress |
| SAPI.c | 五处 efree 后立即 NULL |
| main.c | http_globals 是 zval*，析构成功后 NULL；关闭结束重置 modules_activated；注册 part 限制 |
| php_variables.c | 两处嵌套数组及 treat_data 使用小输入数组 |
| rfc1867.c | 首个必要头、忽略重复头；size_t 长度；long 计数、饱和默认和、复用原 cleanup |

## 5.6 特有表示决策

HashTable (Zend/zend_hash.c:195) 使用独立 Bucket、Bucket** 索引、链表；
nTableMask=0 是“未分配”哨兵，CHECK_INIT 后 mask=size-1。
容量 1 会把已分配表的 mask 也设为 0，破坏此不变量；小输入数组应取最小可用容量 2，
先用原 _array_init 建立全部字段，再仅在尚未分配索引时设 nTableSize=2。
第一次插入 mask=1，后续增长 2→4→8，Bucket 始终独立分配；无 PHP 7 的索引前缀对齐问题。
不改变全局 HashTable 最小容量，不改变公开结构体或 API 编号。

PHP 5.6 字符串长度为 int。concat 的 signed sum 在原检查之前已可能发生 UB；
需在相加之前按 INT_MAX 验证，不能只替换错误函数。add_char/add_string 同属
VM 字符串构建分配路径。正常语言转换、别名和引用语义应保持。

## 验证计划与范围约束

以干净基线作为 legacy 对照，不增加生产可切换的 legacy 开关。先在相同 Linux arm64
工具链构建基线与本分支；Debug/Release、定向 PHPT、原有核心/session/upload 套件、
完整 PHPT 状态对照及同 PID FPM 请求。需要验证 OOM 不执行 shutdown callback、普通
fatal 仍执行、上传进度 INI=1 无法启用、合法上传/Session 不受影响、part 边界和小表增长。
原生 probe 用于可控的 size overflow 与真实容量检查；它不是远程利用复现。
所有新增失败逐项归因，不用 CI 绿色代替因果审查。Windows/ZTS/32bit/mod_php
等未实际执行的平台必须如实列为未验证。无关历史 bug 记录但不顺便修复。

## 构建发现（基线先行）

干净基线在 Linux arm64 GCC 12 的默认 Debug -O0 下无法编译：
Zend/zend_multiply.h 的既有 aarch64 inline asm 用 X 约束产生内存操作数。
这是基线问题，不修改生产源码；先尝试两侧一致使用显式 -O2 的 Debug 工具链，
其 Debug allocator 仍开启。若仍失败，改用现有 x86_64 隔离工具链。
5.6 没有 ZEND_COLD / ZEND_NORETURN 宏，新 helper 使用本版本可用声明。

## 首版 PR 的实施与待验证状态

已形成首版运行时补丁及 11 项定向 PHPT，均待本分支二进制验证。
系统 malloc/realloc 的失败使用独立 zend_out_of_memory：仅 stderr + _exit，
不访问 executor/TSRM globals，以保留启动早期可用性。
PHP 7 的 str_repeat(PHP_INT_MAX) 测试不直接移植：5.6 在到达 safe_emalloc 前
有 INT_MAX 警告返回路径，后续改由原生 probe 验证真实 checked allocator。

用户要求先发布审查 PR，再进行后续验证。此时未宣称成功编译、测试通过或适合部署。
已经启动的构建日志保存在 worktree 的 .security-build/results，后续按快照归档结果。
