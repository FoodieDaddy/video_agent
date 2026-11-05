"""数据库连接与会话生命周期，API 和后台任务共用一个工厂。

每个后台任务创建自己的 Session，不与请求线程共享会话；任务用例仍可能在
模型等待期间持有事务，因此独立 Session 不能等同于短事务保证。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from studio_platform.configuration.settings import Settings, get_settings
from studio_platform.persistence.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(settings: Settings | None = None) -> Engine:
    """按配置替换全局 engine 和工厂；仅用于受控启动/测试，不是并发热切换。"""
    global _engine, _session_factory
    settings = settings or get_settings()
    url = settings.database_url

    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        # ``sqlite:///relative`` would resolve against CWD; make it absolute.
        if not url.startswith("sqlite:////") and ":///" in url:
            raw_path = url.split(":///", 1)[1]
            if raw_path and raw_path != ":memory:":
                path = Path(raw_path)
                if not path.is_absolute():
                    path = (settings.data_dir / path.name).resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                url = f"sqlite:///{path.as_posix()}"

    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, **kwargs)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def init_schema() -> None:
    """聚合注册映射并创建缺失表；不承担已有表结构升级或数据迁移。"""
    # 表映射由启动组合根显式注册；独立使用 platform 时只创建已提供的映射。
    Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """提供独占会话，正常退出提交、异常回滚，并始终关闭。

    内层代码显式提交的变更不会被后续回滚撤销。数据库异常继续传播；
    文件和外部模型副作用也不会因为数据库回滚自动撤销。
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def reset_engine() -> None:
    """测试辅助：释放全局连接与工厂，下次访问时按配置重新建立。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
