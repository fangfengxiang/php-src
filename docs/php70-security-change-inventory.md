# PHP 7.0 安全分支：完整文件改动清单

盘点日期：2026-10-24。读者为代码审阅者、维护者及负责部署评估的工程师。
本文是文件级参考；机制见[设计与流程](php70-security-design.md)，决策理由见[ADR](php70-security-adr.md)。

## 盘点口径与范围

- 固定基线：`bf574c2b67a1f786e36cf679f41b758b973a82c4`（PHP 7.0.33）。
- 已提交分支快照：`7cd812eb6e074a723483c727fac49aca8816befa`，分支 `security/php70-cve-2026-109618-109619`。
- “新增/修改”按基线到 HEAD 的最终树差异判定，不按某个中间提交判定。没有删除或重命名文件。
- “PHP 文件”包含解释器 C 源码、头文件、VM 生成器、构建入口和 PHPT；不只统计 `.php` 后缀。
- 用户规定的目标只有 CVE-2026-109618 / CVE-2026-109619 的必要缓解、7.0 适配及本次引入的回归。原有无关 bug 不修改。

| 统计范围 | 总数 | 新增 | 修改 |
| --- | ---: | ---: | ---: |
| 基线 → 已提交 HEAD | 79 | 58 | 21 |
| 加上本轮文档编写前已有的 4 个本地文件 | 83 | 62 | 21 |
| 再计入本次交付的 3 份 Markdown | 86 | 65 | 21 |

79 个已提交文件中：运行时 C/H 18 个、VM 生成器和 configure 2 个、NEWS/UPGRADING 2 个、
安全 PHPT 12 个、CI workflow 1 个、测试工具及其 README 14 个、既有说明文档 5 个、证据 25 个。
运行时/构建源码共 20 个，其中仅 `Zend/zend_security.h` 是新增文件，其余 19 个修改。
本地另有 2 条 PHPT，故当前工作区安全测试文件总数是 14；远程 HEAD 的 12 条与之不同。

表中“HEAD”固定指上述已提交实现快照；“本地”表示盘点时尚未提交、本批提交归档的文件。
这是提交前的盘点快照，不随 Git 状态滚动更新。下列 86 个路径逐一对应真实文件。

## PHP 运行时、头文件与构建生成器（20 个）

| 文件 | 相对基线状态 / 提交状态 | 改动内容与作用 | 收益 | 风险与边界 |
| --- | --- | --- | --- | --- |
| [Zend/zend_security.h](../Zend/zend_security.h) | 新增 / HEAD | 新增 PHP70_SECURITY_HARDENED 与 php70_security_is_hardened()，只接受编译期 0/1，默认 hardened。 | 在 allocator、VM、SAPI、Session 使用一致、无需 INI 查询和分配的策略。 | legacy 不安全；不能请求内切换；解释器与扩展必须使用匹配配置。 |
| [configure.in](../configure.in) | 修改 / HEAD | 注册默认开启的 php70-security 构建选项；显式 --disable-php70-security 生成 legacy 宏。 | 可用干净的 A/B 构建比较本次机制，不引入运行期 Hook。 | 切换模式需 clean 重编；误部署 legacy 会失去主要缓解。 |
| [Zend/zend_alloc.c](../Zend/zend_alloc.c) | 修改 / HEAD | 新增固定栈缓冲 reporter，诊断写 stderr 后 _exit(1)；覆盖 Zend MM OOM、Debug 元数据、huge rounding、字符串长度溢出；系统 OOM/panic 路径增加硬退出。 | 阻断 109618 中已覆盖分配失败后对不完整状态的清理；hardened 的诊断参数按实际类型匹配。 | 不执行业务 shutdown、析构、输出收尾或 atexit；进程需监督器补位。libc 格式化不是 async-signal-safe 保证；原 Debug panic 信号行为仍保留。 |
| [Zend/zend_alloc.h](../Zend/zend_alloc.h) | 修改 / HEAD | 引入 zend_security.h，并导出 zend_mm_safe_error_hardened() 声明。 | 让跨文件及头内 guard 共享同一错误终止入口。 | 新增符号；旧扩展内联代码不会因运行时升级自动更新，新头编译扩展也不保证可装回原始运行时。 |
| [Zend/zend_multiply.h](../Zend/zend_multiply.h) | 修改 / HEAD | 在 zend_safe_address_guarded / zend_safe_addmult 的失败分支调用 hardened reporter，保留 legacy 分支。 | 乘加计算失败也 fail-stop，不遗漏底层 allocator 之外的溢出入口。 | 内联 guard 需重编扩展才更新；不是对所有 PHP 算术的普遍修复。 |
| [Zend/zend_hash.c](../Zend/zend_hash.c) | 修改 / HEAD | 容量检查、packed grow 和 resize 溢出走 reporter；mixed 初始化、packed→hash 为容量 1 保留至少两个索引前缀。 | 覆盖 HashTable 尺寸错误；补齐本次 singleton 的 PHP 7.0 对齐适配，避免 64 位 Bucket 指针偏移 4 字节。 | 两条布局路径必须一致；表示不变量在两模式都保留。32 位仍未实测；对齐要求不能用 sizeof(Bucket) 代替。 |
| [Zend/zend_strtod.c](../Zend/zend_strtod.c) | 修改 / HEAD | Balloc 两个分配失败分支先按原逻辑释放 dtoa 锁，再在 hardened 下调用 reporter。 | 覆盖浮点转换使用的独立分配失败入口。 | 定向 dtoa 分配失败注入尚未执行；一般数字回归不等于失败入口已覆盖。 |
| [Zend/zend_string.h](../Zend/zend_string.h) | 修改 / HEAD | 定义 ZSTR_MAX_LEN，预留字符串 header、NUL 和对齐空间。 | 为本次 VM 拼接 guard 提供 PHP 7.0 缺失的表示边界。 | 两模式共享宏定义；不代表所有字符串操作都新增了检查。 |
| [Zend/zend_vm_def.h](../Zend/zend_vm_def.h) | 修改 / HEAD | CONCAT 两个分配分支及 FAST_CONCAT 一个分支增加长度上限检查。 | 在拼接分配前终止危险尺寸路径，保持原操作数生命周期与所有权。 | 极限字符串元数据未用伪造对象动态构造；模板错误会传播到多个专用 handler。 |
| [Zend/zend_vm_execute.h](../Zend/zend_vm_execute.h) | 修改 / HEAD | 用 PHP 7.0 自有生成器同步生成 27 个具体 guard，相对基线新增 108 行。 | 实际执行的专用 handler 获得与 VM 模板一致的保护。 | 生成物不能单独手改；须同时审查模板和字节级再生成结果。 |
| [Zend/zend_vm_gen.php](../Zend/zend_vm_gen.php) | 修改 / HEAD | 将 preg_match_all 的无效 /me 修为 /m，以便正确移除未使用声明。 | 本次 VM guard 能用 PHP 7.0 工具可靠生成，属于必要生成工具适配。 | 不是一般生成器重构；不能改用 PHP 8 执行旧生成器或复制其他版本生成头。 |
| [Zend/zend_API.c](../Zend/zend_API.c) | 修改 / HEAD | 新增 _array_init_singleton()：复用原 _array_init 后将惰性表初始容量设为 1。 | 降低输入小数组的初始内存放大，延续 7.0 初始化契约。 | 依赖对应 HashTable 对齐和增长路径；不是将所有应用数组都设为容量 1。 |
| [Zend/zend_API.h](../Zend/zend_API.h) | 修改 / HEAD | 增加 array_init_singleton 宏与 _array_init_singleton 声明。 | 提供输入解析调用所需的最小新增 API。 | 新增 API 的可见性不等于新旧运行时双向二进制兼容。 |
| [main/php_variables.c](../main/php_variables.c) | 修改 / HEAD | 嵌套输入数组的三个创建点及 GET/POST/COOKIE 起始数组在 hardened 下改用 singleton；legacy 仍走旧调用。 | 减少输入树的分配放大，保持已成功解析的输入语义。 | 须维持 packed/sparse/mixed、COW、append 与增长行为；不能消除深层输入或大 body 的全部内存消耗。 |
| [Zend/zend_execute_API.c](../Zend/zend_execute_API.c) | 修改 / HEAD | 原 shutdown_executor 清理后新增无析构 reset，清空选定 error/exception handler、stack、exception 及 object store buckets/top。 | 降低 109619 中后续早期消费者访问已释放请求状态的机会。 | 只覆盖选定槽位；不是完整 Executor 初始化。原清理未到达或被中断时，不承诺所有 reset 都执行。 |
| [Zend/zend_llist.c](../Zend/zend_llist.c) | 修改 / HEAD | 原节点销毁后 hardened 清空 head/tail，保留原 count=0。 | 解除已释放链表节点的端点引用。 | 不重排节点析构；不是全部链表操作的安全重设计。 |
| [main/SAPI.c](../main/SAPI.c) | 修改 / HEAD | 在 sapi_deactivate 的原释放点后，立即将 auth_user/password/digest、content_type_dup、current_user 五个指针置 NULL。 | 消除已覆盖 SAPI 请求字段的悬空引用。 | 只覆盖列出的五个字段；不证明第三方 SAPI 自有状态安全。 |
| [main/main.c](../main/main.c) | 修改 / HEAD | 注册 max_multipart_body_parts；各 HTTP global 析构成功后置 UNDEF；关停末尾将 modules_activated 置 0。 | 接入输入限额，并减少核心请求槽位跨请求残留。 | 保留原清理顺序；单项清理中断不能等同完整恢复。legacy 中指令可见但解析器不执行新限额。 |
| [ext/session/session.c](../ext/session/session.c) | 修改 / HEAD | 上传事件回调仍先执行原 callback chain，hardened 随即返回，跳过 Session Upload Progress。 | 关闭已知 RINIT 前的 Session progress 生产者/消费者链；普通 Session 和上传仍可用。 | Upload Progress 无条件失效，即使 INI 显示 On；原第三方回调仍可执行，需独立审查。 |
| [main/rfc1867.c](../main/rfc1867.c) | 修改 / HEAD | 仅保留首个 Content-Disposition/Content-Type；新增独立 size_t substring helper；使用 zend_long、饱和派生和先零判断后扣减的 part 限额，超限走原 cleanup。 | 限制保留头与 part 驱动的放大，避免 7.0 长度缩窄和上限算术问题；保留 legacy helper 契约。 | 重复头策略和 part 截断属于兼容变化；空文件也计数；未新增 decoded body 总字节限制，超大输入仍可导致 worker 退出。 |

## 面向使用者的版本说明（2 个）

| 文件 | 相对基线状态 / 提交状态 | 改动内容与作用 | 收益 | 风险与边界 |
| --- | --- | --- | --- | --- |
| [NEWS](../NEWS) | 修改 / HEAD | 追加 unofficial security backport 的功能摘要。 | 明确本次安全行为与 Session progress 变化。 | 不能据此称为 PHP 官方发行或完整受支持版本修复。 |
| [UPGRADING](../UPGRADING) | 修改 / HEAD | 记录编译模式、硬退出/stderr、worker 重建、part/header 限制及扩展重编要求。 | 让部署和兼容性评估能看到有意改变的行为。 | 不是生产发布批准；部署方仍需核查自己的 SAPI、扩展与依赖。 |

## 安全 PHPT（已提交 12 个，本地新增 2 个）

| 文件 | 相对基线状态 / 提交状态 | 改动内容与作用 | 收益 | 风险与边界 |
| --- | --- | --- | --- | --- |
| [Zend/tests/cve_2026_109618_hard_oom.phpt](../Zend/tests/cve_2026_109618_hard_oom.phpt) | 新增 / HEAD | 验证 memory_limit OOM 不执行 shutdown/destructor。 | 验证 fail-stop 的关键可观察行为。 | 依赖 Zend MM；单进程输出断言不代替 FPM/PID 与原生退出码检查。 |
| [Zend/tests/cve_2026_109618_ordinary_fatal.phpt](../Zend/tests/cve_2026_109618_ordinary_fatal.phpt) | 新增 / HEAD | 验证 E_USER_ERROR 保持 PHP 7.0 shutdown 行为及本例不析构的原语义。 | 避免把普通 fatal 误改为硬退出。 | 仅代表此错误场景，不推断所有 fatal 的析构行为。 |
| [Zend/tests/cve_2026_109618_singleton_input_arrays.phpt](../Zend/tests/cve_2026_109618_singleton_input_arrays.phpt) | 新增 / HEAD | 覆盖 packed/sparse/mixed、增长、COW、append、序列化、排序及删空再插。 | 验证 singleton 的输入结果兼容性。 | PHPT 不直接观察 C 布局，需原生对齐 probe 补足。 |
| [Zend/tests/cve_2026_109618_size_overflow.phpt](../Zend/tests/cve_2026_109618_size_overflow.phpt) | 新增 / HEAD | 用有界输入触发乘法尺寸溢出，检查不执行 shutdown。 | 验证不依赖真实耗尽大内存的 fail-stop 入口。 | 不是所有溢出分支的动态覆盖。 |
| [ext/session/tests/rfc1867_upload_progress_disabled.phpt](../ext/session/tests/rfc1867_upload_progress_disabled.phpt) | 新增 / HEAD | INI On 下仍无 progress，普通 Session 和真实上传可用。 | 同时验证必要功能移除与保留功能。 | 单请求不能代替跨请求 Session/FPM 检查。 |
| [tests/basic/rfc1867_duplicate_headers.phpt](../tests/basic/rfc1867_duplicate_headers.phpt) | 新增 / HEAD | 重复/不同大小写必要头取首个值，忽略无关头与其 continuation，检查上传内容。 | 验证新的头保留策略。 | 不是所有畸形头和超长头的穷举测试。 |
| [tests/basic/rfc1867_empty_file_nested_name.phpt](../tests/basic/rfc1867_empty_file_nested_name.phpt) | 新增 / HEAD | 嵌套空文件及 0/999/自动递增索引，检查文件错误码和空路径。 | 验证文件输入树的 singleton 增长语义。 | 有限深度与数量，不代表任意深嵌套压力。 |
| [tests/basic/rfc1867_max_multipart_body_parts.phpt](../tests/basic/rfc1867_max_multipart_body_parts.phpt) | 新增 / HEAD | 空 filename 控件也计数，达到显式上限后停止。 | 避免只限制成功上传文件而漏计空控件。 | 前序数据是空文件记录；真实文件组合由本地新增测试补充。 |
| [tests/basic/rfc1867_max_multipart_body_parts_default.phpt](../tests/basic/rfc1867_max_multipart_body_parts_default.phpt) | 新增 / HEAD | -1 从 input/upload 配额派生限制。 | 验证默认配置的组合上限。 | 不是派生零值或饱和值的覆盖。 |
| [tests/basic/rfc1867_max_multipart_body_parts_large.phpt](../tests/basic/rfc1867_max_multipart_body_parts_large.phpt) | 新增 / HEAD | 显式限额超过 INT_MAX 时不截断为负数。 | 验证 zend_long 的 7.0 宽度适配。 | 仅适用于 64 位，32 位会跳过。 |
| [tests/basic/rfc1867_max_multipart_body_parts_saturate.phpt](../tests/basic/rfc1867_max_multipart_body_parts_saturate.phpt) | 新增 / HEAD | 派生总和达到 zend_long 最大值时饱和。 | 验证配置求和不溢出。 | 仅适用于 64 位；不实际提交天文数量的 part。 |
| [tests/basic/rfc1867_max_multipart_body_parts_zero.phpt](../tests/basic/rfc1867_max_multipart_body_parts_zero.phpt) | 新增 / HEAD | 显式 0 拒绝首个 part。 | 验证消费端零值边界。 | 不同于 -1 派生出零的路径。 |
| [tests/basic/rfc1867_max_multipart_body_parts_derived_zero.phpt](../tests/basic/rfc1867_max_multipart_body_parts_derived_zero.phpt) | 新增 / 本地 | 本地待提交：input/upload 配额均 0，-1 派生出零后拒绝首个 part。 | 补齐本次新增派生函数的零值组合。 | 仅本地 PHP 7.0 验证，尚未进入远程 10-job 结果。 |
| [tests/basic/rfc1867_max_multipart_body_parts_retained_data.phpt](../tests/basic/rfc1867_max_multipart_body_parts_retained_data.phpt) | 新增 / 本地 | 本地待提交：先接收字段与真实文件，再因后续 part 超限停止，检查元数据和内容。 | 验证新拒绝分支仍走正确的原 cleanup，保留已完成数据。 | 仅本地验证；不覆盖所有扩展上传回调与失败时机。 |

## CI、PHPT 门禁与外部验证工具

| 文件 | 相对基线状态 | 改动内容与作用 | 收益 | 风险与边界 |
| --- | --- | --- | --- | --- |
| [.github/workflows/php70-security.yml](../.github/workflows/php70-security.yml) | 新增 | 本仓库 PHPT Debug/Release、12 组平台检查、固定外部 behavior/trace、报告与 Pages；仅当前分支 push 和手动触发。 | 沿用本仓库 runner，消除重复触发；发布要求全部门禁通过。 | 固定外部 SHA `bd5f7080231a20b0383f8c97931d2a2093d25d03`；并非穷尽安全证明。 |
| [.github/php70/](../.github/php70/) | 新增 | PHPT/VM 的 CI 脚本、结果完整性检查和 8 条 progress 兼容性清单；所有 PHPT 仍在原源码目录。 | 14 条安全用例不得跳过，失败/不完整结果不能误报绿灯；使用本仓库 `run-tests.php`。 | 集成选择不等于原始目录全绿；不改旧测试、PHP runner 或无关运行时代码。 |
| [php-security-e2e/php70/harness](https://github.com/fangfengxiang/php-security-e2e/tree/bd5f7080231a20b0383f8c97931d2a2093d25d03/php70/harness) | 外部依赖，不计本仓库源码改动 | 唯一工具链、构建、native probe、FPM、cgroup、behavior/trace 实现。 | Debian、CentOS 7/8/Stream 9、UBI 9 共用入口；本仓库不留工具副本。 | 外部项目后续修改须审查并显式更新固定 SHA；容器不验证原生发行版内核。 |
| docs/security/testing/ | 删除 | 旧目录被移除；当前复现入口见 [CI 使用说明](../.github/php70/README.md)。 | 区分当前调用契约和历史证据。 | 旧文档中的 testing/ 链接是历史路径，不代表当前存在。 |

## 说明文档、范围原则与本次三份交付（10 个）

| 文件 | 相对基线状态 / 提交状态 | 改动内容与作用 | 收益 | 风险与边界 |
| --- | --- | --- | --- | --- |
| [docs/security/root-cause.md](../docs/security/root-cause.md) | 新增 / HEAD | 记录两个目标漏洞的所有权、启动/关停和 allocator 根因分析。 | 为修复点提供可追溯的控制流依据。 | 静态路径与推断不等于已运行利用验证，基线行号与当前文件不同。 |
| [docs/security/backport-matrix.md](../docs/security/backport-matrix.md) | 新增 / HEAD | 逐个上游改动文件说明 7.4/8.0/7.1 与 7.0 的适配差异。 | 避免直接复制新版本 VM/HashTable 表示。 | 映射完整不是所有配置动态验证完整；7.1 仅参考。 |
| [docs/security/repair-map.md](../docs/security/repair-map.md) | 新增 / HEAD | 将函数、原位置、策略 A/B/C、legacy 差异与测试入口对应。 | 约束变更局部性和生命周期顺序。 | 不是每条路径已经测试通过的声明。 |
| [docs/security/verification.md](../docs/security/verification.md) | 新增 / HEAD | 保存早期干净构建、全量比较、内存压力、ABI 与未测范围。 | 公开保留真实失败与验证限度。 | 历史 11 PHPT/9 FPM、旧工具链及 x86_64 未测描述是当时快照，不覆盖后续 CI 时点。 |
| [docs/security/ci-and-boundary-review.md](../docs/security/ci-and-boundary-review.md) | 新增 / HEAD | 评估原边界建议，记录 CI 结构、本地/远程首轮结果及下载去重修正。 | 说明哪些检查已有，哪些尚缺证据。 | 含多轮历史状态，不能混作一次当前 HEAD 运行。 |
| [AGENTS.md](../AGENTS.md) | 新增 / 本地 | 本地待提交：固化只修本次目标漏洞及引入回归的原则。 | 防止把原有无关 PHP 缺陷或风格整理混入安全 PR。 | 是任务范围约束，不是安全实现或验证证据。 |
| [docs/security/report-review-2026-10-24.md](../docs/security/report-review-2026-10-24.md) | 新增 / 本地 | 本地待提交：逐条核对外部报告、驳回误报/未经证明的主张，确定两条测试缺口。 | 让新增工作有明确因果依据。 | 审查结论绑定当前快照；未证明的猜测不能当作已修或已确认漏洞。 |
| [docs/php70-security-change-inventory.md](../docs/php70-security-change-inventory.md) | 新增 / 本地 | 本次新增：全部文件状态、内容、用途、收益、风险与提交边界的清单。 | 让审阅者逐文件核查范围。 | 是指定基线/HEAD/工作区快照；以后新增文件需更新。 |
| [docs/php70-security-design.md](../docs/php70-security-design.md) | 新增 / 本地 | 本次新增：从漏洞路径到机制、请求生命周期和 CI 的设计说明与 Mermaid 图。 | 说明各层保护如何配合及其边界。 | 图示是模型，不能替代具体 C 控制流和测试结果。 |
| [docs/php70-security-adr.md](../docs/php70-security-adr.md) | 新增 / 本地 | 本次新增：回顾记录关键决策、替代方案、收益、代价与证据。 | 保留为何采取最小适配而没有扩展修复的理由。 | 回顾性 ADR，不是新批准发布或新生产配置。 |

## 验证证据快照（25 个）

| 文件 | 相对基线状态 / 提交状态 | 改动内容与作用 | 收益 | 风险与边界 |
| --- | --- | --- | --- | --- |
| [docs/security/results/alignment-before-fix.txt](../docs/security/results/alignment-before-fix.txt) | 新增 / HEAD | 初版 singleton arm64 地址偏移 4 字节的失败记录。 | 保留本次 7.0 对齐适配的必要性证据。 | 是修正前失败，不是当前分支状态。 |
| [docs/security/results/artifact-log-hashes.json](../docs/security/results/artifact-log-hashes.json) | 新增 / HEAD | 本地原始日志/产物的大小与 SHA256。 | 支持核对既有验证产物。 | 摘要不能替代原文件；原始临时路径可能不再保留。 |
| [docs/security/results/asan-linkage.txt](../docs/security/results/asan-linkage.txt) | 新增 / HEAD | ASan 版本与链接信息。 | 证明受测构建实际关联 sanitizer。 | 只代表对应构建，且不构成全部路径均受检证明。 |
| [docs/security/results/asan-system-allocator-fpm.json](../docs/security/results/asan-system-allocator-fpm.json) | 新增 / HEAD | 历史系统 allocator FPM 结果。 | 单独记录 MM-off 的适用检查与跳过项。 | 历史 7 pass+1 skip，不是当前 11 项的重复完成。 |
| [docs/security/results/baseline-source-sha256.txt](../docs/security/results/baseline-source-sha256.txt) | 新增 / HEAD | 固定原始基线关键源码摘要。 | 支持确认 baseline 身份。 | 只覆盖列出的文件，非完整仓库或二进制签名。 |
| [docs/security/results/build-configurations.json](../docs/security/results/build-configurations.json) | 新增 / HEAD | baseline/hardened/legacy/ASan/Release 的构建配置。 | 将结果绑定受测选项。 | 不是所有编译配置的覆盖清单。 |
| [docs/security/results/ci-boundary-review.json](../docs/security/results/ci-boundary-review.json) | 新增 / HEAD | 本地纯镜像及 Rosetta amd64 验证；保留原 probe 失败与修正后结果。 | 区分模拟与原生，并保留测试构造修正的证据。 | 其中 unverified 为当时快照，后续原生 CI 结果另见运行链接。 |
| [docs/security/results/ci-first-hosted-run.json](../docs/security/results/ci-first-hosted-run.json) | 新增 / HEAD | e4f3878 的首轮 PR 10/10 与重复 push 9/10。 | 如实记录下载基础设施失败与重复执行。 | 不是最终 7cd812 的成功运行证据；旧失败发生在 PHP 构建之前。 |
| [docs/security/results/docker-memory-debug.json](../docs/security/results/docker-memory-debug.json) | 新增 / HEAD | Debug 的 7 组 cgroup 结果、限额、日志和二进制摘要。 | 验证受限内存下 PHP/kernel 两类退出及 worker 恢复。 | 仅对应 Linux arm64 Debug；不覆盖所有内核 victim 策略。 |
| [docs/security/results/docker-memory-release.json](../docs/security/results/docker-memory-release.json) | 新增 / HEAD | Release 的 7 组 cgroup 结果、限额、日志和二进制摘要。 | 补非 Debug 运行期压力证据。 | 仅对应受测二进制与 cgroup，不等于主机 OOM 验证。 |
| [docs/security/results/hardened-asan-fpm.json](../docs/security/results/hardened-asan-fpm.json) | 新增 / HEAD | 历史 hardened ASan 的 9 项 FPM 结果。 | 记录当轮 worker 与 Session 生命周期。 | 历史子集，不是新增 11 项工具再次执行的结果。 |
| [docs/security/results/hardened-asan-native.json](../docs/security/results/hardened-asan-native.json) | 新增 / HEAD | hardened ASan 的 13 项原生结果。 | 支持对应模式、对齐和失败入口验证。 | 只覆盖明确列出的入口与受测架构。 |
| [docs/security/results/hardened-asan-source-sha256.txt](../docs/security/results/hardened-asan-source-sha256.txt) | 新增 / HEAD | hardened ASan 的关键源码摘要。 | 将当轮构建与关键源文件关联。 | 源码摘要不等于完整配置、二进制或全部路径证明。 |
| [docs/security/results/hardened-debug-fpm.json](../docs/security/results/hardened-debug-fpm.json) | 新增 / HEAD | 历史 hardened Debug 的 9 项 FPM 结果。 | 记录当轮 worker 与 Session 生命周期。 | 历史子集，不是新增 11 项工具再次执行的结果。 |
| [docs/security/results/hardened-debug-native.json](../docs/security/results/hardened-debug-native.json) | 新增 / HEAD | hardened Debug 的 13 项原生结果。 | 支持对应模式、对齐和失败入口验证。 | 只覆盖明确列出的入口与受测架构。 |
| [docs/security/results/hardened-debug-source-sha256.txt](../docs/security/results/hardened-debug-source-sha256.txt) | 新增 / HEAD | hardened Debug 的关键源码摘要。 | 将当轮构建与关键源文件关联。 | 源码摘要不等于完整配置、二进制或全部路径证明。 |
| [docs/security/results/hardened-release-fpm.json](../docs/security/results/hardened-release-fpm.json) | 新增 / HEAD | 历史 hardened Release 的 9 项 FPM 结果。 | 记录当轮 worker 与 Session 生命周期。 | 历史子集，不是新增 11 项工具再次执行的结果。 |
| [docs/security/results/hardened-release-native.json](../docs/security/results/hardened-release-native.json) | 新增 / HEAD | hardened Release 的 13 项原生结果。 | 支持对应模式、对齐和失败入口验证。 | 只覆盖明确列出的入口与受测架构。 |
| [docs/security/results/hardened-release-source-sha256.txt](../docs/security/results/hardened-release-source-sha256.txt) | 新增 / HEAD | hardened Release 的关键源码摘要。 | 将当轮构建与关键源文件关联。 | 源码摘要不等于完整配置、二进制或全部路径证明。 |
| [docs/security/results/legacy-debug-fpm.json](../docs/security/results/legacy-debug-fpm.json) | 新增 / HEAD | 历史 legacy Debug 的 9 项 FPM 对照。 | 验证原有对照语义而非假定硬化未起作用。 | unsafe 对照结果不能用于生产安全保证。 |
| [docs/security/results/legacy-debug-native.json](../docs/security/results/legacy-debug-native.json) | 新增 / HEAD | legacy Debug 的 13 项原生对照。 | 显示旧 bailout/exit 与新 fail-stop 的差异。 | 测试刻意保留不安全路径，只能隔离执行。 |
| [docs/security/results/legacy-debug-source-sha256.txt](../docs/security/results/legacy-debug-source-sha256.txt) | 新增 / HEAD | legacy 构建的关键源码摘要。 | 关联对照源文件。 | 宏配置还须结合 build-configurations，不能仅看文本摘要判断模式。 |
| [docs/security/results/old-extension-compatibility.json](../docs/security/results/old-extension-compatibility.json) | 新增 / HEAD | 原始扩展可加载，但旧 inline guard 仍 bailout 的实证。 | 证明“能加载”与“具备新保护”不同。 | 只覆盖受测扩展及加载方向，非任意扩展兼容承诺。 |
| [docs/security/results/phpt-summary.json](../docs/security/results/phpt-summary.json) | 新增 / HEAD | 历史完整基线/硬化 PHPT 结果、状态变化和新增失败 diff。 | 公开 35/44 个失败与有意兼容变化，不隐藏回归。 | 全量并非全绿；解释规则与 diff 需人工审查，不能替代新版本重跑。 |
| [docs/security/results/static-abi-review.json](../docs/security/results/static-abi-review.json) | 新增 / HEAD | 公共结构/标识未改、27 个 VM guard 和 legacy helper 保持的静态核查。 | 支持最小布局扰动与生成物审查。 | 静态 ABI 证据不等于所有二进制扩展均已动态验证。 |

## 不能从文件清单推导的结论

1. 本分支是非官方 EOL 最小缓解，不是受支持 PHP 完整修复，也不是全部 PHP 7.0 历史漏洞修复。
2. 现有公共结构布局和 API 数值未改，不等于旧扩展中的 inline guard 已更新；扩展需用匹配头重编。
3. 原生 CI 的 10 job 成功不等于完整 PHP PHPT 全绿，也不覆盖 32 位、ZTS、Windows、mod_php、任意自定义 allocator/回调。
4. 两条本地新测试仅证明其已执行的本地场景；没有把它们计入远程结果。此次三份文档不会改变运行时或增加 CI job。

## 如何复核清单

```sh
git diff --name-status bf574c2b67a1f786e36cf679f41b758b973a82c4 7cd812eb6e074a723483c727fac49aca8816befa
git status --short
git ls-files --others --exclude-standard
```

旧证据按各自源码、二进制、配置和运行时点解读；后续新增提交或文件后应重新盘点。
最新已核实的远程成功记录为 [run 39941839719](https://github.com/fangfengxiang/php-src/actions/runs/39941839719)，
对应上面的 HEAD，10 组成功；它没有包含尚未提交的 2 条 PHPT 和本次 3 份文档。
