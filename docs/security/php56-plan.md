# PHP 5.6.40 安全回移植实施计划

状态：首轮适配与范围内验证已完成，保留草稿待独立审查。实际结果见 php56-verification.md。工作目录为独立 managed worktree，分支
codex/php56-cve-2026-109618-109619。原 PHP 7.0 工作区不改动。

1. 根因与来源审计：见 php56-audit.md，基线 4b8f72da5dfb201af4e82dee960261d8657e414f。
2. 首版最小补丁：OOM fail-stop、指定状态清理后重置、禁止内置 Session 上传进度、
   multipart 放大缓解、ZE2 小输入表及 int 字符串长度适配。
3. 先开 PR，再推进：Debug/Release 干净构建，定向 PHPT，原核心/Session/上传 PHPT；
   干净基线与 hardened 全套状态比较；每个新增失败建立因果解释。
4. 原生 probe：真实 safe allocator 溢出、小输入 HashTable 的 mask/capacity/growth。
   仅验证检查边界，不伪造远程 RCE 证据。
5. FPM：单 worker/私有 Unix socket/无网络，确认普通与 fatal 请求后的同 PID 连续处理、
   early INI 诊断、正常 Session 和上传、PHP OOM fail-stop 后 master 更换 child。
6. 证据回填：构建/工具链/源码与二进制摘要、完整命令、原始日志与机器可读结果。
   把真实运行、注入、静态判断和未验证范围分开；据实际结果更新 PR。

## 兼容性与边界

- 内存失败终止 worker，不调用 PHP shutdown/destructors；普通 fatal 保留原生命周期。
- 内置 Session Upload Progress 无条件禁用，即使 INI=1；普通 Session/上传应保持。
- 新增 max_multipart_body_parts，默认 max_input_vars + 非负 max_file_uploads（饱和）。
  计数对象与官方补丁一致：有 Content-Disposition 的 part，包含空 filename。
- 只保留首个 Content-Disposition / Content-Type；重复头不再累积。
- 不改变公开结构体/API 编号；外部扩展中旧版内联系统 allocator 仍须匹配头文件重编。
- 使用原始官方基线作 legacy 比较，不引入生产回退开关。
- 未新增 decoded-body 字节上限，流式大 body 与 worker 重启仍有 DoS 边界。
- 不覆盖 PHP 5.6 EOL 后的其他漏洞。mod_php、Windows、ZTS、32 位及任意第三方
  callback/custom allocator 目前未验证，不能从 FPM 或静态审查推导通过。

## 首次验证障碍

干净官方基线在 arm64 GCC 12 的 Debug -O0 触发现有 signed multiply inline asm
约束错误。源码不顺带修复该 legacy 问题。两侧尝试 make CFLAGS_CLEAN 的一致 -O2
Debug 构建（configure CFLAGS 会被旧构建系统覆盖）；结果待后续记录。
