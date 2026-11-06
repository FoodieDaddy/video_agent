# 分平台发布归档

`scripts/build_releases.py` 为 Windows、macOS、Linux 分别生成归档，不把三个系统的启动方式混成一个入口。应用仍是一套 workspace 和一个 `uv.lock`；平台差异集中在安装器、启动脚本与发布说明。

## 来源与前置条件

默认发布来源是 **当前 Git HEAD 的干净快照**。未提交的代码、配置、前端改动和未跟踪文件均不进入归档。安装器、发布构建器等本批新增文件必须先提交，否则缺失入口会明确报错。

CI 已检出源码或本机已经准备隔离源码目录时，可以使用 `--source-root PATH`；该模式按目录当前内容构建，来源责任由调用方承担，清单中不会伪造 Git 提交号。

macOS/Linux 发布包是源代码安装引导包，前置条件是 Python 3.11 或更新版本、`ffmpeg`、`ffprobe`，以及获取固定 uv 和锁定依赖的网络。它不是已经捆绑 Python/FFmpeg 的独立二进制应用，也不是 macOS 通用二进制。

## macOS 与 Linux

```bash
uv run --frozen --extra dev python scripts/build_releases.py --platform macos
uv run --frozen --extra dev python scripts/build_releases.py --platform linux
```

默认输出位于 `dist/releases/`：

- `ai-film-studio-<版本>-macos-source-bootstrap.tar.gz`：包含 `Install.command`、`install.sh` 和 `uninstall.sh`。
- `ai-film-studio-<版本>-linux-source-bootstrap.tar.gz`：包含 `install.sh` 和 `uninstall.sh`。

解压后运行 `./install.sh --dir "/绝对路径/含空格也可以"`。macOS 也可以从 Finder 启动 `Install.command`；此入口使用原生终端执行同一安装命令。`STUDIO_PYTHON` 可以显式指定 Python 解释器，脚本会核对版本，不会把旧版系统 Python 当成兼容解释器。

卸载命令为 `./uninstall.sh --dir "/安装目录"`，默认保留数据和配置；只有明确追加 `--purge` 才请求清除安装器管理范围内的数据。实际目录和安全约束以 POSIX 安装器的帮助及安装清单为准。

## Windows

Windows 原生 EXE 继续使用已有构建入口。在 Windows 构建环境中先生成两份 EXE，再组装发布归档：

```powershell
uv run --frozen --extra dev python scripts/build_installers.py
uv run --frozen --extra dev python scripts/build_releases.py --platform windows --windows-exe-dir dist
```

Windows 构建流程在两份 EXE 自检通过后生成 `dist/windows-installers.json`，绑定版本、来源提交、锁文件、必要安装器源码与两份 EXE 的 SHA-256，以及 PE 架构。构建开始与结束的必要源码指纹不一致时会拒绝生成清单，失败构建也会清除上一轮旧清单。

原生构建开始时要求必要安装源码、构建脚本、根项目清单和锁文件与 HEAD 字节一致，避免给未提交安装代码伪绑定提交号。文档和前端工作区改动可以保留；默认内嵌 payload 也来自 HEAD 快照，不会把这些改动编入 EXE。需要由调用方提供独立载荷时须显式传 `build_installers.py --source-root PATH`，清单将其标为 `explicit-source-tree`。编译用安装代码仍要求匹配 HEAD。

清单同时记录实际内嵌 payload 的完整文件哈希与聚合哈希。归档时会重新从发布来源生成载荷并逐项核对，内嵌前端、提示词或应用代码与外部发布 payload 不一致也会拒绝。构建和发布阶段均只同步载荷副本中的资源。
两份 EXE 自检后还会复算实际 staging 目录的完整指纹；编译期间载荷被修改时不会生成来源清单。

归档构建器要求 `--windows-exe-dir` 同时包含两份 EXE 和该清单，核对 MZ/PE、架构、EXE 哈希、安装器源码及锁文件。默认 Git 快照还要求来源提交完全相同；显式 `--source-root` 至少核对版本、源码和锁文件。旧 EXE 与新 workspace 载荷不能只因同名就混装。通过后生成 `windows-native-bootstrap.zip`，清单也随包保留，安装入口为 `install.cmd`。

这些来源与结构检查不等于目标机器的原生安装和卸载验收；平台运行证据应另附记录。

跨平台机器上只需归档 Windows 源码时，必须显式使用 `--source-only`：

```bash
uv run --frozen --extra dev python scripts/build_releases.py --platform windows --source-only
```

其输出名和清单均标注 `source-bootstrap`，入口本身要求 Python 3.11 或更新版本，不包含 EXE。`--platform all` 在未提供 Windows EXE 且未指定 `--source-only` 时会失败，避免把缺少 Windows 原生产物的批次报告为完整原生发布。

## 归档与清单

每个平台归档包含一个独立顶层目录，其中有 `payload/`、`installer/`、平台启动脚本和 `release.json`。载荷包含全部 13 个 workspace 成员、锁文件、配置、前端、样例及同步后的随包资源；本地 `.env`、数据库、虚拟环境、构建目录和旧 backend 链接均被排除。

`release.json` 记录目标平台、归档类型、版本、架构策略、源码来源、固定 uv 版本、锁文件 SHA-256、完整成员列表和逐文件 SHA-256。内容哈希覆盖所有普通文件，唯独不包含清单自身，避免自引用。

构建在临时目录中同步资源，不回写原仓库。归档文件按路径排序并使用固定时间元数据；相同来源和构建参数得到相同归档内容。可见源码链接和不安全归档路径会被拒绝。安装器及运行时是否在各目标系统实测通过，须与“发布归档已生成”分别记录。
