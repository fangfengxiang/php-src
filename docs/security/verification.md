# PHP 7.0.33 非官方安全回移植：验证记录

执行日期：2026-10-22 至 2026-10-23。基线：`bf574c2b67a1f786e36cf679f41b758b973a82c4`。
分支：`security/php70-cve-2026-109618-109619`。

**结论：已实现并验证官方 EOL 最小缓解的 PHP 7.0 适配，交付 Draft 审查；尚不认定具备
完整安全修复的发布候选资格。** 原有测试存在已记录失败，Apache/Windows/ZTS/32 位及任意
第三方扩展未验证；旧版本最小缓解也不是受支持 PHP 的完整状态重置方案。

## 环境与构建

所有 PHP 服务测试均在 `--network none` 的 Linux arm64 容器中，FPM 仅监听临时 Unix socket。
没有向公网暴露测试服务。工具链镜像的 Dockerfile 在 [testing/Dockerfile](testing/Dockerfile)：
固定基础镜像摘要、校验 Bison 3.5.1 tar 包 SHA256，使用 GCC 12.2.0、Autoconf 2.69、re2c 3.0。

| 最终构建 | 结果 | 说明 |
| --- | --- | --- |
| hardened Debug | 通过 | 默认安全模式，CLI、CGI、FPM、phpdbg 构建/安装成功 |
| hardened Release | 通过 | 非 Debug 分支也编译和执行测试 |
| hardened ASan Debug | 通过 | GCC `-fsanitize=address`，已核实链接 `libasan.so.8` |
| legacy Debug | 通过 | 显式 `--disable-php70-security`，原始 OOM/Upload Progress 行为作为对照 |

构建过程先遇到 Bison 3.8 生成器不兼容，改用匹配版本；曾发现旧对象引用旧 reporter 符号，
随后执行完整 `make clean` 重建。最终组织调整的并行链接遇到 SIGKILL，改为单任务成功重建；
Docker 中断的重测未记为通过，恢复后对最终源码重新完成干净比较。未把这些失败尝试当成通过。VM 由未修改的 PHP 7.0 二进制
运行本分支生成器生成；27 个新增 guard 去除后，生成头与基线逐字一致。

[build-configurations.json](results/build-configurations.json) 保存 configure 参数/宏，
各构建的 `*-source-sha256.txt` 与当前七个关键源码文件均一致。
完整本地日志保留于 `/tmp/php70-security-validation/`；
[artifact-log-hashes.json](results/artifact-log-hashes.json) 提供摘要，二进制/巨型构建日志没有提交进仓库。

## 安全 PHPT 与原生不变量

| 检查 | 真实结果 |
| --- | --- |
| 11 个新增 PHPT，hardened Debug | 11 通过，0 失败/跳过 |
| 同上，hardened Release | 11 通过，0 失败/跳过 |
| 同上，hardened ASan / Zend MM | 11 通过，0 失败/跳过 |
| ASan / `USE_ZEND_ALLOC=0` | 10 通过，1 跳过，0 失败；有限 memory_limit OOM 不适用于关闭 Zend MM 的构建 |
| native probe，四种构建 | 每种 13 项通过，含模式、结构大小、三类 singleton 对齐、九个分配/溢出入口 |

覆盖：普通 fatal 仍执行 shutdown；OOM 不执行 PHP shutdown/destructor；safe allocation 乘加溢出、
字符串复制长度溢出、huge rounding、Debug 元数据溢出、HashTable 容量、libc malloc 失败；
Session 正常持久化、上传成功但 progress 无法通过 INI 开启；首次必要头保留；part 的
explicit/default/zero/large/saturating 边界；packed/hash/sparse/COW/append 数组行为。

probe 在 legacy 的系统分配失败路径观察到 C `atexit` 回调，而 hardened 不执行它。
其他普通 fatal 的 callback 与真正 OOM 的 fail-stop 已分别测试。

ASan 的直接 allocator 检查有一个重要测试工具适配：PHP 7.0 原 `run-tests.php` 在 SKIPIF 与 FILE
阶段两次强制设置 `USE_ZEND_ALLOC=1`。测试脚本只在容器中生成临时 runner，保留调用者显式的 0，
没有修改运行时源码或 PHPT 安全检查。通过 `variables_order=EGPCS` 传递 sanitizer 环境。
未适配时看似通过的 MM-off 结果已被后续真实结果替代。关闭 leak detection，故不声明泄漏检测通过。

## 同 worker 与 FPM

Debug、Release、ASan、legacy 各完成 9 项检查；未修改的干净基线也完成同样的 9 项对照：

1. 连续正常请求保持相同 PID。
2. Session 写入/读取跨请求持久化。
3. 普通字段与文件上传内容正确。
4. 无关 multipart headers 不再积累保留内存（legacy 对照有相应生命周期预期）。
5. hardened 在 INI On 时仍无 upload progress，legacy 保留进度。
6. 普通 fatal 与 error/exception handler 清理后同 worker 可继续服务。
7. 下个请求的 `PHP_VALUE` 设置 deprecated `iconv.input_encoding`，在正常初始化前实际产生诊断，worker 仍正常响应。
8. 脚本期 memory_limit OOM：hardened 无 shutdown 标记、PID 改变，master 重建 child；legacy 执行 shutdown 并复用 PID。
9. 启动期 multipart OOM：两种模式都不复用 child，符合 PHP 7.0 FPM 原有启动失败退出逻辑。

ASan 系统 allocator 另通过 7 项功能/早期诊断检查；memory_limit 检查明确跳过。
记录见各 `*-fpm.json`。没有使用命令执行、堆布局控制或内存泄露负载。

## PHP 7.0 原有完整测试集

保留原有测试文件和期望，没有为隐藏失败而跳过测试。

| 运行 | 总数 | 通过 | 失败 | 预期失败 | 跳过 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 未修改基线 Debug | 14949 | 10170 | 35 | 45 | 4699 |
| 最终 hardened Debug（含新增 11 项） | 14960 | 10172 | 44 | 45 | 4699 |

完整列表、状态变化及新增失败 diff 在 [phpt-summary.json](results/phpt-summary.json)。
最终比较两侧都从归档重新构建，在相同的容器内部文件系统运行，避免宿主挂载权限影响。
35 个失败与基线相同；仅有 20 个状态差异，即 11 个新增通过和以下 9 个已解释失败：

* 原来的 8 个 `ext/session/tests/rfc1867*.phpt` 正向测试期望 upload progress 存在；hardened 的
  必要兼容性变化使其不成立。文件上传部分仍执行，新测试另外断言 progress 不存在与上传内容正确。
* `tests/lang/bug45392.phpt` 因官方 fail-stop reporter 在 stderr 前加换行，仅多一个空行。
  保留原期望以显示这种输出差异，不把它伪报通过。

初次主机挂载/生成物环境下记录过基线 46、hardened 51 个失败，摘要保留在 JSON 的
`initial_bind_mount_run` 中；不把这种环境差异归功于安全修复。上表以最终双侧干净运行的
35/44 个失败为准，其余原测试状态完全一致。legacy 的 Session/basic/ordinary-fatal 在同类
文件系统定向重跑共 317 项：307 通过、4 失败、2 预期失败、4 跳过；四个失败全是刻意要求
hardened 行为的新测试。完整回归进程退出码为 1，未称作全绿；新增失败不存在未解释项。

## ABI 与扩展

八个涉及公共结构布局的头文件逐字未变，API 数字仍为 PHP/Zend module `20151012`、Zend extension
`320151012`。[static-abi-review.json](results/static-abi-review.json) 保存静态证据。
arm64 Debug 实测 zval=16、zend_string=32、HashTable=56、php_core_globals=656 字节。

未修改的 baseline 编译扩展能加载到 hardened Debug；但其旧内联 guard 仍执行 bailout 与 shutdown，
实测退出码 255。见 [old-extension-compatibility.json](results/old-extension-compatibility.json)。
因此“可以加载”不能代表安全保护已生效，部署必须用匹配的 hardened 头文件重编译扩展。
验证方向是旧扩展加载到新运行时；使用新头文件重编译的扩展可能依赖新增符号，
不保证可装回原始运行时，legacy/hardened 头文件也不应混用。未修改公开结构布局，
不承诺任意扩展、ZTS 或不同平台的 ABI 已通过动态验证。

单 bucket 对齐：适配前 probe 实测 `nTableSize=1`、mask=-1、地址模 pointer alignment=4；
适配后 string/sparse/packed 三类均为 0，hardened 容量仍为 1，legacy 容量仍为 8。
这是 PHP 7.0 与 7.4 hash 表示差异所需的额外修复，不能仅凭 7.1 社区实现假定安全。

## 未执行与剩余风险

* Apache mod_php：容器未配 Apache 开发/模块运行环境，未执行；不能将 FPM 结果泛化至 Apache。
* Linux x86_64、Windows、ZTS、32 位、自定义 Zend allocator、任意第三方扩展 callback：未执行。
* 本次构建禁用 PCRE JIT；OPcache/mbstring 等未启用模块没有定向验证，模块清单见原始日志。
* dtoa Balloc 的定向分配失败注入、真实物理内存压力/内核 OOM-kill、timeout 中断：未执行。
  原生系统分配失败使用立即被拒绝的尺寸哨兵，没有耗尽主机内存。
* ASan 未报告已执行路径的内存错误；这不是所有跨请求 UAF 不存在的证明，也没有运行真实 RCE PoC。
* 未新增无可信 Content-Length 时 decoded body 的实际总字节上限；大 body 仍可造成 worker 退出与 DoS。
* 仅覆盖官方 EOL 缓解涉及的状态，不涵盖受支持 PHP 全量重置中的其他扩展，也不修复 PHP 7.0 EOL 后的其他 CVE。
* Upload Progress 被禁用、OOM 立即退出及部分输入限制均是明确的兼容性变化。

因此交付标记为 **PHP 7.0.33 非官方安全回移植候选版本**，保持 Draft，不能声称两个 CVE 的所有
可能生产者/消费者均已消除。发布前仍需目标部署环境的 Apache/扩展/平台验证和独立安全审查。

复现步骤见 [testing/README.md](testing/README.md)，逐修复点实现理由见 [repair-map.md](repair-map.md)。
