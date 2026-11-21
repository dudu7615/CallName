# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Windows，onedir）。

**只能在 Windows 上跑**，PyInstaller 不支持交叉编译：

    uv sync --group build
    uv run pyinstaller packaging/main.spec --noconfirm --clean

产物是 dist/CallName/，整个目录才是可运行单元，再交给 packaging/setup.iss
封成安装包。

为什么是 onedir 而不是 onefile：onefile 每次启动都要把全部 Python、QtWebEngine
资源解包到临时目录，点名器是上课时要秒开的工具，每次启动先等解包不能接受。

打包后的目录结构（PyInstaller 6 起非 exe 文件都在 _internal/ 下）::

    dist/CallName/
        CallName.exe
        _internal/
            callname/
                web/       <- 前端与字体，真实目录
            icon.png       <- 窗口图标，main.py 按 __file__ 同级查找
            base_library.zip / *.pyd

callname/ 是普通 Python 包，代码会被打进 PYZ 归档、不落成目录；但 `web/`
是静态资源，必须作为 datas 真实落盘。PyInstaller 把 ``__file__`` 统一解析到
_internal/ 下，所以 ``callname/paths.py`` 里的 ``WEB_DIR = .../callname/web``
拿到的正好是 ``_internal/callname/web``——datas 的 dest 必须写
``callname/web``，写成 ``web`` 或扁平放会把路径对不上。

icon.png 放在 ``.``，因为 paths.py 的 ROOT 是 ``callname/`` 的上一层，也就是
_internal/。

数据库 callname.db 不打包：它在 exe 旁边生成（ROOT/callname.db），卸载时
不删，用户数据跟着安装目录走。

本文件扩展名是 .spec，不在 ruff 的检查范围内；SPECPATH 由 PyInstaller 注入。
"""

import sys
from pathlib import Path

#: spec 在 packaging/ 下，仓库根是它的上一层。
ROOT = Path(SPECPATH).parent  # noqa: F821  # SPECPATH 由 PyInstaller 注入


def find_dlls() -> Path | None:
    """定位解释器的 DLLs 目录。

    venv 里没有 _ssl.pyd 和 OpenSSL 的 DLL，它们跟着基础解释器走，所以优先
    从 base_prefix 找；拿不到再退回 exe 所在目录和 sys.path 里的 DLLs 项。
    这不是洁癖：路径猜错时下面那段 binaries 会静默变成空列表，打包照样成功，
    问题要等到用户机器上……本项目其实不走 HTTPS，但 SQLModel 的 pysqlite /
    greenlet 之类依赖同样靠这些系统 DLL 兜底，缺了只在用户机器上报错。
    """
    candidates = [
        Path(sys.base_prefix) / "DLLs",
        Path(sys.executable).parent / "DLLs",
        *(Path(p) for p in sys.path if p.replace("\\", "/").endswith("/DLLs")),
    ]
    return next((p for p in candidates if p.is_dir()), None)


# 显式带上 _ssl 与 OpenSSL，避免将来加网络功能时在用户机器上才炸
# ImportError。Python 3.14 (OpenSSL 3) 的文件名是
# libcrypto-3-x64.dll / libssl-3-x64.dll。
REQUIRED = ("_ssl.pyd", "libcrypto*.dll", "libssl*.dll")
binaries = []
_dlls = find_dlls()
if _dlls:
    binaries = [
        (str(path), ".")
        for pattern in REQUIRED
        for path in sorted(_dlls.glob(pattern))
    ]

# 逐个 pattern 检查，而不是只看 binaries 是不是空：只匹配到其中一个也说明
# 另外几个丢了。这里直接让构建失败，别让残废产物发出去。
if sys.platform == "win32":
    missing = [
        pattern for pattern in REQUIRED if not _dlls or not list(_dlls.glob(pattern))
    ]
    if missing:
        raise SystemExit(
            "[packaging/main.spec] 缺少 HTTPS 依赖："
            f"{', '.join(missing)}（已尝试的 DLLs 目录：{_dlls}）。"
            "已中止构建。"
        )

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=[
        # 前端与内置字体。paths.py 的 WEB_DIR 指向 callname/web，
        # 冻结后 __file__ 在 _internal/callname/ 下，dest 必须完全一致。
        (str(ROOT / "callname" / "web"), "callname/web"),
        # 窗口图标。paths.py 的 ROOT 是 _internal/，所以放 "."。
        # Windows 走 System.Drawing.Icon 只认 ico，Linux 用 png，两个都带上，
        # 免得哪天用同一份 spec 在别的平台出包时图标悄悄缺失。
        (str(ROOT / "icon.png"), "."),
        (str(ROOT / "icon.ico"), "."),
    ],
    # pywebview 在 Windows 上是运行期动态 import webview.platforms.winforms，
    # 静态分析追不到；不列出来就会在用户机器上抛 "pythonnet cannot be loaded"。
    # winforms 里又用 clr.AddReference 反射加载 System.Windows.Forms 等程序集，
    # 由 pyinstaller-hooks-contrib 的 hook-clr / hook-clr_loader 处理。
    # 只在 Windows 上加：Linux 冒烟构建时 winforms 依赖 pythonnet，列上去只会
    # 报一堆 "hidden import not found" 的噪音。
    hiddenimports=["webview.platforms.winforms"] if sys.platform == "win32" else [],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    # SQLModel / SQLAlchemy 用了大量运行期反射，optimize 不能开。
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CallName",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压过的 Qt DLL 与 WebView2Loader 在部分机器上会加载失败，收益也不大
    upx=False,
    # 点名器是图形程序，不该带一个黑框；PIL 的报错走日志而不是控制台。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CallName",
)
