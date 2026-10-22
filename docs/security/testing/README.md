# 隔离构建与复现

在已提交的本分支工作目录执行。需要 Docker，宿主机不需要安装 PHP 7.0。
镜像构建下载工具链，PHP 7.0 构建和测试容器使用 `--network none`。

```sh
validation_root=/tmp/php70-backport-repro
mkdir -p "$validation_root"
git archive HEAD > "$validation_root/source.tar"
git archive bf574c2b67a1f786e36cf679f41b758b973a82c4 > "$validation_root/baseline.tar"
docker build -t php70-security-toolchain docs/security/testing

for build_mode in debug release asan legacy baseline; do
    mkdir -p "$validation_root/$build_mode"
    source_archive="$validation_root/source.tar"
    if test "$build_mode" = baseline; then source_archive="$validation_root/baseline.tar"; fi
    docker run --rm --network none \
        -v "$source_archive:/input/source.tar:ro" \
        -v "$PWD/docs/security/testing:/harness:ro" \
        -v "$validation_root/$build_mode:/work" \
        --entrypoint sh php70-security-toolchain /harness/build.sh "$build_mode"
done
```

使用 `git archive` 避免 macOS tar 的 AppleDouble `._*.phpt` 被旧测试工具误认为测试。
每个模式使用独立输出目录。`build.sh` 明确清理对象文件；改变安全模式或 inline header 后必须
clean，不能仅增量链接旧对象。首次无效的 AppleDouble 测试及旧对象链接失败没有纳入最终结果。

## 硬化构建验证

下面以 Debug 为例；将工作目录替换为 release/asan 后重复。ASan 使用 GCC/libasan，
`detect_leaks=0` 明确不做泄漏检测。FPM 只启动临时 Unix socket，脚本退出时回收 master/child。

```sh
docker run --rm --network none \
    -e ASAN_OPTIONS=detect_leaks=0:abort_on_error=1:allocator_may_return_null=1 \
    -v "$PWD/docs/security/testing:/harness:ro" \
    -v "$validation_root/debug:/work" \
    --entrypoint sh php70-security-toolchain -ec '
        sh /harness/build-probe.sh
        python3 /harness/native-invariants.py --php /work/install/bin/php \
            --module /work/probe/modules/security_probe.so --output /work/logs/native-invariants.json
        python3 /harness/fpm-invariants.py --fpm /work/install/sbin/php-fpm \
            --output /work/logs/fpm-invariants.json
        sh /harness/run-phpt.sh
    '
```

完整 PHPT 保留原始期望，会因已记录的环境失败与必要兼容变化退出 1，不能称作全绿。
原始日志在 `/work/logs/phpt.log`，失败列表与 JUnit 同目录；不要只读取退出码。
只跑 11 个新增测试时传入以下路径（工作目录 `/work/source`，需先 `cd` 才展开 glob）：

```sh
sh /harness/run-phpt.sh Zend/tests/cve_2026_109618_*.phpt \
    ext/session/tests/rfc1867_upload_progress_disabled.phpt \
    tests/basic/rfc1867_duplicate_headers.phpt \
    tests/basic/rfc1867_max_multipart_body_parts*.phpt
```

每次运行覆盖相同 PHPT 日志；分开保存 full/security/system-allocator 的日志，避免互相覆盖。
本次结果已经分别保存，见 `../verification.md` 与 `../results/`。

ASan 直接系统 allocator：对 asan 输出目录传入 `-e USE_ZEND_ALLOC=0`、
`-e RUNNER_VARIABLES_ORDER=EGPCS`，FPM 脚本另加 `--system-allocator`。
`run-phpt.sh` 生成临时 `run-tests-system-allocator.php`，仅修正旧 runner 两处强制把 allocator
改回 1 的语句，不修改仓库原 runner、不修改测试断言。memory_limit OOM PHPT 此时跳过是预期的；
必须同时运行默认 Zend MM 构建中的该测试，不能用跳过替代验证。

legacy 比较构建对 native 脚本传 `--legacy`，FPM 传 `--expect-baseline`。
它刻意保留不安全行为，只可用于隔离比较。基线只运行原始 PHPT/FPM 对照，不运行要求 hardened
API 的新 native 脚本。对照结果汇总工具为 `summarize-results.py`。

probe 是测试扩展，**不得安装到生产实例**。`build-probe.sh` 将它放在容器输出目录，
不会修改宿主机 PHP 安装。旧扩展可加载与旧内联 guard 仍 bailout 的实证保存在
`../results/old-extension-compatibility.json`。
