# CallName 随机点名

Web UI 桌面点名器：滚轮从下往上滚动抽签，SQLite 存名单，每人可设权重。

## 安装

```bash
uv sync
```

> 本项目**只用 `uv`** 管理依赖和运行脚本。不要用 `pip`，也不要用 `uv pip install`。

## 运行

```bash
uv run main.py                    # 主窗口：抽签
uv run main.py --manage           # 名单管理窗口（也可以点主窗口右下角 ⚙）
```

数据库 `callname.db` 生成在程序目录旁边，拷走整个目录即可换电脑。
打包版（Windows）里 exe 旁边的 `callname.db` 就是它，安装包不会覆盖、卸载也不会删。

## 用法

- **开始点名**：滚轮从下往上转，停在中间高亮带的名字就是本轮被点到的人。
- **手动停**（右下角开关，状态会记住）：打开后主按钮变成「开始」，点一下滚轮
  持续旋转、按钮变成「停」；再点一下**立刻停住**，落到紧挨着的下一格，那一格
  就是结果（点停当帧出结果，不再有减速等待）。适合想自己控制揭晓时机的课堂。
  关掉开关回到「开始点名」的自动模式。
- 抽到过的人本轮不再出现；全部抽完会自动进入下一轮（HUD 显示「第 N 轮」）。
- **重置列表**：重新开始一轮（**不清空**数据库里的累计抽中次数）。
- **⚙**：打开名单管理，可增删改名字、改权重、启用/停用、导入旧名单、清零累计次数。

## 管理员密码

名单管理窗口由管理员密码保护：

- **第一次打开设置窗口**时会要求设置密码（至少 4 位），设置后直接进入；
- 之后每次打开设置窗口都要输入密码，输错会被拒绝并提示；
- 解锁后可以在工具栏点「修改密码」，需要先输入原密码（会校验原密码）；
- **不提供重置入口**，请妥善保管密码。只有数据库里 `meta` 表缺少
  `admin_password` 这一行时，窗口才会重新要求设置密码——那需要你自己手工改
  `callname.db`，目的是不让别人随手就能绕过。

密码只以 Argon2id 哈希存在数据库 `meta` 表里，不落明文。这套密码的作用是
课堂上防止学生随手改名单，**不是安全边界**：能读写 `callname.db` 的人本来就能
直接改库，所以不设「重大安全功能」的预期。

## 权重是什么

**权重 = 优先级，不是频率。**

每人每轮仍然恰好被点到一次；权重只决定「谁更可能先被点到」——
权重 3 的人比权重 1 的人更早出现的概率约 3 倍，但一轮下来两人的次数一样。

导入时文件里没写权重的条目，统一使用导入弹层里的「默认权重」。

## 导入名单

管理窗口 →「导入文件…」，支持 `.yml` / `.yaml` / `.txt` / `.csv` / `.json` / `.pkl`。

`.txt` 一行可以写多个姓名，空白（含全角空格）、中英文逗号、顿号或换行都算分隔符。

> `.pkl` 导入会执行文件中的代码，只导入自己生成的文件。

## 开发

```bash
uv run pytest -q                              # 单元测试
uv run mypy . --explicit-package-bases        # 类型检查（strict，必须全绿）
uv run main.py --auto 3                       # 自测：自动连抽 3 次
```

开发约束（详见 `CLAUDE.md`）：

- 依赖与脚本一律走 `uv`，禁止 `pip` / `uv pip`。
- 日志一律用 `loguru` 的默认输出格式，禁止 `print` / `logging`，禁止自定义 `format=`。
- 所有代码必须通过 `uv run mypy . --explicit-package-bases`（strict），非必要不用 `Any`。
- **所有类型结构必须用 pydantic**（配置、消息、API 请求/响应、抽签结果、导入预览……），
  不用 `TypedDict` / `NamedTuple`，模块间不传裸 `dict`。
- 每完成一件事提交一次 commit，`-m` 写清做了什么、为什么。

| 路径 | 作用 |
| --- | --- |
| `callname/models.py` | SQLModel 表定义（person / draw_log / meta） |
| `callname/schemas.py` | pydantic 请求/响应模型（API 信封） |
| `callname/db.py` | engine、PRAGMA、迁移、CRUD |
| `callname/auth.py` | 管理员密码的 Argon2id 哈希与校验 |
| `callname/draw.py` | 本轮会话与加权抽样 |
| `callname/importers.py` | 名单解析（yml/txt/csv/json/pkl） |
| `callname/import_service.py` | 导入预览与落库编排 |
| `callname/api.py` | pywebview 的 js_api 桥 |
| `callname/app.py` | 启动参数与窗口 |
| `callname/web/` | 前端（原生 HTML/CSS/JS，无构建步骤；内置 Maple Mono 字体与转盘音效，见各自许可证文件） |

## 界面字体

界面使用随包分发的 **Maple Mono NF CN**（`callname/web/MapleMono-NF-CN-Regular.ttf`），
采用 SIL Open Font License 1.1，许可证全文见 `callname/web/OFL.txt`。
字体文件是原样分发的，未做子集化或改名。

## 转盘音效

转盘每跨过一格响一记短促的 tick，停稳点亮结果时响一声提示音。
两者来自 Kenney 的 **Interface Sounds 1.0** 音效包（CC0 1.0），原样分发为
`callname/web/tick.ogg`（23 ms）与 `callname/web/finish.ogg`（290 ms），
出处、原始文件名与 sha256 见 `callname/web/Kenney-Audio-LICENSE.txt`。

- 手动停模式转速约 38 格/秒，逐格播放会糊成连续噪声，因此每 3 格抽稀一次（约 13 次/秒）。
- 主窗口右下角的喇叭按钮可以静音，状态存在数据库 `meta` 里，重启后保持。
- `--auto` 自测是程序化点击，不算可信用户手势，浏览器会拒绝启动音频，**无声属预期**。
  自测时看 `window.__state()` 里的 `ticks_played` / `finishes_played` 即可确认回调有跑到。

## 打包与发布

Windows 专用，PyInstaller 不支持交叉编译。详细说明见 [`packaging/README.md`](packaging/README.md)。

```powershell
uv sync --group build
uv run pyinstaller packaging/main.spec --noconfirm --clean   # → dist/CallName/
ISCC.exe /DAppVersion=2.2.0 packaging\setup.iss               # → dist\installer\
```

**合并进 `main` 后 GitHub Actions 会自动跑测试、打包并发布**，产物在
Actions 的 Artifacts 与 Release 里；手动触发跑别的分支只打包、不发布。
发版本的流程：在 PR 里改 `pyproject.toml` 的 `version` → 合并进 `main`。

产物：

- `CallName-Setup-<版本>.exe` —— 安装包（装到 `%LOCALAPPDATA%\CallName`）
- `CallName-portable-<版本>.zip` —— 免安装版，解压双击 `CallName.exe`

## 历史

`doc/` 下的文档描述的是 V1 的 QML 实现，已过时，仅作存档。

`1-webui-2-sqlite-memoized-eagle.md` 是 V2 的设计与实测记录。
