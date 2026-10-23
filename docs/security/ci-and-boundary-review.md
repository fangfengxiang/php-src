# PHP 7.0 分支 CI 与边界测试评估

## 能否在当前分支运行

可以。[工作流](../../.github/workflows/php70-security.yml) 对
`security/php70-cve-2026-109618-109619` 的 push 和仓库 PR 自动运行。
PR 的默认 checkout 是 GitHub 生成的合并提交；push 测试分支提交本身。
不需要先把 workflow 合并进默认分支。手动 `workflow_dispatch` 的可用性则要求
workflow 已存在于默认分支；本分支首次验证应使用 push。Fork 需要启用 Actions，
外部贡献者的 PR 可能需要仓库维护者批准运行。
本 workflow 随安全分支提交；推送该分支即触发漏洞回归 CI，不自动部署或发布二进制。

参考 [PHP 官方 test.yml](https://github.com/php/php-src/blob/master/.github/workflows/test.yml)
与 [test-suite.yml](https://github.com/php/php-src/blob/master/.github/workflows/test-suite.yml)：
采用源码构建、Debug/Release、架构差异、sanitizer、生成文件验证及原生 PHPT runner。
PHP 7.0 原 `.travis.yml` 也包含 Debug/ZTS 和完整 PHPT；现代 PHP 的 JIT 等配置不直接搬到 7.0。

## 已配置的安全门禁

| Docker 用户态 | 架构 | 模式 |
| --- | --- | --- |
| Debian 12 | amd64 | Debug、Release、ASan、legacy Debug |
| Ubuntu 22.04 | amd64 | Debug、Release |
| Ubuntu 24.04 | amd64 | Debug、Release |
| Debian 12 | arm64 | Debug、Release |

10 个 job 使用原生架构 runner，各自从 checkout 归档源码，禁止复用旧 PHP 对象文件。
Docker 模拟发行版用户态，内核来自宿主 runner，因此这不是不同 Linux 内核的验证。
初始发行版均属 glibc/Debian 系；没有覆盖 RHEL/Rocky/CentOS 或 Alpine/musl。
镜像基线以 tag 更新，日志记录实际镜像 ID 和安装包版本；尚不承诺 apt 仓库的字节级复现。
Dockerfile 默认使用纯 Debian 12；CI 通过 BASE_IMAGE 显式选择发行版，
基础镜像不预装任何 PHP。PHP 7.0.33 及 PHPT runner 均使用本分支编译安装的二进制。

每个 hardened job：构建 CLI/CGI/FPM，13 个 native 不变量、11 个 FPM 生命周期检查、
12 个安全 PHPT，以及两个 VM 生成头的字节比较。legacy 只跑 native/FPM 对照预期。
ASan 额外用系统 allocator 跑 FPM 与数组/嵌套上传 PHPT，probe 扩展同样带 ASan 编译选项；
不在系统 allocator 下把 `memory_limit` 当成有效的 OOM 限额。
Debian amd64 Debug 另跑现有 64/96/128 MiB cgroup 测试。
测试容器无网络，FPM 只监听私有 Unix socket。失败保持非零退出，始终上传日志、JUnit、diff。

这是安全回归门禁，不是全量 PHP 功能测试通过证明。既有完整 PHPT 有记录失败，发布前仍需按
[复现说明](testing/README.md) 在同工具链上运行 baseline/hardened 全量对照，检查具体新增失败；
不能通过忽略退出码或粗放的 Session 路径白名单，把完整回归涂绿。
本轮不自动发布二进制；CD 应等全量对照及目标运行环境验证后再确定。

## Grok 提议逐项判断

| 项目 | 判断与处理 |
| --- | --- |
| singleton 对齐 | 高优先级合理。已有三种 native 对齐输入和增长/COW PHPT，本轮额外检查编译器实际 Bucket 对齐要求，并新增 amd64/arm64 Debug/Release 矩阵。同一份 probe/PHPT 在不同架构上运行即可，无需复制三份同义 PHPT。32 位仍待补，多个发行版不等于多个架构。 |
| overflow / bailout 漏口 | 合理，但不是已发现 bug。已有 9 类 native 失败路径和 overflow PHPT。普通用户态 PHPT 无法直接可靠构造 HashTable 内部超大容量，应保留 C probe。`estrdup` 没有外部长度参数，长度溢出应测试 `estrndup` 等接受长度的入口，避免用无效指针伪造测试。dtoa 两处分配失败的定向注入仍未覆盖，不能用现有 allocator 测试替代。 |
| Session upload progress | 原建议第 3 行内容截断。已有强制 INI On 的关闭检查；本轮补 FPM PHP_VALUE On 和脚本 OOM 后下一 worker 的 progress 检查。 |
| stale globals | 代码已经清空 error/exception handler 及其 stack、EG(exception)、object_buckets 和 top；不是 Grok 暗示的完全漏掉。已有同 PID fatal 复用及 RINIT 前 INI diagnostic。对象存储、output handler 和被中断扩展回调仍不能声称完整覆盖，属于下一轮定向生命周期测试。7.0 不存在的 weakref 等结构不能机械移植。 |
| multipart 限制 | 已有 first-header、unknown-header 压力、派生/0/大值/饱和边界。本轮补嵌套空文件 + 0/999/自动递增索引的增长行为。本轮另验证 FPM 缺失/零 Content-Length 时不解析随附 body、下一次正常上传同 PID 成功；错误非零长度、CGI/其他 SAPI、大 body 与嵌套深度阈值仍需单独测试。 |
| fatal 与 OOM 分裂 | 是预期行为，已有两类 PHPT/FPM 检查。OOM 应退出并换 PID，不能要求 OOM 后同 PID 连续请求；普通 fatal 才要求可复用。原始和 hardened PHP 7.0 对照确认：E_USER_ERROR 执行 shutdown function，但本例不执行对象析构函数；不能把“所有 fatal 都会析构”当作基线。 |
| VM 27 guard | 已有去 guard 后与基线逐字一致的历史证据；本轮新增每次 CI 从当前 7.0 生成器再生成并比较两个头文件。 |
| 旧扩展 inline guard | 已有旧扩展 ABI/旧错误路径实证。新 CI 每次重编 probe，不能替代旧二进制扩展测试；生产扩展仍须重编并做清单验证。 |
| cgroup / 系统 OOM | 已有真实 cgroup OOM，接入单个 CI job。host-wide 接近耗尽不适合共享 runner，且内核 OOM victim 选择无法由 PHP 补丁保证。 |
| ZTS / Windows / 32-bit / mod_php | 有价值但尚未覆盖。应根据实际部署补专用 job；当前 10 组全是 Linux NTS，不能宣称覆盖这些平台。 |

优先补充项：dtoa 可控故障注入、对象/output 回调跨请求消费、32 位原生布局测试，
再按部署需要加 ZTS、Apache 和 musl/Alpine。普通内存分配失败、整数溢出、PHP memory_limit、
内核 OOM 分别保持独立断言；ASan 无报错本身不证明没有走 bailout。

## 本轮本地验证

所有下表测试均使用 PHP 7.0.33。纯 Ubuntu/Debian 工具链不预装 PHP，测试与生成器使用
本分支编译安装的 PHP 7；构建脚本另有 PHP_VERSION_ID=70033 硬断言。

| 环境 | Native probe | FPM | 安全 PHPT | VM 两个生成头 |
| --- | --- | --- | --- | --- |
| 纯 Ubuntu 22.04 arm64 Debug | 13/13 | 11/11 | 12/12 | 逐字一致 |
| 纯 Debian 12 amd64 Debug，Docker Desktop Rosetta 模拟 | 13/13 | 11/11 | 12/12 | 逐字一致 |
| arm64 legacy Debug，对新版 probe 做对照 | 13/13 | 本轮未重跑 | 不适用 hardened 预期 | 本轮未重跑 |

Ubuntu arm64 的 Debug 系统 allocator 模式另通过 8/8 项适用 FPM 检查；这轮不是 ASan，
且明确跳过依赖 Zend MM 的 memory_limit OOM 检查。历史 Debian arm64 和 ASan 结果仍见
[verification.md](verification.md)，不与新纯镜像环境或 GitHub 原生运行混作同一次结果。

复查发现并修正三项测试问题：

* 原 `huge_rounding` 用 `emalloc((size_t)-4096)`，在 4 KiB 页的 x86_64 上已对齐，
  没有触发预期 rounding overflow，最终导致 Rosetta 自身报错并返回信号。
  改用 `-1024`，留出 Debug 元数据空间，又确保页取整溢出；arm64、模拟 amd64 和
  legacy 三种检查均重测 13/13 通过。没有跳过或放宽断言，也没有改 PHP 运行时代码。
* PHPT runner 原先只在第二轮系统 allocator 前设置 EGPCS。现在 ASan job 从第一轮
  PHPT 开始就传递 ASAN_OPTIONS，避免父进程选项未进入被测子进程。
* 普通 fatal 的析构预期先与原始 PHP 7.0 对比：E_USER_ERROR 执行 shutdown function，
  但本例不执行对象析构函数；hardened 保持相同语义。PHPT 检查这一基线，避免套用错误假设。

嵌套空文件用例首轮因原有 `No file uploaded` Notice 失败；按既有空文件用例约定
排除 E_NOTICE 后通过，仍检查所有文件错误码、空路径、大小与索引。
Bucket probe 现在同时检查指针对齐和编译器实际 Bucket 对齐要求。
native harness 失败时会保存已完成检查与失败原因，避免临时容器退出后只剩控制台 traceback。
workflow 通过 actionlint 1.7.12，Python/shell 语法和 git diff 检查通过。

机器可读结果、旧 rounding 失败、修正后的结果、测试脚本及日志哈希保存在
[ci-boundary-review.json](results/ci-boundary-review.json)。原始日志分别位于
`/tmp/php70-ci-check/jammy/logs/`、`/tmp/php70-ci-review/amd64-debug/logs/` 和
`/tmp/php70-ci-review/legacy-probe/logs/`。

GitHub 完整 10 job 矩阵、Ubuntu 24.04、本轮全量 PHPT、32 位、ZTS、Windows、mod_php、
dtoa 定向失败注入仍未执行。模拟 amd64 不等于 GitHub 原生 amd64。

## 远程 PR 与发布门槛

接入 CI 前通过 GitHub 连接核实 [PR #1](https://github.com/fangfengxiang/php-src/pull/1)：
head 为 `security/php70-cve-2026-109618-109619`，base 为固定 PHP 7.0.33 的
`codex/php70-7.0.33-base`，两者同属此 fork。远程 head 是 `0d2be532f76`，
该分支 Actions runs 为 0，该提交 check runs 为 0。以上为接入 CI 前的远程快照，运行状态以 GitHub Actions 为准。
仓库默认 master 是 PHP 8 系列，但不参与该 PR 的编译或目标基线。

1. 提交并推送本分支 CI，取得 GitHub 原生 amd64/arm64 的 10 job 实际结果。
2. 用相同镜像和参数重跑 baseline/hardened 全量 PHPT，对每个新增失败逐项审查。
3. 定向补 dtoa 失败注入与真实部署扩展；部署有 ZTS/mod_php/32 位时相应项成为必需。
4. 门槛完成后再决定发布包和部署；当前证据支持继续审查最小缓解，不支持声称完整修复。

GitHub 官方参考：[工作流事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)、
[runner 架构与标签](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
