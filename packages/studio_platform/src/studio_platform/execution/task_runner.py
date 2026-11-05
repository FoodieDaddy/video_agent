"""进程内任务运行器；只接收处理函数，不解释工作流或业务阶段。

保留当前线程、取消、等待与提交行为；并发策略的功能修复单独验收。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from sqlalchemy.orm import Session

from studio_contracts.public import json_safe
from studio_platform.constants import TaskStatus
from studio_platform.execution.runtime import AppRuntime
from studio_platform.ids import utcnow
from studio_platform.persistence.models import Task
from studio_platform.persistence.session import session_scope
from studio_platform.persistence.task_records import emit

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Session, AppRuntime, Task], Awaitable[dict[str, Any] | None]]


class TaskRunner:
    """进程内线程运行器，每个执行任务独占 Session 和事件循环。

    inline=True 为每次提交创建 daemon 线程，并不是调用线程同步执行；
    inline=False 才使用 max_workers 限制的线程池。两种模式都不是外部 worker。
    """

    def __init__(self, *, max_workers: int = 4, inline: bool = True) -> None:
        self.inline = inline
        self.max_workers = max(1, int(max_workers))
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="task")
        self._cancelled: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}
        self._done: dict[str, threading.Event] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()

    # -- submission
    def submit(self, task_id: str, handler: TaskHandler, runtime: AppRuntime) -> None:
        """异步提交已存在的任务；不执行可靠领取，也不保证重复 task_id 去重。"""
        done = threading.Event()
        with self._lock:
            self._done[task_id] = done
        if self.inline:
            thread = threading.Thread(
                target=self._worker,
                args=(task_id, handler, runtime, done),
                name=f"task-{task_id[-6:]}",
                daemon=True,
            )
            with self._lock:
                self._threads[task_id] = thread
            thread.start()
        else:
            future = self._executor.submit(self._worker, task_id, handler, runtime, done)
            with self._lock:
                self._futures[task_id] = future

    def wait(self, task_id: str, timeout: float | None = 60.0) -> bool:
        """等待本进程完成信号；未知任务或超时返回 False，True 不代表业务成功。"""
        with self._lock:
            done = self._done.get(task_id)
        return bool(done and done.wait(timeout))

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled

    def cancel(self, task_id: str) -> bool:
        """标记本进程尚未完成的任务；不强制中断已发出的模型请求或 FFmpeg。"""
        with self._lock:
            if task_id in self._done and not self._done[task_id].is_set():
                self._cancelled.add(task_id)
                return True
        return False

    def shutdown(self) -> None:
        """停止线程池排队任务；当前不等待执行完成，也不统一回收 inline 线程。"""
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- worker
    def _worker(
        self,
        task_id: str,
        handler: TaskHandler,
        runtime: AppRuntime,
        done: threading.Event,
    ) -> None:
        try:
            with session_scope() as db:
                task = db.get(Task, task_id)
                if task is None:  # pragma: no cover - defensive
                    return
                if self.is_cancelled(task_id):
                    task.status = TaskStatus.CANCELLED.value
                    task.finished_at = utcnow()
                    db.flush()
                    return
                task.status = TaskStatus.RUNNING.value
                task.started_at = utcnow()
                task.attempts = int(task.attempts or 0) + 1
                task.error = ""
                task.config_versions = dict(runtime.config_store.config_versions())
                emit(db, task, "started", f"任务开始：{task.type}", progress=0.0)
                db.commit()

                try:
                    result = asyncio.run(handler(db, runtime, task))
                except Exception as exc:
                    db.rollback()
                    task = db.get(Task, task_id)
                    if task is None:  # pragma: no cover
                        return
                    task.status = TaskStatus.FAILED.value
                    task.error = f"{type(exc).__name__}: {exc}"[:4000]
                    task.finished_at = utcnow()
                    task.message = "任务失败"
                    emit(
                        db,
                        task,
                        "failed",
                        task.error,
                        level="error",
                        data={"type": type(exc).__name__},
                    )
                    db.commit()
                    logger.warning("task %s failed: %s", task_id, exc)
                    return

                task = db.get(Task, task_id)
                if task is None:  # pragma: no cover
                    return
                if self.is_cancelled(task_id):
                    task.status = TaskStatus.CANCELLED.value
                    task.message = "任务已取消"
                else:
                    task.status = TaskStatus.SUCCEEDED.value
                    task.progress = 1.0
                    task.message = task.message or "任务完成"
                    task.result = json_safe(result or {})
                task.finished_at = utcnow()
                emit(
                    db,
                    task,
                    "completed" if task.status == TaskStatus.SUCCEEDED.value else "cancelled",
                    task.message,
                    progress=task.progress,
                )
                db.commit()
        except Exception:  # pragma: no cover - session/commit failures
            logger.exception("task runner crashed for %s", task_id)
        finally:
            with self._lock:
                self._cancelled.discard(task_id)
                self._threads.pop(task_id, None)
                self._futures.pop(task_id, None)
            done.set()


_runner_lock = threading.RLock()


def get_runner(runtime: AppRuntime) -> TaskRunner:
    """为每个 Runtime 惰性创建一个运行器，保持测试执行状态隔离。"""
    if runtime.task_runner is not None:
        return runtime.task_runner
    with _runner_lock:
        if runtime.task_runner is None:
            runtime.task_runner = TaskRunner(
                max_workers=runtime.settings.max_workers, inline=runtime.settings.inline_tasks
            )
            runtime.extras["is_cancelled"] = runtime.task_runner.is_cancelled
        return runtime.task_runner


def reset_runner(runtime: AppRuntime | None = None) -> None:
    if runtime is not None and runtime.task_runner is not None:
        runtime.task_runner.shutdown()
        runtime.task_runner = None
        runtime.extras.pop("is_cancelled", None)
