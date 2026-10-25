# PHP 7.0 安全 CI

本分支 push 自动运行一次；同提交的 PR 展示这些检查，不另触发重复流水线。
所有 PHP 测试均编译当前提交的 PHP 7.0.33，不使用系统 PHP。

- 独立 PHPT：Debian 12 工具链，Bison 3.5.1（SHA256 校验）、autoconf 2.69；Debug / Release。
  `phpt.sh` 先运行 14 条安全测试，再运行 Zend/session/basic 的集成选择。
  安全测试必须完整通过，不能 skip；集成的 8 条正向 progress 旧测试列于
  `progress-compatibility.txt`，它们依赖本修复刻意禁用的功能。
  替代安全断言 `rfc1867_upload_progress_disabled.phpt` 仍必须通过。
  排除清单、完整选择、JUnit、退出码、计数和 diff 都保存，未掩盖为原始目录全绿。
- 平台门禁：`platform/` 保留原已验证的 native / FPM / PHPT / cgroup 工具；
  Debian 12、CentOS 7、CentOS 8、CentOS Stream 9、UBI 9 都跑 amd64 Debug/Release，
  另有 Debian arm64 Debug 与 amd64 ASan。容器共享宿主 Linux 内核，发行版覆盖验证用户空间。
- 外部 E2E：固定 `fangfengxiang/php-cve-e2e` 提交
  `7ce13d03c0fcba68e8f6db8a5017d845ad812747`，behavior 三构建加 instrumented 两构建；
  源码与 harness 同级检出，保持源码工作树干净。两种运行和报告 `pass` 均为必要条件。
- 报告：上传 reporter 生成的自包含报告与有限证据，不上传完整源码或安装树。
  PHPT、平台、E2E 全部通过后才部署 Pages。报告生成成功本身不表示安全验证成功。

本地复现 PHPT（从仓库根目录执行；输出目录必须是新的）：

```sh
mkdir -p /tmp/php70-ci/input /tmp/php70-ci/output/logs
git archive HEAD > /tmp/php70-ci/input/source.tar
docker build -t php70-phpt .github/php70
docker run --rm --network none --mount type=volume,dst=/work/source \
  -v /tmp/php70-ci/input:/input:ro \
  -v "$PWD/.github/php70:/harness:ro" \
  -v /tmp/php70-ci/output:/work \
  -e BUILD_JOBS=4 --entrypoint sh php70-phpt /harness/phpt.sh debug
```

失败时先看 artifact 的构建日志、阶段 summary JSON、JUnit 和 diagnostics。
预期 WARN/XFAIL、SKIP 均保留原始记录；不因为历史缺陷而修改 PHP 源码。
此门禁不是 PHP 全量基线比较或完整漏洞修复证明。
