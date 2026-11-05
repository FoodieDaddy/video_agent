# Docker workspace 实际构建与隔离运行

- 源码基线：`1e6b5bc`。构建上下文采集时存在文档改动。
- 构建命令：`docker build -f deployment/docker/Dockerfile -t video-agent:workspace-20261105 .`。
- 平台：本机 Docker Desktop 中的 Linux arm64；不是 Windows 容器或原生 Windows 安装。
- 原始结果：[docker-workspace-2026-11-06.json](docker-workspace-2026-11-06.json)。

## 构建

完整 Dockerfile 构建成功，镜像 ID 为 `sha256:25ef58b7b57ccc3cdb7c0f8318860fbece0f840277274eac47a1d11326006a6c`。
使用固定 uv 0.12.9、唯一锁文件，实际完成 13 个 workspace 成员的冻结、非 editable 安装。
系统依赖下载曾多次网络重试，原构建最终退出码为 0；没有通过替换 mock 系统依赖绕过 FFmpeg 安装。

## 容器内运行

临时容器使用 `--network none`，不挂载主机目录、不绑定主机端口。
数据、数据库和存储全部指向容器内临时目录，所有模型强制 mock。
通过真实 FastAPI TestClient 执行应用 lifespan 和 HTTP 请求，结果：

- 健康检查、控制台、JS、CSS 和元信息接口均返回 200。
- 39 张 ORM 表、17 个 Agent、13 个成员发行包装配正确。
- 从样例小说开始，经过人物/场景、分镜、镜头、终审四关。
- 工作流完成，实际 FFmpeg 渲染并导出 70,049 字节成片，可由媒体接口读取。
- 镜像的默认命令为 `uvicorn studio_api.main:app --host 0.0.0.0 --port 8000 --workers 1`。

该验证执行了容器内应用和媒体流程，但没有启动第二个常驻 Uvicorn 服务，
也没有验证对外 TCP 端口、反向代理或镜像默认 HEALTHCHECK 的定时执行。

## 清理与剩余范围

临时运行容器和诊断容器均已删除；本次启动的 Docker Desktop 已关闭，原项目单实例未重启。
构建镜像保留为可审查产物。Windows EXE 构建、安装、快捷方式、启动与卸载仍需可用 Windows 环境完成；
当前两个配置入口的 SSH 连接均被关闭，不能以本次 Linux 容器验证代替。
