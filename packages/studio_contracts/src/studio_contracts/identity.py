"""技术运行器只需要调用方提供资源标识，不依赖业务 ORM。"""

from typing import Protocol


class ProjectIdentity(Protocol):
    @property
    def id(self) -> str:
        """调用方已经验证可访问的项目标识。"""
        ...
