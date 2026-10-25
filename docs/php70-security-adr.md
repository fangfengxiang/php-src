# PHP 7.0 安全回移植：关键决策 ADR

记录日期：2026-10-24。实现快照：`7cd812eb6e074a723483c727fac49aca8816befa`。
基线：`bf574c2b67a1f786e36cf679f41b758b973a82c4`（PHP 7.0.33）。
本文回顾记录已经体现在源码中的决策，不表示本次文档又引入一套运行时设计，也不构成发布批准。
文件范围见[完整清单](php70-security-change-inventory.md)，调用关系和流程图见[设计说明](php70-security-design.md)。
文中 HEAD、本地文件与 CI 状态均指上述实现快照及本批提交前的验证时点，不是实时分支状态。

| 编号 | 决策主题 | 当前状态 |
| --- | --- | --- |
| ADR-001 | 只做目标 CVE 的 EOL 最小缓解及必要适配 | 已采纳；范围原则另保存在本地 AGENTS.md，尚未提交 |
| ADR-002 | 默认 hardened，编译期选择 unsafe legacy | 已实现于 HEAD |
| ADR-003 | 已覆盖 OOM/尺寸错误 fail-stop，普通 fatal 保留语义 | 已实现于 HEAD |
| ADR-004 | 保留清理顺序，只在指定点重置引用 | 已实现于 HEAD |
| ADR-005 | 硬关闭 Session Upload Progress，保留原回调链 | 已实现于 HEAD |
| ADR-006 | 对 retained headers 与 part 数量做有界限制 | 已实现于 HEAD |
| ADR-007 | 宽度安全的上限算术与独立 substring helper | 已实现于 HEAD |
| ADR-008 | singleton 必须成套适配 PHP 7.0 的对齐表示 | 已实现于 HEAD |
| ADR-009 | 以 PHP 7.0 模板和生成器维护 VM guard | 已实现于 HEAD |
| ADR-010 | 保留公共布局/API 数值，扩展重编是保护边界 | 已实现并有受测扩展证据，不承诺任意扩展兼容 |
| ADR-011 | 安全门禁分层，CI 去重和执行预算，结果按版本归属 | 已实现于 HEAD；本地新增两条 PHPT 尚未进入远程 |

## ADR-001：修复目标与变更准入

**背景。** PHP 7.0 已无完整维护路线。本次要适配的是 CVE-2026-109618 / CVE-2026-109619，
不是顺便修复所有历史缺陷。较新受支持分支的完整 OOM/VM 方案与 7.0 差异很大。

**决策。** 以 [PHP 7.4 官方 EOL 最小缓解 712e60f9](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2)
为直接机制依据；按 7.0 真实表示与生命周期作必要适配。每个运行时变更必须关联目标漏洞路径，
或有证据表明它修正了本次改动引入的问题。原有无关 PHP bug 只记录、不修改。

**未采用。** 整体移植新 PHP 的 delayed soft OOM/VM 安全点架构；以安全 PR 为由统一旧代码风格、
修 legacy 的历史 ctype/格式化问题、根据“字段未全清零”猜测扩大重置范围。

**收益与代价。** 范围可审查、较少扰动 7.0；代价是只获得最小缓解的有限保证，未覆盖的历史漏洞仍存在。
这不是自动采纳外部 P0 清单的依据。

**证据与约束。** `security/backport-matrix.md`、`security/repair-map.md`、
`security/report-review-2026-10-24.md` 和根 `AGENTS.md`。
新增 VM guard 需要修生成器、singleton 需要修对齐，均有直接依赖关系；与此不同的历史清理不纳入。

## ADR-002：使用编译期常量，保留隔离比较构建

**背景。** OOM 路径不能为判断策略再读取复杂配置或分配内存，各层也不能在同一请求混用不同模式。
同时需要与旧行为作可靠对照。

**决策。** `configure.in` 默认启用 hardened；显式 `--disable-php70-security` 仅创建 unsafe legacy。
由 `Zend/zend_security.h::php70_security_is_hardened()` 返回编译期 0/1。新增小 helper 保持在原文件，
不加入动态 Hook 框架。

**未采用。** INI 动态开关、请求级切换、函数指针策略分派，以及将 legacy 当作生产故障回退。

**收益与代价。** 失败路径无需配置查询/分配，跨层策略一致；模式变更必须 clean、重新编译并匹配扩展头。
表示/工具不变量和新增声明仍存在于两种变体，因此 legacy 不等于基线逐字节重现。

**证据。** `configure.in`、`Zend/zend_security.h`、`Zend/zend_alloc.h`、构建配置和 native probe 的 hardened 字段。

## ADR-003：危险内存失败终止进程，不扩大到全部 fatal

**背景。** 旧分配失败的 non-local jump 可以把不完整状态带入 PHP 清理、析构或退出回调。
只改 Zend MM 中一个函数还不足以覆盖独立的算术、Hash、字符串、VM 和 dtoa 错误入口。

**决策。** 对已映射的分配/尺寸错误使用 hardened reporter 或对应硬退出路径。
reporter 用固定栈缓冲、libc 格式化和 stderr，随后 `_exit(1)`，不调用常规 Zend 错误链。
系统 allocator OOM/panic 保留各自诊断并增加 hardened 硬退出；原 Debug panic 信号行为不重写。
普通 fatal、parse error 和 timeout 不一律改成 `_exit()`。

**未采用。** OOM 后继续原 bailout 清理；在不可信中间状态上尝试完整回滚；为保护旧扩展而拦截所有普通 fatal。

**收益与代价。** 阻断已覆盖入口进入危险清理；代价是业务 shutdown/destructor/output 收尾和 C atexit 不执行，
进程可能需要监督器替换。线程或内嵌 SAPI 影响整个宿主进程，FPM child 结论不能泛化。
reporter 避免 Zend 分配，不意味着 libc 操作是 async-signal-safe 或任意堆破坏下可用。

**证据。** `Zend/zend_alloc.c`、`zend_multiply.h`、`zend_hash.c`、`zend_strtod.c`、`zend_vm_def.h`；
hard_oom/size_overflow/ordinary_fatal PHPT、native/FPM 结果。dtoa 定向失败仍未注入；ASan 无报告不是全部入口无缺陷的证明。

## ADR-004：沿用原所有权与清理顺序，只做指定引用重置

**背景。** worker 全局槽位可能比请求堆长寿。仅在下一请求 RINIT 重置太晚；
但提前全局清零或重排析构也可能破坏原所有权、隐藏引用或改变回调行为。

**决策。** SAPI/HTTP globals 在各自原释放/析构成功后立即置 NULL/UNDEF；
Executor 在原 shutdown 清理末尾执行无析构 reset；链表在原节点销毁后清端点；请求关停末重置模块标志。
只覆盖本次上游相关字段。

**未采用。** 将整个 EG/SG/PG 结构 memset；把全部释放挪到新统一函数；对未经证明的 free_list_head 等字段扩展重置。

**收益与代价。** 解除选定悬空引用，同时保留生命周期顺序；并不证明所有扩展状态安全。
原清理被中断时，未到达的重置点不能宣称已执行；`zend_try` 不是事务回滚。

**证据。** `Zend/zend_execute_API.c`、`Zend/zend_llist.c`、`main/SAPI.c`、`main/main.c`；
同 PID fatal 后的正常请求、早期 INI diagnostic 与 FPM 复用检查。
正常下一请求会重新初始化对象池；假设提前创建对象还需具体消费者路径和复现，不能仅凭字段值定性 P0。

## ADR-005：在 hardened 中无条件禁用 Session Upload Progress

**背景。** multipart 的 Session progress 回调能够早于本次模块 RINIT 执行，属于目标漏洞的已知早期链路。
脚本中的 ini_set 已经太晚，改变默认 INI 也可被配置覆盖。

**决策。** `php_session_rfc1867_callback()` 保持原 callback chain 的执行顺序和返回值；
hardened 随后直接 return，不执行 Session progress。普通 Session 与上传功能保留。

**未采用。** 只把 enabled 默认值改 Off；让运行期配置重新开启；删除全部上传回调链；重排所有扩展 RINIT。

**收益与代价。** 移除已知的 RINIT 前 Session progress 消费路径；明确损失上传进度功能，
即使 INI 显示 On 也不会恢复。原第三方 callback 仍可执行，本决策不是对所有 early callback 的证明。

**证据。** `ext/session/session.c`；upload_progress_disabled PHPT；
FPM 强制 INI/PHP_VALUE On、OOM 后续请求、普通 Session 和文件上传检查。

## ADR-006：限制保留头与被计数 part，复用原拒绝清理

**背景。** 无关/重复头、空文件控件和输入树能放大内存压力。只统计成功上传文件会漏掉其他引发分配的 part。

**决策。** hardened 只保留首个 Content-Disposition 与 Content-Type。
有 Content-Disposition 的 part 在处理其字段/文件元数据前检查并消费总 part 限额，包含空 filename；
超限发 warning 后跳原 `fileupload_done`，保留此前已接收的数据。

**未采用。** 保存所有头；只数非空或成功文件；超限后再设计一套不同的清理链；宣称 part 限额就是总 body 字节限额。

**收益与代价。** 减少已覆盖的 retained headers 与 part 驱动分配。
取首个头、忽略其他头和截断后续 part 均是兼容变化；缺失/不可信 Content-Length 时未新增 decoded body 总字节限制。
巨大字段或头仍可使 worker fail-stop，不能据此保证无 DoS。

**证据。** `main/rfc1867.c`、`main/main.c`；duplicate_headers、part 限额系列与 FPM header pressure。
真实文件在超限后的完整保留由本地新 PHPT 补测，尚不计入远程 HEAD 的 12 条结果。

## ADR-007：使用 7.0 合适的宽度和算术，不改变 legacy helper 契约

**背景。** 7.0 的 INI 数值为 zend_long，机械缩成 int 或使用未经检查的加法/预减会带来额外问题。
长度处理也不能将 size_t 的输入在 hardened 下继续缩到 int。

**决策。** part 剩余数和显式上限使用 zend_long；派生和饱和到 ZEND_LONG_MAX，先与零比较再减。
文档化默认 -1 走派生，显式非负值直接使用；实现中其他负值也走派生分支。
新增同文件 `substring_conf_hardened(size_t)`，保留 `substring_conf(int)` 及 legacy 原契约，调用点按模式分支。

**未采用。** 照抄上游 int/predecrement；改变旧函数签名；合并两个 helper 并顺手改旧解析器；调整无实际消费者的 legacy 限额哨兵。

**收益与代价。** 避免本次新增上限带来的缩窄、求和或扣减问题，保持对照意义；代价是保留两个私有 helper。
极大长度边界不能通过真实分配任意巨大的输入来穷举，需结合静态约束和原生 probe。

**证据。** `main/rfc1867.c`；default/zero/large/saturate PHPT、原 helper 与固定基线逐字比较。
派生零和真实数据保留两条本地新测试在 hardened 通过，在原始基线按预期不满足新行为。

## ADR-008：singleton 与 HashTable 对齐必须成套适配

**背景。** 降低输入小数组初始容量需要 singleton。普通 array_init_size(1) 会被旧最小容量规则提升，
直接照搬新版本 helper 则忽略 7.0 的索引前缀表示差异，可能产生四字节错位。

**决策。** 新 API 复用原惰性初始化后设逻辑容量 1。
mixed 初始化与 packed→hash 转换均为容量 1 保留至少两个 uint32 索引槽；保持分配大小、mask 和地址计算一致。
此对齐是两种构建共同的固定不变量，不按请求切换，也不整体迁移 7.4 HashTable 结构。

**未采用。** 仅 array_init_size(1)；只改 constructor 不改布局；只修 mixed 初始化而漏 packed 转换；
把地址整除 sizeof(Bucket) 当作对齐标准。

**收益与代价。** 降低输入放大并满足实际对齐，保留既有公共结构。
适配需覆盖增长、packed/mixed、稀疏键、COW、复制、排序等行为；32 位尚未实测。

**证据。** `Zend/zend_API.c/h`、`Zend/zend_hash.c`、`main/php_variables.c`；
`alignment-before-fix.txt`、实际 alignment probe、singleton_input_arrays PHPT、原生 amd64/arm64 CI。

## ADR-009：用 PHP 7.0 模板及生成器维护 VM 保护

**背景。** 7.0 与其他大版本的操作码实现、专用 handler、常量环境不同。
只改定义源或只手改生成头均可能让实际执行路径与审阅内容脱节。

**决策。** 在 7.0 VM 定义的三个拼接分配点增加原位 guard；使用 PHP 7.0 生成器生成专用 handler，
仅为这次可靠生成将无效正则 /me 修为 /m。提交的执行头新增 27 个 guard、108 行。
CI 再生成并逐字比较 execute/opcodes 头。

**未采用。** 从 7.4/8.x 粘贴生成头；用 PHP 8 执行旧生成器；只手维护生成物；借此整体重构生成器。

**收益与代价。** 保持 7.0 操作码和操作数所有权，防止模板/生成物漂移。
必须保留同步生成步骤；生成文件体积和专用路径数量增加了审查成本。

**证据。** `Zend/zend_vm_def.h`、`Zend/zend_vm_execute.h`、`Zend/zend_vm_gen.php`、`ZSTR_MAX_LEN`；
静态移除新 guard 后与基线一致的记录和 CI 字节比较。`zend_vm_opcodes.h` 未改变，不计为新增改动文件。

## ADR-010：保持已有公共布局与 API 数值，明确扩展重编边界

**背景。** 尽量少扰动旧扩展是适配目标，但头文件内联 guard 已编入扩展自身机器码，不能由新运行时替换。

**决策。** 采用少量新增 helper、声明、宏；保留现有公共结构布局和 API 标识：
PHP_API_VERSION/ZEND_MODULE_API_NO 为 20151012，ZEND_EXTENSION_API_NO 为 320151012。
生产扩展使用匹配 hardened 头重编并单独验证。

**未采用。** 改动公共结构来照搬新版本；将“旧扩展可加载”解释为“旧 guard 已安全”；
为补旧扩展而改变全部普通 fatal 语义。

**收益与代价。** 控制布局扰动，保留受测旧扩展的加载能力；旧 inline guard 仍可能走旧错误链。
新增符号也不保证使用新头编译的扩展可装回原始运行时；不承诺任意平台、模式或第三方扩展的 ABI。

**证据。** `security/results/static-abi-review.json`、`old-extension-compatibility.json`、
`Zend/zend_API.h`、`Zend/zend_alloc.h`、`Zend/zend_multiply.h`。

## ADR-011：验证分层、CI 去重与按快照陈述结果

**背景。** 编译、PHPT、原生 probe、FPM、ASan、kernel OOM 分别回答不同问题。
早期 push+PR 同时触发重复矩阵，且一次 Bison 网络失败发生在 PHP 构建之前，不能当作安全回归。

**决策。** 保留原生 10-job 安全矩阵；只监听当前安全分支 push 自动运行，并保留手动入口。
从 checkout 干净构建 PHP 7.0.33；限定 job/步骤预算，网络有超时/重试/备用源和摘要校验。
测试保持真实退出码和失败 diff；ASan 显式传子进程环境，MM-off 单独解释。
完整基线比较另运行，不把它混入每次安全门禁或将全部历史测试称作全绿。

**未采用。** push/PR 重复跑 20 job；使用系统或 PHP 8 二进制替代本分支；
删除旧测试或忽略失败涂绿；无限下载等待；在共享 runner 做 host-wide OOM；为了缩短 CI 隐藏安全用例。

**收益与代价。** 安全覆盖有重复性、运行成本有执行预算，网络失败与 PHP 断言失败可区分。
队列时间不受 job 上限约束，下载依赖/runner 仍可能失败；10-job 通过不是完整安全证明。

**证据。** `.github/workflows/php70-security.yml`、[php-cve-e2e](https://github.com/fangfengxiang/php-cve-e2e) `php70/harness/`、
[run 39941839719](https://github.com/fangfengxiang/php-src/actions/runs/39941839719)：
7cd812 原生 10 组成功，2026-10-23 北京时间 18:49:50–18:54:19，4 分 29 秒。
HEAD 的 12 条安全 PHPT 已进入该轮；本地另两条只有 9/9 邻近回归的本地证据，不能算远程 14 条已通过。
历史全量比较保留 35/44 个失败，其中 9 个新增差异逐项解释；汇总工具不能替代失败 diff 审查。

## ADR-012：沿用 php-src 的 PHPT 归属，外部工具只有一份实现

**背景。** `431276f` 的远程运行暴露了外部 checkout 绝对路径、Bison 3.8 与 PHP 7.0
parser 不兼容、push/PR 重复运行及 progress 旧预期冲突。删除旧工具时也丢失了尚未迁移的
RPM/cgroup 覆盖。历史修复 `d4dee4a6144` 将代码修复与 `Zend/tests/bug75573.phpt` 一起提交；
`.travis.yml`、AppVeyor 和 `Makefile.global` 都调用仓库自己的 `run-tests.php`。

**决策。** PHP 源码、PHPT 用例、runner、用例选择和 PHPT 结果门禁属于 php-src，保留原位。
本仓库 `.github/php70/` 只包含 PHPT/VM 的 CI 调用与完整性检查。Dockerfile、构建脚本、
native probe、FPM、cgroup 和 behavior/trace 统一维护于 php-cve-e2e，不保留本地工具副本。
外部调用契约见 [php70/CI.md](https://github.com/fangfengxiang/php-cve-e2e/blob/a03ad2f4c092004f651da1e890c61c5848d5ca7d/php70/CI.md)。

所有 job 固定同一外部提交，source/harness 同级检出，结果放 runner temp；
构建后使用本分支 PHP 7.0.33 执行原有 `run-tests.php`，不修改 runner 或运行时代码。
14 条安全 PHPT 必须完整通过且不可 skip。受影响目录集成明确列出 8 条依赖已禁用
progress 功能的旧用例，其替代安全断言必须通过；不把选择后结果说成原始目录全绿。

保留 Debian/CentOS 7/8/9/UBI 9、arm64、ASan 与 cgroup 验证，三构建/trace 集中在 Debian。
只监听当前分支 push 与手动入口；job/步骤设预算。上传有限证据，不上传完整源码/安装树。
Pages 必须等待全部门禁通过，报告生成成功不能代替测试通过。

**边界。** 此 CI 不是完整 baseline/hardened PHPT 比较或所有 CVE 变种的修复证明。
PHPT 与平台原始证据单独上传；外部 HTML 报告尚不合并平台矩阵，不宣称已包含它。
维护者可在外部项目继续优化缓存、构建复用和报告，但不能削弱现有断言或吞掉失败。

## 后续决策的准入规则

只有目标漏洞的必要修复、必要 7.0 适配或本次引入回归才进入本 PR。
如果发现未覆盖路径，应先给出生产者、生命周期窗口、可达消费者及代码/测试证据，
再决定是否修改。对于 mod_php/ZTS/32 位等验证空白，按真实部署需要补验证，
不自动扩展成新平台实现、全局状态重置或 PHP 历史缺陷治理项目。
