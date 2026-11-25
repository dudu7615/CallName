# packaging/

Windows 打包。**只能在 Windows 上执行**（PyInstaller 不支持交叉编译）：

```powershell
uv sync --group build
uv run pyinstaller packaging/main.spec --noconfirm --clean     # → dist/CallName/
# 想在本机出安装包，再补一步（需自行安装 Inno Setup 6）：
ISCC.exe /DAppVersion=2.2.0 packaging\setup.iss                # → dist/installer/*.exe
```

只看效果、不需要安装包时，跑完第一条就能双击 `dist/CallName/CallName.exe`。

`.github/workflows/release.yml` 走的就是这两步：合并进 `main` 后自动跑
（先跑 `pytest` 与 `mypy`），产物传到 Actions Artifacts；该版本还没有
Release（或上次发到一半失败）时顺带建一个 Release。手动触发跑别的分支
只打包、不发布。所以发版本的流程是：**在 PR 里改 `version` → 合并**。

## 产物

| 文件 | 说明 |
|---|---|
| `dist/installer/CallName-Setup-<版本>.exe` | 安装包 |
| `dist/CallName-portable-<版本>.zip` | 免安装版，解压双击 `CallName.exe` |

## 目录结构（打包后）

```
dist/CallName/
    CallName.exe
    _internal/
        callname/
            web/       # 前端：HTML/CSS/JS + MapleMono 字体 + 音效（各带许可证）
        icon.ico       # 窗口图标（Windows 走 System.Drawing.Icon，只认 ico）
        base_library.zip / *.pyd ...
```

`callname/*.py` 是纯 Python，会被打进 PYZ 归档、不落成目录，但 PyInstaller
把 `__file__` 统一解析到 `_internal/` 下。所以 `callname/paths.py` 里
`BUNDLE = Path(__file__).resolve().parent.parent` 拿到的就是 `_internal/`，
`WEB_DIR` 是 `_internal/callname/web`——spec 里 `callname/web` 的 dest 必须
一字不差，写成 `web` 就会白屏。

`web/` 在源码里就是包内目录，打包后仍保持同样的相对位置，所以 `paths.py`
不需要为冻结另写分支。`web/` 必须平铺（见 CLAUDE.md）。

## 数据与日志

- `callname.db` 由程序在 **exe 旁边** 生成（`paths.APP_DIR/callname.db`），
  与开发时的 `<仓库>/callname.db` 是同一个相对位置。
- 冻结后没有控制台，日志同时写 `callname.log`（exe 旁边，1 MB 轮转、保留 3 份）。
  开发时不写这个文件。
- 安装包**不包含** `callname.db`；覆盖升级不会碰它，卸载也不删。名单是老师
  攒出来的数据，卸载重装后还要接着用。想彻底清干净就手动删
  `%LOCALAPPDATA%\CallName`。

## 安装器（`setup.iss`）

### 两个名字

| 变量 | 值 | 用在哪 |
|---|---|---|
| `AppName` | `CallName` | 安装目录、产物文件名 |
| `AppDisplayName` | `随机点名器` | 所有快捷方式、安装/卸载向导 |

`AppName` 牵扯升级链（安装目录变了 `UsePreviousAppDir` 就找不到旧版本），
改 `AppDisplayName` 是安全的。

### 快捷方式

`[Tasks]` 只有一个复选框：桌面快捷方式（默认勾选）。

**不做开机自启**——点名器只在课堂上用，没必要常驻。需要的话用户自己把
快捷方式拖进「启动」文件夹。

### 安装位置与权限

装到 `%LOCALAPPDATA%\CallName`，`PrivilegesRequired=lowest`，不弹 UAC。
**刻意不设 `PrivilegesRequiredOverridesAllowed`**：安装目录用户可写，而卸载时
会经 powershell 执行 `{app}\killapp.ps1`；一旦允许临时提权卸载，就等于给了
任何能写这个目录的人一个提权执行点。卸载时也加了 `if IsAdmin then` 跳过。

结束进程走 `packaging/killapp.ps1`（按 exe 完整路径匹配），**不是**
`taskkill /im`——后者按映像名匹配，会把机器上任何同名程序一起强杀。

### 几条踩过的坑（编译期才会暴露）

改完务必真的编译一遍——`ISCC.exe /DAppVersion=x packaging\setup.iss`：

- 注释里**不要写 `[UninstallRun]` 这类段名**：Inno 会把它当成新的段标记，
  报 `Invalid section tag`
- 注释里**不要写 `{app}`**：花括号会提前闭合 Pascal 注释，报 `Syntax error`
- `LoadStringFromFile` 的第二个参数必须是 `AnsiString`，`String` 会报 `Type mismatch`

### 升级

`[Files]` 用 `ignoreversion recursesubdirs` 覆盖整目录；`callname.db` 不在
安装包里，所以不会被覆盖。安装过程中出错时 Inno 会整体回滚，不需要 staging。

## 几个不能改的东西

- `setup.iss` 里的 **`AppId`**：软件的唯一标识，改了等于换了另一个程序，
  老版本的覆盖安装和卸载都会错乱。
- **exe 名 `CallName.exe`**：`setup.iss` 的 `[Files]`/`[Icons]`、`killapp.ps1`
  的调用、release.yml 的产物检查都按这个名字写；改名要同步改。
- spec 里 `callname/web` 与 `icon.*` 的 dest：见上文。

## 图标

仓库根的 `icon.ico` 用作 exe 图标、窗口图标与安装器图标（已是多尺寸 ICO）；
Linux 开发时 `paths.ICON` 用 `icon.png`，Qt 显示更清晰。
