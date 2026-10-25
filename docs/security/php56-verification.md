# PHP 5.6.40 回移植：验证记录

日期：2026-10-25。PR：https://github.com/fangfengxiang/php-src/pull/2。
官方基线：4b8f72da5dfb201af4e82dee960261d8657e414f。
本记录描述非官方 EOL 最小缓解的实际验证，不是完整漏洞消除或生产发布证明。

## 已执行结果

| 二进制与方式 | 定向 PHPT | 原生边界检查 | 私有 socket FPM |
|---|---:|---:|---:|
| Linux arm64 / Clang Debug，真实运行 | 11/11 PASS | 12/12 | 13/13 |
| Linux arm64 / Clang Release，真实运行 | 11/11 PASS | 12/12 | 13/13 |
| Linux x86_64 / GCC Debug，amd64 仿真执行 | 11/11 PASS | 12/12 | 未运行 |

所有测试使用对应快照自行编译的 PHP 5.6.40。无主机 PHP 代跑。
Debug/Release 的全部运行时代码哈希与当前分支一致；x64 初版快照仅少后续新增的
noreturn 声明，故不将其当作包含最后声明修正的二进制验证。
未修改基线在两种架构也实际完成 Debug 构建。Release 没有另做全套基线比较。

## 全套 PHPT 的固定基线对照

相同 arm64 Clang 工具链、Debug 配置、离线容器、明确测试文件清单：

| 快照 | 总数 | PASS | FAIL | SKIP | XFAIL |
|---|---:|---:|---:|---:|---:|
| 原始 PHP 5.6.40 | 13,882 | 7,731 | 66 | 6,041 | 44 |
| hardened | 13,893 | 7,733 | 75 | 6,041 | 44 |

新增 11 项全部 PASS。共同 13,882 项中，13,873 项状态一致，9 项 PASS→FAIL：

- ext/session/tests/rfc1867.phpt
- ext/session/tests/rfc1867_inter.phpt
- ext/session/tests/rfc1867_sid_cookie.phpt
- ext/session/tests/rfc1867_sid_get.phpt
- ext/session/tests/rfc1867_sid_get_2.phpt
- ext/session/tests/rfc1867_sid_invalid.phpt
- ext/session/tests/rfc1867_sid_only_cookie.phpt
- ext/session/tests/rfc1867_sid_post.phpt
- tests/lang/bug45392.phpt

前八项检查被有意禁用的内置上传进度。通常差异为预期进度数组变为 NULL；
sid_invalid 的早期非法 SID 打开警告消失，文件上传数据仍存在。
最后一项只有 OOM 诊断前多一个空行（.diff 的唯一行是 002+）。
这是官方式固定缓冲 stderr reporter 的格式变化。原始测试期望保留，便于对照；
没有通过删除测试或更改 legacy 期望制造全绿。
没有未解释的新增失败；原有 66 项 FAIL 不在此次修复范围，未顺便修改。
这不是“全套测试通过”。SKIP 与 XFAIL 也不是已验证行为。

每个变化的原 .diff/.out/.exp 归档在 results/2026-10-25/changed-expectations。
PHPT 标题包含括号和换行，初版 runner 的结果解析漏项；已从同一原始日志用修正
parser 重建逐路径结果并记录 postprocessing，没有重跑或改写 PHP 输出。

## FPM 的实际生命周期证据

脚本自行启动一个 static child 的本分支 FPM，Docker --network none，仅 AF_UNIX：
五次连续请求同 PID；正常 Session 读写；普通表单和真实临时文件上传；
INI=1 时无上传进度；普通 fatal 执行 shutdown callback 且下一请求仍同 PID；
安装错误与异常处理器后，下一请求的 iconv.input_encoding 早期 INI 诊断不调用旧处理器，
后续请求仍同 PID。memory_limit=8M 的脚本真实 OOM 令 child exit code 1，
不生成 shutdown/destructor marker，master 存活并提供新 child，Session 数据仍可读取。

这些是请求阶段 OOM 的 fail-stop 证据，不是“FPM 启动失败后仍复用旧 worker”的证据，
也不等于重现远程命令执行。没有伪造请求堆或攻击外部服务。

## 原生检查与证据等级

真实执行：正常退出/普通 fatal 的 PHP shutdown 与 C atexit 阳性对照；
safe_emalloc 乘法/加法溢出、safe_emalloc_string 的 INT_MAX 边界；
libc malloc(SIZE_MAX) 的真实失败；ZE2 输入数组的 12 个容量/mask/值快照。
请求表第一项 mask=1、capacity=2，第三项增长为 capacity=4；普通数组仍保持原最小容量8。

五个字符串检查使用小缓冲和合成长度元数据，仅验证 guard 顺序及退出边界；
不声称真实分配超大字符串，也不是远程可利用性证明。
C atexit 对照设置 ZEND_DONT_UNLOAD_MODULES=1，防止模块 dlclose 改变 marker 意义。
初版系统 malloc 探针的未使用结果被 -O2 优化消除，已添加 volatile sink 后重新执行；
归档通过结果来自修正后的探针，不把首次工具失败归为生产代码问题。

## 基线已有问题与工具链限制

GCC 12 编译原始 arm64 Debug 的 ZEND_SIGNED_MULTIPLY_LONG 时，旧 X 汇编约束选择了
内存或浮点寄存器，在 -O0/-O2 都失败。Clang 能编译原样代码，本次不修该无关问题。
arm64 真机运行采用 Clang 14.0.6，x64 使用 GCC 12.2 / amd64 仿真，Bison 3.5.1。

早期 INI 诊断的 Debug 日志还报告 3 块 64/72/76 bytes 的 date tzcache 泄漏。
未修改基线的普通 early-INI-only 对照复现相同分配点和大小：
main/main.c php_log_err → php_format_date → php_date_parse_tzfile 建立请求 tzcache，
随后 date RINIT 把 tzcache 置 NULL。该路径未被补丁改动，只记录，不修复。
FPM 13 项行为检查通过不等于“无 Debug 泄漏”。

## 证据与复现

results/2026-10-25/summary.json 包含计数、源码/二进制哈希、配置和归档 SHA256；
comparison.json 可逐路径检查全部共同状态变化及新增测试；toolchain.json 记录实际工具版本。
*.tar.gz 包含原始 PHPT/JUnit/状态、native 子进程输出、FPM 请求/配置/日志和构建日志。
原始构建目录与首次失败日志还保留在 worktree 的 .security-build，未提交二进制。

固定工具链容器内，使用 docs/security/testing 下的脚本：

```sh
bash php56-build.sh --src /work/fresh-src --output /work/build-log --mode Debug --compiler clang --jobs 4
python3 php56-phpt.py --src /work/fresh-src --output /work/target --targeted
python3 php56-phpt.py --src /work/fresh-src --output /work/full --full
python3 php56-native.py --src /work/fresh-src --output /work/native --cc clang
python3 php56-fpm.py --fpm /work/fresh-src/sapi/fpm/php-fpm --evidence-dir /work/fpm
python3 php56-fpm.py --fpm /work/baseline/sapi/fpm/php-fpm --evidence-dir /work/early --early-ini-only
python3 php56-phpt.py --compare /work/baseline-full/result.json /work/full/result.json --output /work/compare
```

fresh-src 必须来自固定 commit 的干净 git archive；output 须使用新目录。
原生/PHPT 脚本会核对 PHP 版本并记录二进制 SHA。Docker 运行须 --network none。
GitHub CI 只增加单一 Linux amd64 runner，在其中构建 Debug/Release 并跑定向/native/FPM，
保留所有输出；Bison 来源与校验和沿用 PHP 7.0 已审查工具链。首轮 GitHub run 40177481468 在真实 Linux amd64 GCC 上，两种构建各完成定向11、
native12、FPM13，运行步骤成功；整项 CI 因 root-owned 0700 临时证据目录的上传
EACCES 失败。原日志已归档。CI trap 已改为在容器退出时给合成测试证据加 a+rX，
等待后续 run 验证上传修正。文档/结果提交不再重复触发编译，测试和代码变化仍触发。

## 尚未验证的范围

mod_php、独立 APACHE_HOOKS 生命周期、Windows、ZTS、32位、ASan、任意第三方
callback/custom allocator、dtoa 分配失败注入、真实主机/容器物理内存耗尽及超时中断。
没有新增无 Content-Length 场景的 decoded-body 字节限制，worker-exit DoS 仍可能发生。
本次不涵盖 PHP 5.6 EOL 后的其他漏洞。保持草稿待独立安全审查和部署环境验证。
