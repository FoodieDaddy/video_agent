# ADR 0009 — workspace 的源码、容器与 Windows 交付共用锁文件

- 状态：已采纳；替代 ADR 0008 中安装时重新解析应用依赖的决定。实际 Docker/Windows 运行验收须单独记录。
- 日期：2026 年 11 月 5 日。

## 背景

源码已按业务拆为 `apps/studio_api` 与 `packages/studio_*`。每个成员有独立包元数据，成员间依赖由 workspace 提供。如果继续只读取根 `pyproject.toml` 然后 `pip install studio-api`，安装器会尝试从公共索引获取本地应用，而遗漏仓库成员。旧的 `PYTHONPATH=backend` 也无法证明成员已正确安装。

## 决定

开发环境、Docker 和 Windows 安装都使用根目录唯一的 `uv.lock`，以固定版本 uv 0.12.9 引导。安装器先复制完整 workspace，再执行 `uv sync --frozen --no-dev --no-editable`。`--extras s3,pdf` 对应多个 uv `--extra` 参数；安装时不升级应用依赖或重新解析版本。

Windows 的 uv 引导临时放在 runtime venv 之外，同步成功或失败后清理，以免精确同步清除正在执行的 uv。桌面启动器使用已安装的 `studio_api.desktop`，显式指定资源根、配置和用户数据位置；启动前遇到端口占用会报错，不自动换端口另开实例。

载荷包含成员 `pyproject.toml`、`src`、根锁文件、`config`、`web` 与 `samples`；载荷校验会拒绝成员缺失。根 `backend/app` 旧入口链接不复制，兼容 `app` 包由 `studio-api` 成员正常安装。本地 `.env`、数据、虚拟环境和构建目录不进入载荷或镜像。

Docker 同样复制全部成员并执行冻结的非 editable 安装，启动 `studio_api.main:app`，保持一个 worker。CI 构建所有成员 wheel；容器启动后检查健康和元信息，并清理本次创建的容器。

## 影响与限制

安装需要网络获取 uv 引导、Python（如缺失）和锁定的第三方包；本方案未提供离线 wheelhouse。构建工具本身仍有独立依赖，不等同于应用 runtime 的锁定依赖。

macOS 上的载荷和命令合约检查不能替代 Linux Docker 镜像启动，也不能替代 Windows EXE 构建、安装和卸载验证。对应 CI job 未实际运行前，交付记录保持未验收说明。

## 重新评估时机

需要离线安装、签名安装器或企业镜像供应链时，再增加锁定工具链和第三方 wheelhouse，并在目标操作系统完成安装/升级/卸载演练。
