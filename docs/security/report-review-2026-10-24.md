# 2026-10-24 外部审查报告复核

## 目标与结论

目标仅为 PHP 7.0.33 适配 CVE-2026-109618 / CVE-2026-109619 的官方 EOL 最小缓解，
以及验证本次适配没有引入回归。其他 PHP 历史缺陷、风格统一和一般重构不纳入。
这一约束已写入仓库根目录 [AGENTS.md](../../AGENTS.md)。

复核执行时的本地与 PR head 均为 `7cd812eb6e074a723483c727fac49aca8816befa`；
固定基线 `bf574c2b67a1f786e36cf679f41b758b973a82c4`。
官方对照为 [PHP 7.4 提交 712e60f9](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2)。

报告对两类漏洞的总体方向有参考价值，但不足以直接作为修改清单：两个 P0 一个误报、
一个缺少可达路径证明；还存在过时源码判断、错误对齐判据和遗漏现有测试的问题。
本轮未发现报告已经证明的新增运行时缺陷，不据此修改 PHP 运行时代码。
仅补两个与新增 multipart 限制直接有关的组合边界测试。

## 按因果关系逐项审查

| 报告主张 | 核对结果 | 本次决定 |
| --- | --- | --- |
| `_estrdup` 格式串 P0 不匹配 | `Zend/zend_alloc.c:2626` 一个 `%zu` 对应一个 `size_t length`，完全匹配。官方 7.4 对应三个入口也使用 `(1 * %zu + 1)`，当前 `_estrndup`/`zend_strndup` 相同。 | 拒绝该修改。报告建议的 `1, length, 1` 还会将两个 `int` 传给 `%zu`，复制 legacy 原有类型问题；不借此修理 legacy。 |
| 必须补 `free_list_head=-1`，否则 P0 | 正常请求经 `init_executor()` 调用 `zend_objects_store_init()`，后者分配新 buckets、设置 top/size/free_list_head。报告未提供此前实际分配对象的可达消费者及本 PR 的回归因果。官方 7.4 收尾也只重置 buckets/top。 | 记为未证实，非 P0 阻塞项，不补该行。上游相同不是安全证明；若有具体提前消费复现再审。仅重置 free_list_head 也无法使 NULL buckets 上的对象写入合法。 |
| singleton 改私有成员破坏封装 | 这是 7.0 缺少新 API 时的明确适配。lazy-init 前设置容量，mixed 初始化和 packed→mixed 都保留两个索引前缀；现有 probe/数组回归覆盖关键不变量。 | 不为抽象风格重构已验证的布局适配。注释可按确有歧义再补，不是漏洞修复门槛。 |
| 要求 `arData % sizeof(Bucket) == 0` | 对齐要求与对象大小不同。应检查 Bucket 的实际 alignment；现有 probe 用 offsetof 得到对齐要求并断言，而非错误地要求地址整除结构大小。 | 不采用错误断言。32 位仍未验证，但不能把此错误判据加入 CI。 |
| 两个 substring helper 重复，旧函数也变成 size_t | 当前旧函数仍是 `substring_conf(char *, int, char)`；新 helper 才是 size_t。提取原函数与固定基线比较，逐字一致；repair-map 描述准确。 | 拒绝合并，保留 legacy 原契约与 hardened 宽度适配。 |
| header 丢弃后必须防御性重置 | 每个新头之前，已有合法头的 buffer 所有权先交给链表，然后同时清空 key/c；丢弃分支不 append；合法分支才填充。smart_string 在 c=NULL 的新分配时重置 len/a。未发现报告证明的残留消费。 | 不移动所有权或增加推测性清理。已有 unknown+continuation、重复必要头测试。 |
| legacy body_parts_limit 应改成 -1 | 限制推导与消费均由 hardened gate 控制，legacy 不执行该验证。 | 改哨兵不影响目标行为，不改。 |
| legacy isspace 应补 unsigned char 转换 | 该调用存在于固定 PHP 7.0 基线，本 PR 保留该 legacy 行为。 | 属本轮范围外的原有问题，不改。 |

`free_list_head` 的主张应以“旧状态如何产生 → 生命周期的哪一个窗口 → 哪个消费者可达 →
本次补丁怎样使它成为新增回归或仍属于本次漏洞必需修复 → 有界复现/测试”为准，
而不是以结构体是否每个字段都被清零为准。当前证据不足以证明报告中的严重缺陷。

## 测试建议中已覆盖与未覆盖的部分

已有覆盖：

* FPM 普通 fatal 后同 PID 复用；OOM 无 shutdown 标记、更换 PID；下一请求、Session 及
  upload progress 的状态检查。见 `testing/fpm-invariants.py`。
* singleton 的 mixed/sparse/packed 增长、COW、序列化、排序、删空再插；原生实际对齐断言。
* 重复 Content-Type 保留第一个值，以及真实文件名、类型和 `hello` 内容。
* `_estrndup` 和 `zend_strndup` 的 SIZE_MAX 入口及 hardened fail-stop。

真正值得补充且直接验证本次改动的两项：

1. [派生零限额](../../tests/basic/rfc1867_max_multipart_body_parts_derived_zero.phpt)：
   max_input_vars=0、max_file_uploads=0、max_multipart_body_parts=-1，首个 part 即拒绝。
   既有 explicit-zero 测试不覆盖派生函数这条输入组合。
2. [截断后数据保留](../../tests/basic/rfc1867_max_multipart_body_parts_retained_data.phpt)：
   前两个 part 成功接收普通字段和非空文件，第三个 part 超限；检查前两项元数据、
   is_uploaded_file() 与文件内容仍正确，超限字段/文件不进入全局数组。
   既有限额测试仅保留空文件记录，不覆盖实际文件与 `fileupload_done` 组合。

两个文件匹配现有 CI 的 `rfc1867_max_multipart_body_parts*.phpt` glob，无需改 CI 配置或增加 job。
32 位、dtoa 注入等仍是已知验证边界，按目标部署和本次漏洞因果决定优先级，
不把报告提议自动扩大成平台、完整状态重置或一般 PHP 维护项目。

## 本轮实际验证与改动范围

用此前从本分支安全运行时代码构建的 PHP 7.0.33 Debug，在纯 Ubuntu 22.04 arm64、
无网络 Docker 容器中运行两个新测试及邻近 multipart 回归：9/9 通过、0 失败、0 跳过。
本轮未改运行时代码，因此不为这两个测试重建解释器，也不把既有二进制结果说成新源码全量重建。
原始 PHPT 日志和 JUnit 在 `/tmp/php70-report-review/logs/`。

另用固定原始 PHP 7.0.33 基线运行两个新用例，二者均因预期行为差异失败：
派生零用例仍进入旧 input/file 限额诊断；数据保留用例的超限字段和文件仍被接受。
相同环境中的 hardened 结果通过，说明测试针对本次新增 part 限制而不是环境差异。
基线日志及 diff 在 `/tmp/php70-report-review/baseline-logs/`；这些失败不被定性为新的 PHP bug。

改动只有根目录范围说明、本文档和两条 PHPT；PHP 的 C 源码、legacy 行为、CI job 数均未改变。
上述复核和本地测试在提交前完成；后续文档归档、提交、推送及远程 CI 结果以 Git 历史和对应运行记录为准。
