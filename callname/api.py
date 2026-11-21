"""pywebview 的 js_api 桥。

约束：所有方法都是普通 def（独立线程执行并 json.dumps 返回值），
返回前 model_dump(mode="json")。窗口句柄用下划线属性，避免被暴露给 JS。
"""

from collections.abc import Callable
from pathlib import Path
import subprocess

import webview
from loguru import logger
from pydantic import ValidationError

from callname.db import Database, DbError
from callname.draw import DrawSession
from callname.schemas import (
    ApiResponse,
    DeleteOneResult,
    FilePickResult,
    ImportMode,
    LaunchResult,
    PersonPatch,
    fail,
    ok,
)


def _import_mode(raw: str) -> ImportMode:
    """把桥上传来的字符串转成枚举；非法值交给 DbError 统一兜底。"""
    try:
        return ImportMode(raw)
    except ValueError as exc:
        raise DbError("BAD_MODE", "导入模式只能是 merge 或 replace") from exc


def _dump[T](response: ApiResponse[T]) -> dict[str, object]:
    """桥接返回值必须是 JSON 可序列化结构。"""
    return response.model_dump(mode="json")


class MainApi:
    """主窗口（抽签）。"""

    def __init__(self, *, session: DrawSession, db: Database) -> None:
        self._session = session
        self._db = db
        self._window: webview.Window | None = None
        self._manager: subprocess.Popen[bytes] | None = None

    def attach(self, window: webview.Window) -> None:
        """由 app.py 注入窗口句柄；下划线属性不会被 pywebview 暴露。"""
        self._window = window

    def status(self) -> dict[str, object]:
        try:
            return _dump(ok(self._session.status()))
        except Exception as exc:  # pragma: no cover - 兜底，真正的 bug 才走到这里
            logger.exception("status failed")
            return _dump(fail("INTERNAL", f"读取状态失败：{exc}"))

    def draw(self) -> dict[str, object]:
        try:
            return _dump(self._session.draw())
        except Exception as exc:  # pragma: no cover
            logger.exception("draw failed")
            return _dump(fail("INTERNAL", f"抽签失败：{exc}"))

    def reset(self) -> dict[str, object]:
        try:
            return _dump(ok(self._session.reset()))
        except Exception as exc:  # pragma: no cover
            logger.exception("reset failed")
            return _dump(fail("INTERNAL", f"重置失败：{exc}"))

    def open_manage(self) -> dict[str, object]:
        try:
            proc = self._manager
            if proc is not None and proc.poll() is None:
                return _dump(ok(LaunchResult(launched=True, already_running=True)))
            from callname.app import spawn_manager

            self._manager = spawn_manager(self._db.path)
            return _dump(ok(LaunchResult(launched=True, already_running=False)))
        except Exception as exc:  # pragma: no cover
            logger.exception("open_manage failed")
            return _dump(fail("MANAGER_FAILED", f"无法打开名单管理：{exc}"))


class ManageApi:
    """名单管理窗口。"""

    def __init__(self, *, db: Database) -> None:
        self._db = db
        self._window: webview.Window | None = None

    def attach(self, window: webview.Window) -> None:
        self._window = window

    # -- 查询 -------------------------------------------------------------
    def list_people(self, query: str = "") -> dict[str, object]:
        try:
            return _dump(ok(self._db.list_people(query)))
        except Exception as exc:  # pragma: no cover
            logger.exception("list_people failed")
            return _dump(fail("INTERNAL", f"读取名单失败：{exc}"))

    def stats(self) -> dict[str, object]:
        try:
            return _dump(ok(self._db.stats()))
        except Exception as exc:  # pragma: no cover
            logger.exception("stats failed")
            return _dump(fail("INTERNAL", f"读取统计失败：{exc}"))

    # -- 增删改 -----------------------------------------------------------
    def add_person(self, name: str, weight: int = 1) -> dict[str, object]:
        return self._call("add_person", lambda: self._db.add_person(name, weight))

    def update_person(self, pid: int, patch: dict[str, object]) -> dict[str, object]:
        # 校验放进 lambda：否则 ValidationError 会绕过统一信封直接抛给桥。
        return self._call(
            "update_person",
            lambda: self._db.update_person(pid, PersonPatch.model_validate(patch)),
        )

    def set_active(self, pid: int, active: bool) -> dict[str, object]:
        return self._call("set_active", lambda: self._db.set_active(pid, active))

    def delete_person(self, pid: int) -> dict[str, object]:
        return self._call(
            "delete_person",
            lambda: DeleteOneResult(deleted=self._db.delete_person(pid)),
        )

    def delete_many(self, ids: list[int]) -> dict[str, object]:
        return self._call("delete_many", lambda: self._db.delete_many(ids))

    def clear_draw_counts(self) -> dict[str, object]:
        return self._call("clear_draw_counts", self._db.clear_draw_counts)

    # -- 导入 -------------------------------------------------------------
    def pick_import_file(self) -> dict[str, object]:
        window = self._window
        if window is None:
            return _dump(fail("NO_WINDOW", "窗口尚未就绪"))
        try:
            picked = window.create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=("名单文件 (*.yml;*.yaml;*.txt;*.csv;*.json;*.pkl)",),
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("pick_import_file failed")
            return _dump(fail("DIALOG_FAILED", f"无法打开文件选择框：{exc}"))
        if not picked:
            return _dump(ok(FilePickResult(path=None)))
        return _dump(ok(FilePickResult(path=str(picked[0]))))

    def preview_import(self, path: str) -> dict[str, object]:
        from callname.import_service import preview_import

        return self._call(
            "preview_import", lambda: preview_import(self._db, Path(path))
        )

    def commit_import(
        self,
        path: str,
        mode: str,
        weight: int = 1,
        dedupe: bool = True,
    ) -> dict[str, object]:
        """mode 从 JS 过来是字符串，这里显式校验成枚举。"""
        from callname.import_service import commit_import

        return self._call(
            "commit_import",
            lambda: commit_import(
                self._db, Path(path), _import_mode(mode), weight, dedupe
            ),
        )

    # -- 内部 -------------------------------------------------------------
    def _call[T](self, name: str, action: Callable[[], T]) -> dict[str, object]:
        from callname.importers import RosterError

        try:
            return _dump(ok(action()))
        except (DbError, RosterError) as exc:
            logger.warning("{} rejected: {} {}", name, exc.code, exc.message)
            return _dump(fail(exc.code, exc.message))
        except ValidationError as exc:
            # 桥上传来的参数类型不对：同样是用户可见的输入错误，不是内部 bug。
            logger.warning("{} bad payload: {}", name, exc)
            return _dump(fail("BAD_PAYLOAD", "提交的数据格式不正确，请刷新后重试"))
        except Exception as exc:  # pragma: no cover
            logger.exception("{} failed", name)
            return _dump(fail("INTERNAL", f"{name} 失败：{exc}"))
