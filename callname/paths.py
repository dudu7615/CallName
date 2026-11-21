"""程序路径常量：便携模式，所有可变数据都在程序目录旁。

开发时程序目录 = 仓库根；PyInstaller 冻结后程序目录 = exe 所在目录
（``dist/CallName/``），而静态资源（前端、字体、图标）在 ``_internal/`` 下。
两者必须分开：数据库要写在用户能找到、且升级/重装不会覆盖的地方，
资源则跟着打包目录走。
"""

import sys
from pathlib import Path

#: 资源根目录：开发时是仓库根，冻结后是 ``_internal/``。
BUNDLE = Path(__file__).resolve().parent.parent

#: 程序目录：可写的用户数据（callname.db）放在这里。
#: 冻结后取 exe 所在目录；开发时就是仓库根，两者路径恰好相同。
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BUNDLE

#: 前端资源目录：始终在包内，冻结后是 ``_internal/callname/web``。
WEB_DIR = Path(__file__).resolve().parent / "web"

DB_PATH = APP_DIR / "callname.db"

#: 窗口图标。Windows 走 pywebview 的 winforms 后端，System.Drawing.Icon
#: 只认 .ico；Linux 的 Qt 用 png 更清晰。
ICON = BUNDLE / ("icon.ico" if sys.platform == "win32" else "icon.png")

#: 冻结后没有控制台，日志只能落文件；开发时这个文件不该生成。
LOG_PATH = APP_DIR / "callname.log"
