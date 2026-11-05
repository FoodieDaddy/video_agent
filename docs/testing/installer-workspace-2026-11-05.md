# 安装器 workspace 机制验收（2026-11-05）

- 代码版本：`1e6b5bce75bae74ffb84dfca0ddea2193ed9e0f3`；执行时工作区有未提交改动：`True`。
- 平台：macOS-26.2-arm64-arm-64bit，Python 3.12.13。
- 结果：**passed**，耗时 347.68 秒。

本次在自动清理的临时安装目录中复制完整 payload、创建带 pip 的标准 venv，实际调用 `installer.install.install_workspace(..., extras=[], dry_run=False)`。uv 引导固定为 0.12.9，随后使用载荷锁文件执行冻结、非 editable workspace 安装。安装后将源码目录移走，在独立工作目录执行安装器 `verify_packages()` 和全部成员导入检查；没有设置 PYTHONPATH，没有启动独立网页进程。

核验结果见 [结构化证据](installer-workspace-2026-11-05.json)：payload 有 13 个成员；安装发行包 13 个；uv 临时引导已清理：True；锁文件未改写：True；包内 config/web/samples 资源可用：True；临时安装目录已删除：True。

这证明当前 macOS 上共享安装机制的真实执行结果。未执行 Windows EXE、快捷方式、注册表、原生安装/卸载，也未执行 Docker；不作为这些交付路径的原生验收证据。
