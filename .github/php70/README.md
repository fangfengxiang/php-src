# PHP 7.0 的 PHPT 与 CI

PHP 源码、PHPT、run-tests.php、测试选择和结果门禁都在本仓库维护。
历史修复 `d4dee4a6144` 同时修改源码并增加 `Zend/tests/bug75573.phpt`；
`.travis.yml`、AppVeyor 和 `Makefile.global` 均调用本仓库 runner，本工作流沿用这个模式。

Docker 工具链、构建、native probe、FPM、cgroup、behavior/trace 属于
[php-cve-e2e](https://github.com/fangfengxiang/php-cve-e2e/blob/31fe485c059420aa3403e0f31ce8f4f7b2f9e95c/php70/CI.md)。
本仓库不保存这些工具的副本；CI 固定外部 SHA，source/harness 同级检出。
所有测试使用指定提交编译的 PHP 7.0.33，不使用宿主 PHP。

## 本仓库入口

- `run-phpt-stages.sh`：调用外部构建入口后，以本仓库 runner 先执行 14 条严格安全 PHPT，
  再执行 Zend/session/basic 的集成选择；Debug、Release 各一组。
- `progress-compatibility.txt`：明确列出 8 条依赖已关闭 progress 功能的旧用例。
  替代安全用例 `rfc1867_upload_progress_disabled.phpt` 不能排除或 skip。
  不把选择后的结果描述成原始目录全绿。
- `check-phpt.py`、`test-check-phpt.py`：检查完整计数、失败及安全用例 skip，保留负向控制。
- `run-source-checks.sh`：平台构建后比较 VM 生成头，再执行严格安全 PHPT；
  ASan 额外在系统分配器下执行两条输入 PHPT。`run-phpt.sh` 仅对临时 runner 适配环境变量，
  不改变原 runner 和用例。

## 工作流

当前分支 push 自动跑一轮，PR 展示相同提交的检查；保留手动入口。
Debian 12、CentOS 7/8/Stream 9、UBI 9 跑 amd64 Debug/Release，另有 Debian arm64 Debug 和 amd64 ASan。
上述五种发行版 amd64 Debug/Release 的 cgroup 检查均实际执行。容器验证用户空间/工具链，共享宿主内核。
外部三构建与两构建 trace 集中在 Debian，不在每个发行版重复五次构建。

证据包含 source SHA、harness SHA、镜像信息、构建日志、测试清单、JUnit、退出码和失败 diff。
取消、超时、缺失结果或安全用例 skip 都不得通过。报告生成成功不是测试通过。
全部门禁成功后才发布 Pages；上传有限原始证据，不上传完整源码、安装树或归档。
PHPT/平台 artifact 与外部 HTML 报告分别保存，目前 HTML 不合并平台矩阵。

## 本地复现 PHPT

从本仓库根目录执行，外部仓库先检出工作流固定的 SHA，输出目录必须是新的：

```sh
PHP70_HARNESS=../php-cve-e2e
mkdir -p /tmp/php70-ci/input /tmp/php70-ci/output/logs
git archive HEAD > /tmp/php70-ci/input/source.tar
docker build -t php70-toolchain "$PHP70_HARNESS/php70/harness"
docker run --rm --network none --mount type=volume,dst=/work/source \
  -v /tmp/php70-ci/input:/input:ro \
  -v "$(cd "$PHP70_HARNESS/php70/harness" && pwd):/harness:ro" \
  -v "$PWD/.github/php70:/source-ci:ro" \
  -v /tmp/php70-ci/output:/work \
  -e BUILD_JOBS=4 --entrypoint sh php70-toolchain /source-ci/run-phpt-stages.sh debug
```

失败先查对应 artifact 的构建日志、summary JSON、JUnit 和 diagnostics。
旧 WARN/XFAIL/SKIP 记录保留；门禁不是 PHP 全量比较或完整漏洞修复证明。
