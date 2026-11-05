"""源码与安装包的资源锚点，不随测试中的 settings.REPO_ROOT 覆盖而变化。"""

from pathlib import Path

# 当前仍沿用 backend/app 布局；与原 services/documents.py 的 parents[3] 等价。
# workspace 打包阶段由启动组装显式传入资源路径，再统一替换此兼容锚点。
PROJECT_ROOT = Path(__file__).resolve().parents[4]
