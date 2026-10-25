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

## 干净的完整基线比较

最终比较使用相同镜像和容器内部文件系统，避免 macOS bind mount 的权限语义造成假差异。
`run-clean-comparison.sh` 在同一容器完成构建、probe、FPM、安全 PHPT 和完整 PHPT，
将生成配置、失败 diff 和日志写回宿主机。源目录是临时 Docker 卷，退出后自动回收。
沿用上面的镜像和两个源码归档：

```sh
for build_mode in baseline debug; do
    source_archive="$validation_root/source.tar"
    if test "$build_mode" = baseline; then source_archive="$validation_root/baseline.tar"; fi
    mkdir -p "$validation_root/clean-$build_mode"
    if docker run --rm --network none --mount type=volume,dst=/work/source \
        -v "$source_archive:/input/source.tar:ro" \
        -v "$PWD/docs/security/testing:/harness:ro" \
        -v "$validation_root/clean-$build_mode:/work" \
        --entrypoint sh php70-security-toolchain /harness/run-clean-comparison.sh "$build_mode"; then
        result=0
    else
        result=$?
    fi
    echo "$build_mode actual exit code: $result"
done

python3 docs/security/testing/summarize-results.py --artifacts "$validation_root" \
    --baseline-folder clean-baseline --hardened-folder clean-debug \
    --output "$validation_root/comparison.json"
```

完整运行有已记录失败，退出 1 必须保留为失败，不能把构建成功当成测试通过。
汇总工具拒绝未完成的主要 PHPT 日志；未运行的可选构建以 `not_executed` 标示。
汇总中的兼容变化分类仅供定位，每个新增失败仍须逐项检查 diff，不能仅凭文件名前缀判为预期。
初次主机挂载结果仅作历史记录，不与不同文件系统的运行混作补丁收益。

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
只跑当前 14 条安全 PHPT 时传入以下路径（工作目录 `/work/source`，需先 `cd` 才展开 glob）：

```sh
sh /harness/run-phpt.sh Zend/tests/cve_2026_109618_*.phpt \
    ext/session/tests/rfc1867_upload_progress_disabled.phpt \
    tests/basic/rfc1867_duplicate_headers.phpt \
    tests/basic/rfc1867_empty_file_nested_name.phpt \
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

## 小内存 Docker OOM

在宿主机运行以下 Python 工具，传入已经编译好的 **hardened** Linux PHP 7.0 安装目录。
它依次创建 64、96、128 MiB、无 swap、无网络的运行期容器；不会给编译任务施加这些小限额。
输出目录必须尚不存在，以免覆盖先前证据。以两个构建分别执行：

```sh
for build_mode in debug release; do
    python3 docs/security/testing/docker-memory-invariants.py \
        --image php70-security-toolchain:latest \
        --install "$validation_root/$build_mode/install" \
        --output "$validation_root/docker-memory-$build_mode"
done
```

`--memory-mib 64 96 128` 可显式指定限额。每个 FPM 容器有一个 static worker，使用私有 Unix socket。
PHP `memory_limit=16M` 检查 Zend fail-stop 的 exit 1；`memory_limit=-1` 才用实际分块分配触发
cgroup 内核 OOM。额外的 64 MiB CLI 容器检查 PHP 作为 PID 1 时被内核杀死的 exit 137。
内层 [fpm-memory-pressure.py](fpm-memory-pressure.py) 读取 cgroup v2 的实际内存/swap 限额、
计数和峰值，同时检查原 child 的退出原因、master 存活、替换 worker 和 Session 连续可用。
每次分配 1 MiB、保留最多 512 MiB；没有 RCE 负载。

Docker 启动参数的关键部分为 `--memory 64m --memory-swap 64m --network none`。
`--memory-swap` 是内存加 swap 的总额，相等表示禁用 swap；必须同时看到容器里的
`memory.max=67108864`、`memory.swap.max=0` 才算生效。工具要求 cgroup v2，不把缺失指标当作通过。
FPM child 被杀时 Docker 也可能报告 `OOMKilled=true`、容器却正常退出 0，故不能只看该字段。

`summary.json` 记录计划/完成组数；全部计划完成并通过才令汇总 `pass=true`。另保存每轮
JSON、FPM 原始日志和容器日志；退出/超时清理只针对工具自己创建的唯一名称容器。
记录 Docker inspect 后才删除容器。先前完整 FPM 上传测试会在 Python 中复制较大请求体，
应与本专用小内存测试分开运行。这里证明受测 cgroup 与进程生命周期行为，不能替代安全 PHPT、
完整回归或 ASan。

probe 是测试扩展，**不得安装到生产实例**。`build-probe.sh` 将它放在容器输出目录，
不会修改宿主机 PHP 安装。旧扩展可加载与旧内联 guard 仍 bailout 的实证保存在
`../results/old-extension-compatibility.json`。

## 分支自动 CI

新增矩阵、触发条件和 Grok 边界建议评估见 [CI 与边界测试评估](../ci-and-boundary-review.md)。

当前配置共 14 个 job；新增 9 系覆盖用于验证目标部署的 RPM/glibc/GCC 环境，不扩展漏洞修复范围：

| Linux 用户态 | 架构与构建 | cgroup 7 组检查 |
| --- | --- | --- |
| Debian 12 | amd64 Debug/Release/ASan/legacy；arm64 Debug/Release | amd64 Debug 和 Release |
| Ubuntu 22.04、24.04 | amd64 Debug/Release | 不重复执行 |
| CentOS Stream 9 (`quay.io/centos/centos:stream9`) | amd64 Debug/Release | 两个构建均执行 |
| Red Hat UBI 9 (`registry.access.redhat.com/ubi9/ubi:latest`) | amd64 Debug/Release | 两个构建均执行 |

UBI 镜像名固定在 9 系，`latest` 仅在该系内更新；不需要 Red Hat 订阅凭据。
每次运行保留实际镜像 ID、`/etc/os-release`、包版本和源码提交，结果须绑定具体运行。
容器共享 GitHub runner 的 Linux 内核：此矩阵验证发行版用户态，不等于验证 CentOS/RHEL 宿主机内核。
CentOS/RHEL 7、8，ZTS、Windows 和 mod_php 未因此获得覆盖。

同一 Dockerfile 按 apt/dnf 安装编译依赖；RPM 使用 Autoconf 2.69、校验源码摘要的 re2c 3.0，
所有镜像使用校验摘要的 Bison 3.5.1。镜像不安装发行版 PHP；解释器仍从本分支构建为 PHP 7.0.33。
FPM 测试读取 `nobody` 的实际主组，兼容 Debian 的 `nogroup` 和 RPM 的 `nobody`。
需要本地复现时，将上述 `docker build` 加上 `--build-arg BASE_IMAGE=quay.io/centos/centos:stream9`
或 `--build-arg BASE_IMAGE=registry.access.redhat.com/ubi9/ubi:latest`，并为各镜像使用独立输出目录。

2026-10-25 准备验证：本地原生 arm64 的 CentOS Stream 9、UBI 9 各自全新构建 PHP 7.0.33 Debug，
各通过 14 项 native、11 项 FPM、14 条 PHPT 和 7 组 cgroup；Debian 的既有 Release 构建另通过 7 组 cgroup。
这些本地结果不能代替新增 amd64 Debug/Release job 的远程运行记录。

上述安全 PHPT 命令与 `ci.sh`、clean comparison 的专项阶段一致，当前共 14 条。
默认 Zend MM 的 FPM 检查为 11 项；hardened OOM 要求旧 worker 明确 exit 1，
不能仅凭 PID 更换判定成功。测试会拒绝 ASan 报错及 worker 崩溃信号。
native probe 现有 14 项，包括 `zend_safe_addmult()` 的加法溢出入口；历史记录中的 13 项不含此新增用例。
已完成的 [5c9173b CI](https://github.com/fangfengxiang/php-src/actions/runs/40058565734)
在原生 amd64/arm64 的 10 个 job 通过，包含 14 条安全 PHPT、13 项 native 和 11 项默认 Zend MM FPM。
该次运行不包含后来增强的 OOM 退出原因断言与新增 native 用例，不能作为这些新断言的运行证据。

2026-10-25 本地补充验证复用既有 PHP 7.0.33 安装前缀，核对其构建目录的 20 个运行时/构建源码
与当前分支一致，仅重编测试扩展。Debug、Release、ASan、legacy 各通过 14 项 native、11 项 FPM；
ASan 系统 allocator 另有 8 项通过、1 项预期跳过。临时脚本将 OOM 请求替换为 worker SIGSEGV，
新断言按预期拒绝该负面对照。未重编 PHP 运行时、未重跑全量 PHPT，也未据此新增生产适用性声明。
