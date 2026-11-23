"""pywebview 窗口启动与命令行参数。"""

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal

import webview
from loguru import logger

from callname import __version__
from callname.api import MainApi, ManageApi
from callname.db import Database
from callname.draw import DrawSession
from callname.paths import APP_DIR, DB_PATH, ICON, LOG_PATH, WEB_DIR

# 与 style.css 的 --bg 一致：窗口创建时就用它，避免启动白闪。
BOARD_BG = "#070d18"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="callname", description="随机点名器")
    parser.add_argument("--manage", action="store_true", help="打开名单管理窗口")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="数据库路径")
    parser.add_argument("--debug", action="store_true", help="开启 WebView 调试")
    parser.add_argument(
        "--auto", type=int, default=0, metavar="N", help="自测：自动连抽 N 次"
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def _configure_logging(*, debug: bool) -> None:
    """入口处配置一次 loguru；保持默认格式，不传 format。

    冻结后 console=False 没有 stderr，必须同时落文件，否则出错时连线索都没有。
    日志文件跟着程序目录走，与 callname.db 一样属于「拷走整个目录就换电脑」。
    """
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if debug else "INFO")
    if getattr(sys, "frozen", False):
        logger.add(
            LOG_PATH,
            level="DEBUG" if debug else "INFO",
            rotation="1 MB",
            retention=3,
        )


GuiBackend = Literal["qt", "gtk", "cef", "mshtml", "edgechromium", "android", "cocoa"]


def _gui_backend() -> GuiBackend | None:
    """Linux 上钉死 Qt：否则装了 PyGObject 会悄悄换成 GTK/WebKit。"""
    return "qt" if sys.platform.startswith("linux") else None


def _require_window(window: webview.Window | None) -> webview.Window:
    """create_window 在正常路径下必然返回窗口；None 只可能来自内部失败。"""
    if window is None:
        raise RuntimeError("pywebview 创建窗口失败")
    return window


def _prepare_environment() -> None:
    """以 root 运行时 QtWebEngine 的 sandbox 会白屏，与 pywebview 的平台判断无关。"""
    if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")


def _start_auto(window: webview.Window, count: int) -> None:
    """--auto N：等页面加载完后用 evaluate_js 触发按钮，避免模拟鼠标。

    两种模式共用一条路径：先「点开始」让转盘转起来，再「点停」。
    自动模式下 clickStop 是空操作，转盘按 SPIN_MS 自己停。
    """

    def run() -> None:
        time.sleep(1.5)
        for index in range(count):
            logger.info("auto draw {}/{}", index + 1, count)
            window.evaluate_js("window.clickStart && window.clickStart()")
            time.sleep(0.7)   # 让手动停模式真的转起来再停
            window.evaluate_js("window.clickStop && window.clickStop()")
            # 自动模式 3.0s 自停；手动模式 0.7s 旋转 + 约 0.7-1.6s 平滑减速
            time.sleep(3.6)
        state = window.evaluate_js("window.__state ? window.__state() : null")
        logger.info("auto final state: {}", state)

    thread = threading.Thread(target=run, name="auto-draw", daemon=True)
    thread.start()


def _open_main(db: Database, *, debug: bool, auto: int) -> int:
    session = DrawSession(db)
    api = MainApi(session=session, db=db)
    window = webview.create_window(
        "点名",
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=1280,
        height=760,
        min_size=(900, 600),
        background_color=BOARD_BG,
    )
    handle = _require_window(window)
    api.attach(handle)
    if auto > 0:
        handle.events.loaded += lambda: _start_auto(handle, auto)
    webview.start(gui=_gui_backend(), debug=debug, http_server=True, icon=str(ICON))
    return 0


def _open_manage(db: Database, *, debug: bool) -> int:
    api = ManageApi(db=db)
    window = webview.create_window(
        "名单管理",
        url=str(WEB_DIR / "manage.html"),
        js_api=api,
        width=1100,
        height=760,
        min_size=(860, 560),
        background_color=BOARD_BG,
    )
    api.attach(_require_window(window))
    webview.start(gui=_gui_backend(), debug=debug, http_server=True, icon=str(ICON))
    return 0


def manager_command(db_path: Path) -> list[str]:
    """管理窗口子进程命令；frozen 分支为将来打包预留。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--manage", "--db", str(db_path)]
    return [sys.executable, "-m", "callname", "--manage", "--db", str(db_path)]


def spawn_manager(db_path: Path) -> subprocess.Popen[bytes]:
    """独立进程启动管理窗口，主窗口关闭后仍可存活。"""
    command = manager_command(db_path)
    logger.info("spawn manager: {}", command)
    return subprocess.Popen(
        command,
        cwd=str(APP_DIR),
        start_new_session=os.name == "posix",
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(debug=bool(args.debug))
    _prepare_environment()

    db_path: Path = args.db
    logger.info("callname {} db={}", __version__, db_path)
    db = Database(db_path)
    db.migrate()

    if args.manage:
        return _open_manage(db, debug=bool(args.debug))
    return _open_main(db, debug=bool(args.debug), auto=int(args.auto))
