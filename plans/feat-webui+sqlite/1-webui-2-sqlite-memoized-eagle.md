# 点名器 V2：Web UI 滚轮抽签 + SQLite 名单

## 硬性开发规则（用户要求，严格执行）

1. **依赖与运行一律 `uv`**：`uv add` / `uv sync` / `uv run`。
2. **禁止 `pip` 和 `uv pip install`**（包括验证用的临时安装）。
3. **日志只用 `loguru`，且用默认输出格式**：`from loguru import logger`；**禁止 `print()` 与 `logging` 模块**，
   **禁止自定义 `format=`**。入口 `logger.remove(); logger.add(sys.stderr, level="INFO")`，库代码只调用不配置。
4. **必须通过 `uv run mypy . --explicit-package-bases`（strict）**，非必要不用 `Any`。
   `pyproject.toml` 配 `[tool.mypy] strict = true`、`mypy_path = "."`；
   缺 stub 的第三方库用 `[[tool.mypy.overrides]]` 局部 `ignore_missing_imports`。
5. **所有类型结构必须用 pydantic**：配置、消息、API 请求/响应、抽签结果、导入预览、列表项、
   状态快照、错误信封——所有跨函数/跨模块/跨桥传递的结构都是 `BaseModel`（SQLModel 本身即 pydantic）。
   **不用 `TypedDict` / `NamedTuple`，模块间不传裸 `dict`/`tuple`**；枚举用 `StrEnum`，可选值用 `Literal`。
   过桥前 `model_dump(mode="json")`。
6. **每完成一件事 commit 一次**，`-m` 写清做了什么与为什么；提交前 `uv run pytest -q`
   与 `uv run mypy . --explicit-package-bases` 必须全绿。

## Context

现在的 CallName 是一个 54 行的 PySide6 小工具：`main.py` 从 `names.pkl` 读 52 个名字，`random.choice` 取一个显示在 `QTextEdit` 里，"抽过就移除"的逻辑被注释掉了（doc/doc.md 描述的 QML 版本和实际代码已经不一致）。分支 `feat/webui+sqlite` 目前与 `main` 完全一致，没有历史包袱。

要把它重做成：

1. **Web UI 桌面应用**：名字显示区改成**从下往上滚动**的滚轮（老虎机）效果；一个「开始点名」按钮，一个「重置列表」按钮。
2. **本次运行内不重复**：抽到过的名字本轮不再出现；全部抽完或点重置后，程序内列表自动重置。不跨重启保存。
3. **SQLite 存名单**，每人一个**权重**，并额外记一列**累计抽中次数**。
4. **名单管理单独一个工具**（独立窗口/独立入口），主界面只负责抽签；主窗口右下角一个 ⚙ 按钮启动它。
5. **手动导入**旧名单（yaml/txt/csv/json/pkl），不自动导入。

已确认的产品语义：

- **权重 = 优先级**（Plackett–Luce 无放回抽样）：权重只决定"谁更可能先被点到"，每人每轮仍然只被点到一次。已用 20 万次模拟验证：每人整轮总次数完全相等，首位概率严格正比于权重。
- **重置按钮只重置本轮名单**，数据库里的累计抽中次数不清零（管理工具里另给一个「清零累计次数」）。
- 数据库文件放在**程序目录旁**（`callname.db`），便携模式。**本轮不做 PyInstaller 打包**，只需 `uv run` 能跑。
- 旧文件**全部删除**（Qt 界面、tools、tests 演示脚本、data/、names.pkl、style.qss），每完成一个改动就 commit 一次。

### 为什么 pywebview 还要装 Qt（以及为什么 Windows 不会带上它）

pywebview 自己不渲染页面，它只是"壳 + Python↔JS 桥"，真正画网页的是系统 WebView：

| 平台 | pywebview 后端 | 需要的绑定 |
|---|---|---|
| Windows | winforms + **WebView2**（EdgeChromium） | `pythonnet`（pywebview 自动依赖） |
| macOS | **WKWebView**（Cocoa） | `pyobjc`（pywebview 自动依赖） |
| Linux | **GTK + WebKit2** 或 **Qt + QtWebEngine** | `PyGObject` 或 `PySide6` |

Linux 上 `webview/guilib.py` **先试 GTK，失败才退 Qt**。本机 venv 看不到系统的 `/usr/lib/python3/dist-packages/gi`，`import gi` 直接失败，于是退回 Qt —— 这就是 Linux 需要 PySide6 + qtpy 的原因。所以 `pyproject.toml` 里给这两项加了 `sys_platform == 'linux'` 标记。

**Windows 依赖解析已实测**（`uv pip compile --python-platform windows --python-version 3.14`）：

```
bottle, cffi, clr-loader, proxy-tools, pycparser, pythonnet, pywebview, pyyaml, typing-extensions
```

**没有任何 PySide6 / PySide6-Essentials / PySide6-Addons / shiboken6 / qtpy** —— 标记生效，Windows 上不会拉那 ~400MB 的 QtWebEngine。作为对照，同一份依赖在 Linux 上解析出 `pyside6 + pyside6-addons + pyside6-essentials + shiboken6 + qtpy`。

唯一需要在 Windows 上额外确认的是 **WebView2 Runtime**：Win10 1803+/Win11 通常随 Edge 预装；若目标机器没有，需要装微软的 Evergreen Runtime（这是 pywebview 在 Windows 的既定前提，与本次改动无关）。

另外为了让 Linux 上**不**悄悄换后端，`app.py` 里钉死 `gui = "qt" if sys.platform.startswith("linux") else None`。

## 已验证的技术结论（本次探查实测）

- pywebview 6.2.1 + PySide6 6.12（cp310-abi3 wheel，可用于 3.14）+ qtpy 在本机 3.14.6 下正常工作。
- `webview.start(http_server=True)` 会把本地目录用 `http://127.0.0.1:随机端口/` 服务起来，ES module、相对路径 CSS、`fetch` 子目录都正常（避免 `file://` 的 CORS 问题）。服务根目录 = 传入 HTML 文件所在目录，所以 `web/` 下所有页面/JS/CSS 必须**平铺**，不能嵌套子目录再 `../` 引用。
- `js_api` 的每个方法在**独立工作线程**里执行（`webview/util.py:js_bridge_call`），返回值直接 `json.dumps`。因此：① SQLite 必须用 `check_same_thread=False` 的长连接 + 锁（见下文 db.py），不能依赖默认线程亲和；② **API 方法只能是普通 `def`，不能是 `async def`**（协程对象无法 JSON 序列化）；③ 返回值不能含 `Path`/`datetime`/`set`。
- `window.create_file_dialog(webview.FileDialog.OPEN, ...)` 在 Qt 后端可用，取消返回 `None`；调用时会阻塞当前工作线程等 GUI 线程，按钮要保持 disabled。
- `window.evaluate_js()` 可以从后台线程调用，用于管理工具退出后刷新主窗口。
- 不要设 `private_mode=False`：pywebview 会因此强制固定 `http_port=42001`，端口被占或开第二个实例就失败。默认 `private_mode=True` + 随机端口，保持不动。
- 滚轮原型已在 QtWebEngine 里截图验证：赢家与高亮带中心偏差 0px，2.8s 上滚到位。
- 本机有真实 X display（1920x1080），可用 `xdotool search --name` + `xwd` + `ffmpeg` 抓真实窗口截图做验收。
- 滚轮在 125% DPI（`QT_SCALE_FACTOR=1.25`，`devicePixelRatio=1.25`）下实测赢家偏移 0.0000038px —— 因为所有几何量都来自 `getBoundingClientRect()`，不写死像素。
- 条带覆盖不变量已数值验证：`clip` 高度 2.4h–4h 任意值下，`restY = H/2 - h/2 - above*h` 时条带顶端 ≤ 0 且底端 ≥ H（`above=26, below=5` 与 `above=2, below=2` 都成立），所以静止画面永远不会露白。

## 目标结构

```
pyproject.toml            # 依赖 + [project.scripts] callname
uv.lock
main.py                   # 薄入口：from callname.app import main; raise SystemExit(main())
callname/
  __init__.py               # __version__
  __main__.py               # `python -m callname` 入口（管理窗口子进程用得到）
  paths.py                # ROOT / WEB_DIR / DB_PATH / ICON（程序目录旁，便携）
  db.py                   # Database：engine + Session、PRAGMA、migrate、CRUD（全走 SQLModel）
  models.py               # Person / DrawLog / Meta（SQLModel table=True）
  draw.py                 # DrawSession：本轮已抽集合、加权抽样、cycle
  importers.py            # yaml/txt/csv/json/pkl 解析 + 去重预览
  builtin_rosters.py      # 内嵌的 4 份旧名单（2/93/94/96，共 205 个唯一名字）
  api.py                  # MainApi / ManageApi（js_api 类，全部普通 def）
  schemas.py              # pydantic 请求/响应模型（API 信封、抽签结果、导入预览）
  app.py                  # argparse --manage/--db/--debug/--auto，启动 pywebview 窗口
  web/                    # 平铺，不要嵌套子目录（HTTP 根 = 本目录）
    index.html            # 主窗口：滚轮
    manage.html           # 管理窗口：名单表格
    style.css             # 共用样式（沿用原渐变 #84fab0 → #8fd3f4）
    reel.js               # 滚轮引擎（ES module）
    main.js               # 按钮、HUD、⚙、状态轮询
    manage.js             # 表格编辑、导入
tests/
  conftest.py
  test_db.py
  test_draw.py
  test_importers.py
  test_api.py
```
删除：`Ui/`、`tools/`、`tests/base64.py`、`tests/getListFromBase64.py`、`data/`、`names.pkl`、`style.qss`、`envernment.yml`（已在工作区删除）。`data/` 与 `names.pkl` 里的名字先搬进 `callname/builtin_rosters.py`，再删文件。保留 `icon.png`、`icon.ico`、`README.md`（改写）、`doc/`（旧文档保留但 README 里注明已过时）。

## 数据层（SQLModel）

不手写 SQL、不手写 `CREATE TABLE` —— 用 **SQLModel**（Pydantic + SQLAlchemy 2.x 的官方轻封装）定义模型，建表交给 `SQLModel.metadata.create_all()`，查询用 `select()`。已在本机 Python 3.14.6 上实测：`sqlmodel 0.0.50 / sqlalchemy 2.1.9 / pydantic 2.14.3` 全部有 3.14 wheel（pydantic-core 有 cp314 原生轮子），建表、写入、查询、WAL、并发都跑通。

`callname/paths.py`：

```python
ROOT = Path(__file__).resolve().parent.parent   # 程序目录
WEB_DIR = Path(__file__).resolve().parent / "web"
DB_PATH = ROOT / "callname.db"                  # 便携：exe 旁边
ICON = ROOT / "icon.png"
```

`callname/models.py`：

```python
from datetime import datetime, timezone

class Person(SQLModel, table=True):
    __tablename__ = "person"
    __table_args__ = (
        CheckConstraint("weight BETWEEN 1 AND 99", name="ck_person_weight"),
        CheckConstraint("active IN (0,1)", name="ck_person_active"),
        CheckConstraint("draw_count >= 0", name="ck_person_draw_count"),
        CheckConstraint("length(trim(name)) > 0", name="ck_person_name"),
    )
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1)
    weight: int = Field(default=1, ge=1, le=99)      # 权重 = 优先级
    active: bool = Field(default=True)
    draw_count: int = Field(default=0, ge=0)          # 累计抽中次数
    sort_order: int = Field(default=0)
    last_drawn_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class DrawLog(SQLModel, table=True):
    __tablename__ = "draw_log"
    id: int | None = Field(default=None, primary_key=True)
    person_id: int = Field(foreign_key="person.id", ondelete="CASCADE")
    name_snapshot: str
    weight_snapshot: int
    cycle: int
    drawn_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Meta(SQLModel, table=True):
    __tablename__ = "meta"
    key: str = Field(primary_key=True)
    value: str
```

⚠️ **SQLModel 0.0.50 的时间戳必须是 timezone-aware**：`default_factory=datetime.now` 会在 `commit()` 时抛 `ValueError: Datetime values must have timezone information`（已实测）。所以统一用 `datetime.now(timezone.utc)` 存库，展示时再 `.astimezone()` 转本地时间（管理窗口显示「最后抽中」用）。若想存 naive，字段要显式标注 `NaiveDatetime` —— 不推荐。

已实测确认：`__table_args__` 里的 `CheckConstraint` 会进 DDL；`weight=0` 插入被 `IntegrityError` 拒绝；`Field(foreign_key=..., ondelete="CASCADE")` + `PRAGMA foreign_keys=ON` 下删人确实级联删掉日志。

`callname/db.py`：引擎 + 每调用一个 `Session`（SQLAlchemy 的 `Session` 不是线程安全的，必须按调用新建；引擎本身线程安全）。

```python
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 5},
    pool_pre_ping=True,
)

@event.listens_for(engine, "connect")
def _set_pragmas(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")     # 管理窗口是独立进程同时写，必须开
    cur.execute("PRAGMA foreign_keys=ON")      # SQLite 默认关闭，级联删除要靠它
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()
```

- 建表：`SQLModel.metadata.create_all(engine)`，幂等。
- 迁移：`PRAGMA user_version` + `MIGRATIONS = [v1_create_all]`，`migrate()` 执行到 `len(MIGRATIONS)`。当前只有 v1，留好分支。
- **`draw_count` 必须用原子 UPDATE，不能读-改-写**。已实测：8 线程各 100 次 ORM 读-改-写（`row.cnt += 1; session.add(row)`）只记到 **133/800** 次，静默丢更新；改成 `session.exec(update(Person).where(...).values(draw_count=Person.draw_count + 1))` 后精确 **800/800**，零异常。管理窗口是独立进程，会真的并发写同一个库，所以这条是硬要求。
- `Database` 类包一层：`session()` 上下文管理器（`with db.session() as s:`）、`transaction()`（`with db.transaction() as s:` 内 `s.commit()`，异常自动 `rollback`），内部再叠一把 `threading.RLock` 串行化本进程的写操作（`DrawSession` 的 `_drawn` 集合也需要同一把锁）。
- 查询/CRUD 全部用 SQLModel：`s.exec(select(Person).where(Person.active == True).order_by(Person.sort_order, Person.id)).all()`、`s.get(Person, pid)`、`s.add(...)`、`s.delete(...)`、`s.exec(delete(Person).where(...))`、`s.exec(update(Person).where(...).values(...))`。
- `meta` 表存 `roster_version`、`cycle`。`cycle` 持久化让 `draw_log.cycle` 跨重启单调递增；**本轮已抽集合本身不持久化**（需求：只在本次运行有效）。
- `roster_version` 每次名单变更（增删改/启用/导入/清计数）+1，主窗口轮询它刷新 HUD 与假名池。
- 方法：`list_people(query="")`、`add_person(name, weight)`、`update_person(id, name=…, weight=…, active=…)`、`delete_person(id)`、`delete_many(ids)`、`get_meta/set_meta`、`get_cycle()`、`bump_cycle()`、`bump_roster_version()`、`record_draw(person_id, name, weight, cycle)`（原子 `draw_count+1` + 写 `last_drawn_at` + 插 `DrawLog`）、`clear_draw_counts()`（`draw_count=0` + `DELETE draw_log`）。
- **不做 `UNIQUE(name)`**：真实班级有同名同学；身份是 `id`，去重只是导入时的策略。添加同名时返回 `warning: "DUPLICATE_NAME"`，前端标黄提示但不阻止。
- `draw_count` 冗余在 `person` 上（需求要求"数据库加一列"），`draw_log` 是可重建它的审计日志（`UPDATE person SET draw_count=(SELECT count(*) FROM draw_log ...)`，管理窗口的「校验/修复」按钮可选加）。

## 抽签逻辑（`callname/draw.py`）

```python
class DrawSession:
    def __init__(self, db: Database, rng: random.Random | None = None) -> None
    def status(self) -> StatusResult        # total/active/remaining/drawn/cycle/roster_version/names
    def draw(self) -> DrawResult            # 见下
    def reset(self) -> StatusResult         # 只清 _drawn；cycle 保留
```

全部返回 `schemas.py` 里的 pydantic 模型，不用裸 dict。

`draw()` 在同一把进程内锁 + 同一个 SQLModel `Session` 事务里完成（防连点；JS 侧另有 `busy` 标志）：

1. `with db.transaction() as s:` → `s.exec(select(Person).where(Person.active == True).order_by(Person.sort_order, Person.id)).all()`。
2. 名单为空 → 回滚并返回 `ApiResponse[DrawResult]` 的失败信封（`code="EMPTY_ROSTER"`），不启动动画。
3. `remaining = [p for p in people if p.id not in self._drawn]`（**每次都从库重算再和内存集合做差**，管理窗口改了名单立刻生效，不需要失效逻辑）。
4. 若 `remaining` 为空：清空 `_drawn`、`cycle = bump_cycle()`、`remaining = people`，标记 `auto_reset=True`（HUD 提示"本轮已抽完，已自动重置"）。
5. `pick = self._rng.choices(remaining, weights=[max(p.weight, 0) for p in remaining], k=1)[0]` —— 权重即优先级，已用 20 万次模拟验证：整轮每人次数完全相等，首位概率严格正比于权重。权重全为 0（手改库）时退回 `rng.choice`，不崩。
6. 同一事务里记一次抽签（**原子** `update(Person).values(draw_count=Person.draw_count + 1, last_drawn_at=...)` + `s.add(DrawLog(...))`），提交；然后 `self._drawn.add(pick.id)`。**先落库再播动画**：播到一半被杀掉，这次抽签也算数。`logger.info("draw id={} name={} cycle={} remaining={}", ...)`。
7. 生成滚轮假名：`decoys = [rng.choice(others).name for _ in range(31)]`，`others` 为空（只剩 1 人）时用 `[winner]` 兜底。假名池用「本轮还没抽到的人」，这样滚轮里不会立刻出现重复的已抽名字（只剩 1 人时才退化为同一名字滚动）。
8. 返回 `ApiResponse[DrawResult]`（`id/name/weight/decoys/total/remaining/cycle/auto_reset/roster_version`）。

删除某人后，其 id 留在 `_drawn` 里无害（集合大小上界是名单人数，重置时清空）。

## pywebview 桥（`callname/api.py`）

**约定**：全部普通 `def`；参数与返回值都是 pydantic 模型，返回前 `model_dump(mode="json")`。错误用统一信封，而不是抛异常：

```python
class ApiError(BaseModel):
    code: str          # 稳定 ASCII 键，测试/分支用
    message: str       # 中文提示，直接显示

class ApiResponse[T](BaseModel):   # 或分别定义 Ok/Err 两个模型
    ok: bool
    data: T | None = None
    error: ApiError | None = None
```

`code` 是稳定 ASCII 键（测试/分支用），`message` 是中文提示（直接显示）。真正的 bug 才让异常冒泡成 rejected promise（并 `logger.exception` 记录），JS 顶层统一 catch 显示"出错了：…"。

`MainApi`（主窗口）：

| 方法 | 作用 |
|---|---|
| `status()` | `{total, active, remaining, drawn, cycle, roster_version, names}`（`names` = 启用的名字，前端直接拿来造假名，省一次调用） |
| `draw()` | 见上 |
| `reset()` | 只重置本轮；tooltip「重新开始一轮（不清空累计次数）」 |
| `open_manage()` | 起独立进程；幂等（`proc.poll() is None` 直接返回） |

`ManageApi`（管理窗口）：

| 方法 | 作用 |
|---|---|
| `list_people(query="")` | 全量（含停用），按 `draw_count DESC, sort_order, id` |
| `add_person(name, weight=1)` / `update_person(id, name=…, weight=…, active=…)` / `delete_person(id)` / `delete_many(ids)` | CRUD |
| `set_active(id, active)` | 启用/停用 |
| `clear_draw_counts()` | 清零累计次数（前端二次确认弹层） |
| `stats()` | `{total, active, sum_draws, last_draw_at}` |
| `pick_import_file()` | `create_file_dialog(OPEN, file_types=("名单文件 (*.yml;*.yaml;*.txt;*.csv;*.json;*.pkl)",))`；取消返回 `{"ok": True, "data": None}` |
| `preview_import(path)` | `{format, count, file_dups, db_dups, names}`，不落库 |
| `commit_import(path, mode, weight, dedupe=True)` | `mode ∈ {"merge","replace"}`，返回 `{added, updated, skipped}` |

窗口句柄用**下划线属性** `self._window`：pywebview 的 `get_functions` 会暴露所有公开方法，并且会递归进带 `__module__` 的公开非 callable 属性；公开 `self.window` 会把 `pywebview.api.window.evaluate_js` 泄漏给 JS。同理 API 类里不要放公开的辅助方法/公开的 `Database` 属性。

## 滚轮前端（`callname/web`）

DOM（已用真实窗口截图验证：赢家与高亮带中心偏差 0px）：

```html
<div class="reel">
  <div class="clip" id="clip">          <!-- 高度 3.6 × --item，圆角，overflow hidden -->
    <div class="band"></div>            <!-- z-index:0，居中 1 格高亮带，在条带后面 -->
    <div class="strip" id="strip"></div><!-- z-index:1，transform 动画 -->
    <div class="fade"></div>            <!-- z-index:3，上下白色渐隐，盖在条带上方 -->
  </div>
</div>
```

层次顺序是关键（三种顺序都试过并截图对比）：高亮带必须在条带**后面**（否则整条条带都变成半透明，字发灰）；渐隐必须是独立的 `.fade` 层盖在条带**上面**；不要把 `mask-image` 加在 `.clip` 上 —— 那样会连高亮带的边框一起削掉，而且 mask 会让子层创建新的合成层，动画期间更容易掉帧。

- `--item: 112px`，名字 `font-size: 62px`，字体栈 `"Microsoft YaHei UI","Noto Sans CJK SC","PingFang SC",sans-serif`。
- 渐隐用纯 CSS 渐变层（`linear-gradient` 从白到透明再回白），不逐帧算，也别用 `filter: blur()` —— QtWebEngine 里 30 个节点做模糊很贵。
- 构建条带：上方 26 个假名 + 赢家（`.cell.win`，绿色高亮 + 光晕）+ 下方 5 个假名。尾部必须有假名，否则静止时下半格是空白。
- **所有尺寸都测量得到**，不写死：`h = winnerEl.getBoundingClientRect().height`、`H = clip.clientHeight`、`winIdx = 26`、`restY = Math.round(H/2 - h/2 - winIdx*h)`（负数）。这样 125% 缩放/窗口缩放都不会偏。
- 动画：先把 `transitionDuration=0`、`transform=translate3d(0, restY + H*0.6 + h*8, 0)`（在下方）强制 reflow，再设 `transition: transform 2400–2800ms cubic-bezier(.08,.82,.06,1)` 到 `restY` —— 条带**自下而上**滚入，末尾长尾减速。用 CSS transition 而不是 rAF（合成器驱动、不漂移、自带 `transitionend`）。
- 落定后给赢家格子加一次 `pop` 缩放动画（动格子，不动条带，避免偏移）。
- 下一次抽签的"跳变"：重建条带 + 立刻 `transition:none` 归位到起点 + 强制 reflow，**全在同一个同步任务里完成**，中间帧不会渲染成静止画面；同时给容器加 120ms 的 `is-kicking` 类让内容切换看起来是"机器咬合"。
- `prefers-reduced-motion: reduce`：不滚动，直接一个格子放在高亮带中心，跳过 pop。
- 防连点：`busy = true` 写在**第一个 await 之前**（按钮 disabled 只是视觉），Python 侧锁双保险。空格/回车键触发时过滤 `e.repeat`。
- `transitionend` 过滤 `e.target === strip && e.propertyName === 'transform'`，另设 `setTimeout(dur+400)` 兜底（窗口被遮挡时 QtWebEngine 可能丢事件）。
- 全部抽完：`draw()` 自动开新一轮（HUD 显示"第 N 轮"），不会卡死；名单为空时按钮禁用、HUD 提示去 ⚙。
- 按钮：`开始点名`、`重置列表`、⚙（56px 圆形，调用 `open_manage()`）。
- HUD：`本轮剩余 X / Y · 第 N 轮`。
- 初始化：`window.addEventListener('pywebviewready', boot)`；`boot()` 里 `status()` + 摆好静止条带。
- **名单变更刷新**：`setInterval` 每 1500ms 调 `status()`（`busy` 时跳过），只有 `roster_version` 变了才重渲染 HUD 和假名池。管理窗口开着时改动也能立刻反映，不依赖它退出。

## 管理窗口（`manage.html` + `manage.js`）

- 顶部：标题 + 统计（总人数 / 启用 / 累计抽中）+ 搜索框。
- 工具条：`+ 添加`（姓名输入框 + 权重）、`导入文件…`、`快速导入`（内置名单下拉）、`删除所选`、`重置累计次数`。
- 表格列：勾选框 / 姓名（inline 编辑）/ 权重（`<input type=number min=1 max=99 step=1>`，`change` 时保存，乐观更新，失败回滚 + toast）/ 累计抽中 / 最后抽中 / 删除。
- 权重列上方一行灰色说明：**"权重只影响谁更可能先被点到；每人每轮仍恰好被点一次。"**
- 停用行 45% 透明度 + 「已停用」标签；同名添加显示黄色「已存在同名学生」提示但不阻止。
- 删除用页面内自绘弹层，不用 `confirm()`（嵌入式 WebView 的 JS 对话框不可靠）。
- 每次变更后重新 `list_people()` 渲染（52 行，无所谓性能）。
- 导入流程：`pick_import_file()` → `preview_import()` → 预览弹层显示"文件 / 格式 / 共 N 条 / 文件内重复 / 库中已存在 / 将新增"→ 选择「跳过已存在」或「覆盖权重」、`追加` 或 `替换全部名单`、默认权重 → `commit_import()`。
- `importers.py` 按扩展名分派，统一返回 `ParsedRoster(names: list[str], format: str, skipped: int)`：
  - `.yml/.yaml`：`yaml.safe_load`，接受 `list[str]` 或 `list[{name, weight}]`
  - `.txt`：每行一个名字，去掉 BOM、前导 `- `、空白
  - `.csv`：`csv.reader` 第一列，识别并跳过表头（`姓名/名字/name`）
  - `.json`：`["名字", ...]` 或 `[{"name":…,"weight":…}]`
  - `.pkl`：`pickle.load`，**只接受 `list[str]`**（类型校验，拒绝其它对象）；预览弹层注明"导入 .pkl 会执行其中的代码，请只导入自己生成的文件"
  - 文本编码阶梯 `utf-8-sig` → `gb18030`（中文 Windows 导出的文本常见 GBK）
  - 权重非法/缺失回退 1；文件内按 `name.strip()` 去重保序
- 启动方式：主窗口 ⚙ → `subprocess.Popen([sys.executable, "-m", "callname", "--manage", "--db", <DB_PATH>], cwd=ROOT, start_new_session=os.name=="posix")`；frozen 时 `[sys.executable, "--manage", "--db", …]`（两行判断，不做打包本身）。`start_new_session` 让管理窗口在主窗口关闭后仍能存活。
- 快速导入的内置名单：`callname/builtin_rosters.py` 里直接内嵌 4 份旧名单（`2/93/94/96`，共 205 个唯一名字，从 `data/yaml/*.yml` 原样搬过来），不依赖外部文件。管理窗口下拉选择 → 预览 → 提交，走同一条 `commit_import` 路径。

## 依赖与配置
`pyproject.toml`（保留用户已写的 `requires-python = ">=3.14"`；注意 PySide6 要求 `<3.16`）：

```toml
[project]
name = "callname"
version = "2.0.0"
description = "随机点名工具（Web UI + SQLite）"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
  "pywebview>=6.2,<7",
  "sqlmodel>=0.0.50",
  "pydantic>=2.14",
  "loguru>=0.7",
  "pyyaml>=6.0.3",
  "qtpy>=2.4; sys_platform == 'linux'",
  "pyside6>=6.8; sys_platform == 'linux'",
]

[project.scripts]
callname = "callname.app:main"

[dependency-groups]
dev = ["pytest>=8", "mypy>=1.13"]

[tool.mypy]
strict = true
mypy_path = "."
explicit_package_bases = true
warn_unused_ignores = true
disallow_any_explicit = false     # 非必要不用 Any；真需要时允许并加注释
disallow_untyped_defs = true
warn_return_any = true

[[tool.mypy.overrides]]
module = ["webview.*", "qtpy.*", "yaml.*", "bottle.*"]
ignore_missing_imports = true
```

- 依赖一律 `uv add`（禁止 `pip` / `uv pip`）。
- `loguru` 用于全部日志；`mypy` 与 `pytest` 放 dev 组，不进入运行时依赖。
- `sqlmodel` 会带进 `sqlalchemy`（2.1.x，有 cp314 轮子）和 `pydantic`（2.14.x + `pydantic-core` cp314 轮子）。已实测在 3.14.6 上安装并跑通。
- Windows 上解析结果（实测）只有 `pywebview / pythonnet / clr-loader / cffi / pycparser / bottle / proxy-tools / pyyaml / typing-extensions` **+ sqlmodel 链**，**不含任何 PySide6**。
- `uv sync` 生成并提交 `uv.lock`。

`.gitignore` 追加：`callname.db`、`callname.db-wal`、`callname.db-shm`。

## 提交计划（每个改动一次 commit）

1. `chore: 切换到 uv，移除旧 Qt 界面与工具` —— 删 `Ui/ tools/ tests/base64.py tests/getListFromBase64.py style.qss envernment.yml`；写 `pyproject.toml` 依赖、`.gitignore`；`uv sync` 生成 `uv.lock`。（`data/`、`names.pkl` 留到第 5 步，先把名字搬进 `builtin_rosters.py` 再删，避免中间状态丢数据。）
2. `feat(db): SQLModel 名单库（权重 + 累计次数 + 抽签日志）` —— `callname/__init__.py`、`models.py`、`paths.py`、`db.py`、`tests/conftest.py`、`tests/test_db.py`；`uv run pytest -q` 通过。
3. `feat(draw): 本轮不重复的加权抽签会话` —— `draw.py`、`tests/test_draw.py`；测试通过。
4. `feat(ui): pywebview 外壳与从下往上的滚轮界面` —— `main.py`、`app.py`、`api.py`（MainApi）、`web/index.html`、`web/style.css`、`web/reel.js`、`web/main.js`；`uv run main.py` 实测截图。
5. `feat(manage): 独立名单管理工具与导入` —— `web/manage.html`、`web/manage.js`、`importers.py`、`builtin_rosters.py`（内嵌 4 份旧名单）、`ManageApi`、`tests/test_importers.py`、`tests/test_api.py`；测试 + 实测截图；同时删 `data/`、`names.pkl`。
6. `docs: README + CLAUDE.md` —— 见下节。

## README.md 与 CLAUDE.md 内容

### README.md（面向使用者：老师/自己以后看）

```markdown
# CallName 随机点名

Web UI 桌面点名器：滚轮从下往上滚动抽签，SQLite 存名单，每人可设权重。

## 安装

    uv sync

## 运行

    uv run main.py            # 主窗口：抽签
    uv run main.py --manage   # 名单管理窗口（也可以点主窗口右下角 ⚙）

数据库 `callname.db` 生成在程序目录旁边，拷走整个目录即可换电脑。

## 用法

- 「开始点名」：滚轮从下往上转，停下的名字即本轮被点到的人。
- 抽到过的人本轮不再出现；全部抽完会自动进入下一轮。
- 「重置列表」：重新开始一轮（**不清空**数据库里的累计抽中次数）。
- ⚙：打开名单管理，可增删改名字、改权重、启用/停用、导入旧名单、清零累计次数。

## 权重是什么

**权重 = 优先级，不是频率。** 每人每轮仍然恰好被点到一次；权重只决定
「谁更可能先被点到」（权重 3 的人比权重 1 的人更早出现的概率约 3 倍）。

## 导入名单

管理窗口 → 「导入文件…」，支持 `.yml / .yaml / .txt / .csv / .json / .pkl`；
或「快速导入」内置的 4 份旧班级名单（2/93/94/96，共 205 个名字）。

`.pkl` 会执行文件中的代码，只导入自己生成的文件。

## 开发

    uv run pytest -q

- `callname/models.py` SQLModel 表定义（person / draw_log / meta）
- `callname/db.py` engine、PRAGMA、迁移、CRUD
- `callname/draw.py` 本轮会话与加权抽样
- `callname/api.py` pywebview 的 js_api 桥
- `callname/web/` 前端（原生 HTML/CSS/JS，无构建步骤）

## 历史

`doc/` 下的文档描述的是 V1 的 QML 实现，已过时，仅作存档。
```

### CLAUDE.md（面向以后接手的 AI/自己）

```markdown
# CLAUDE.md

## 项目
随机点名器（中文课堂用）。pywebview 桌面壳 + 原生 HTML/CSS/JS 前端 + SQLite（SQLModel）。
Python 3.14，uv 管理依赖。

## 常用命令
    uv sync
    uv run main.py            # 主窗口
    uv run main.py --manage   # 管理窗口
    uv run main.py --auto 3   # 自测：自动连抽 3 次（配合 xwd 截图验收）
    uv run pytest -q

## 架构要点（改代码前必读）
- **API 方法必须是普通 `def`**：pywebview 的 js_api 在独立线程执行并 `json.dumps` 返回值，
  `async def` 会直接报错；返回值不能含 Path/datetime/set。
- **SQLAlchemy `Session` 不是线程安全的**：每次调用 `with db.session() as s:` 新建。
  引擎设 `connect_args={"check_same_thread": False}`，PRAGMA 用
  `event.listens_for(engine, "connect")` 挂。
- **`draw_count` 只能原子自增**：`update(Person).values(draw_count=Person.draw_count + 1)`。
  ORM 读-改-写会静默丢更新（并发实测 133/800）。
- **SQLModel 时间戳必须 timezone-aware**：`datetime.now(timezone.utc)`，
  否则 commit 时抛 ValueError。
- **权重 = 优先级**（Plackett–Luce 无放回）。不要把它改成频率加权——会破坏「每人每轮一次」。
- **本轮已抽集合只在内存里**（`DrawSession._drawn`），不持久化；`draw_count` 才持久化。
  两者是不同概念，UI 文案不能混。
- **滚轮几何全部测量得出**（`getBoundingClientRect`），不要写死像素，否则 125% DPI 会偏。
  层级：`.band`(z0) → `.strip`(z1) → `.fade`(z3)，顺序不能换。
- **Linux 钉死 `gui="qt"`**：pywebview 在 Linux 会先试 GTK，装了 PyGObject 就会换渲染后端。
- **依赖标记**：`pyside6`/`qtpy` 仅 `sys_platform == 'linux'`。Windows 用 WebView2，
  打包时不该出现任何 Qt 包。
- 前端是 `web/` 平铺目录：pywebview 的 HTTP 根 = 传入 HTML 的所在目录，不要嵌套子目录。

## 数据
- `callname.db` 在程序目录旁，**已被 .gitignore 忽略**，不要提交。
- 表：`person`(权重/累计次数/启用)、`draw_log`(审计)、`meta`(roster_version/cycle)。
- 迁移：`PRAGMA user_version` + `MIGRATIONS` 列表，加迁移时追加函数并递增版本。

## 测试与验收
- 单测覆盖数据层、抽样语义、导入解析、API 信封。
- 端到端：`uv run main.py --auto N` + `xdotool search --name 点名` + `xwd`/`ffmpeg` 截图。
  **不要用 `xdotool click`** —— 合成鼠标事件落不到 QtWebEngine 页面里（实测无效）。

## 提交习惯
每个独立改动一个 commit（chore → db → draw → ui → manage → docs）。
```

## 验证

**每个 commit 前必跑（两条都绿才提交）**：
```bash
uv run pytest -q
uv run mypy . --explicit-package-bases
```

1. **单元测试**：`uv run pytest -q`
   - `test_db.py`：`migrate()` 幂等且 `user_version==1`；`journal_mode=='wal'`；`foreign_keys` 生效（删人级联删日志）；同名允许但返回 `DUPLICATE_NAME` 警告；权重越界被拒（`BAD_WEIGHT`）；`record_draw` 原子性（`draw_count` 与 `draw_log` 同步，8 线程 × 100 次并发后精确等于 800 —— 已用原型验证读-改-写会丢更新到 133/800，必须用 `update(...).values(draw_count=Person.draw_count+1)`）；`clear_draw_counts()` 同时清日志；`roster_version` 只在名单变更时 +1、抽签不 +1。
   - `test_draw.py`：52 人抽 52 次无重复；第 53 次 `auto_reset=True`、`cycle==2`；`reset()` 后 `remaining==total` 且 `sum(draw_count)` 不变；权重 `[1,1,1,9]` 固定 seed 跑 2 万次首位频率在 0.70–0.80（期望 0.75），且整轮每人次数恰好相等；等权重时首位频率 0.22–0.28；全 0 权重（用 `Session.exec(update(...))` 绕过 ORM 校验直接写库）不崩、退回均匀；停用者不被抽中；只剩 1 人时必中；空名单/全停用 → `EMPTY_ROSTER`。
   - `test_importers.py`：用 `tmp_path` 造 yaml（`list[str]` 与 `[{name,weight}]` 两种）、txt（UTF-8 带 BOM、GB18030 各一份）、csv（带/不带表头）、json（字符串数组与对象数组）、pkl（protocol 4 的 `list[str]`，以及一个非 list 的非法对象）、文件内重复、非法权重回退、`merge`/`replace` 两种模式。
   - `test_api.py`：直接实例化 `MainApi`/`ManageApi`（不启动窗口），跑 add→draw→status→reset→import 全流程，断言每个返回值都能 `json.dumps`，错误信封结构正确。
2. **端到端实测（本机真实 X 窗口，已验证可行）**：
   ```bash
   uv run main.py &                        # 主窗口
   xdotool search --name "点名"             # 找窗口 id
   xwd -silent -id <wid> -out /tmp/a.xwd && ffmpeg -y -loglevel error -i /tmp/a.xwd /tmp/a.png
   ```
   点 3 次「开始点名」（间隔 3.4s）各抓一帧，检查：条带向上滚动、赢家停在正中高亮带（原型实测偏差 0px，125% DPI 下仍为 0）、HUD 剩余数递减、抽完 52 人自动进入第 2 轮、重置按钮恢复满额。
   ⚠️ **本机 `xdotool click` 合成的鼠标事件落不到 QtWebEngine 的页面里**（实测点按钮无反应，窗口与 WM 均正常）。所以驱动方式用 `--auto` 测试开关：`main.py` 支持 `--auto N`，在 `webview.start()` 前起一个线程，等 `window.events.loaded` 后调 `window.evaluate_js("window.clickStart()")`，每次间隔 3.4s，最后打印 `window.__state()`；截图仍用 `xwd`。这比模拟鼠标更确定，也不影响正常启动路径。
   另用 QtWebEngine 离屏截图（`QT_QPA_PLATFORM=offscreen`）做快速像素校验，不需要窗口管理器。
3. **管理工具**：点 ⚙ → 新进程窗口出现 → 加人/改权重/停用 → 主窗口 HUD 在 1.5s 内自动刷新（无需关窗口）；`导入文件…` 选一个 yaml → 预览计数正确 → 应用后主窗口能抽到新名字。
4. **数据落盘**：`sqlite3 callname.db "select name,weight,draw_count from person limit 5"` 与界面一致；重启程序后累计次数保留、本轮已抽集合清空（`remaining` 回到满额）。

## 风险与注意

- **Linux 后端要钉死 `gui='qt'`**：`webview/guilib.py` 在 Linux 上**先试 GTK**，只有失败才退 Qt。系统若装了 PyGObject+WebKit2GTK，渲染后端会悄悄变成 WebKit，样式和 sandbox 行为都不一样。`app.py` 里 `gui = "qt" if sys.platform.startswith("linux") else None`。
- **SQLModel / Session 跨线程**：js_api 每次调用一个新线程，而 SQLAlchemy 的 `Session` **不是线程安全的**，所以每次调用 `with db.session() as s:` 新建（engine 是线程安全的、内部有连接池）。`connect_args={"check_same_thread": False}` 必须给，否则池里的连接被别的线程复用时直接报错。`PRAGMA` 用 `event.listens_for(engine, "connect")` 挂上去，保证每条新连接都设到。
- **`draw_count` 必须原子自增**：实测 8 线程 × 100 次 ORM 读-改-写只记到 133/800，静默丢更新；`update(Person).values(draw_count=Person.draw_count + 1)` 才是 800/800。管理窗口是独立进程并发写同一个库，这条不是理论风险。
- **QtWebEngine sandbox**：pywebview 只在 `arch/manjaro/nixos/rhel/pop` 上自动加 `--no-sandbox`，本机是 kali，不在列表里。若以 root 运行或在无 unprivileged userns 的容器里跑，会白屏。`app.py` 加一行 `if os.geteuid() == 0: os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")`。
- **HTTP 端口**：`http_server=True` 在 127.0.0.1 随机端口起 Bottle 服务，不写死端口；保持 `private_mode=True`（改成 False 会强制固定 42001，端口占用或开第二个实例就失败）。
- **窗口图标**：`webview.start(icon=str(ICON))`（仅 GTK/Qt 支持），Windows 的 WebView2 窗口图标由 pythonnet 侧处理，本轮不深究。
- **`.pkl` 导入 = 任意代码执行**：预览弹层必须写明"请只导入自己生成的文件"；解析器校验结果必须是 `list[str]`。
- **合成鼠标事件打不进 QtWebEngine**：验收不要依赖 `xdotool click`，用 `--auto` 开关走 `evaluate_js`（见"验证"第 2 条）。
- **管理窗口子进程用 `-m callname`**：需要 `callname/__main__.py`；`cwd=ROOT` 保证 `callname` 包可导入。
- **旧文档**：`doc/doc.md` 描述的是 QML 版本，保留但在 README 标注"历史文档"。
- **不碰打包**：不做 PyInstaller 配置/构建；`manager_command()` 里留 frozen 分支只是为将来省事，不在本次验收范围内。
