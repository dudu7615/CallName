# CLAUDE.md

## 项目

随机点名器（中文课堂用）。pywebview 桌面壳 + 原生 HTML/CSS/JS 前端 + SQLite（SQLModel）。
Python 3.14，依赖用 uv 管理。

## 硬性规则（每次都严格执行）

1. **依赖与运行一律用 `uv`**：`uv add` / `uv sync` / `uv run ...`。
2. **禁止 `pip` 和 `uv pip install`**。要加依赖就用 `uv add`（它会同时写 `pyproject.toml` 和 `uv.lock`）。
3. **日志只用 `loguru`，且用默认输出格式**：`from loguru import logger`。
   **禁止 `print()` 和 `logging` 模块**；**禁止自定义 `format=`**。
   - 应用入口配置一次：`logger.remove(); logger.add(sys.stderr, level="INFO")` —— 不传 `format`，
     保持 loguru 默认格式（`时间 | 级别 | 位置 | 消息`）。
   - 需要落文件时同样不传 `format`：`logger.add("callname.log", rotation="1 MB", retention=3)`。
   - 库代码只 `logger.debug/info/warning/error/exception(...)`，不做全局配置。
   - 用户可见的错误信息由 API 信封返回给前端，日志只做诊断，不要把日志当 UI。
4. **类型检查必须全绿**：`uv run mypy . --explicit-package-bases`（strict 模式）。
   - 所有函数签名、返回值都要有注解；`disallow_untyped_defs` 等 strict 项不得关。
   - **非必要不用 `Any`**。需要表达「任意 JSON」时用 pydantic 模型或
     `dict[str, object]` / `list[object]`，实在绕不开才 `Any` 并写注释说明原因。
   - `pyproject.toml` 里配好 `[tool.mypy] strict = true` 与
     `explicit_package_bases` / `mypy_path`，确保 `uv run mypy . --explicit-package-bases` 直接可跑。
   - 第三方库缺 stub 时用 `[[tool.mypy.overrides]]` 的 `ignore_missing_imports` 局部豁免，
     不要全局关掉 strict。
5. **所有类型结构必须用 `pydantic`**：配置、消息、API 请求/响应、抽签结果、导入预览、
   列表项、状态快照、错误信封——**所有**跨函数/跨模块/跨 pywebview 桥传递的结构都必须是
   `BaseModel`（或 SQLModel，它本身即 pydantic 模型）。
   - **不要用 `TypedDict`**，不要用 `NamedTuple`，不要在模块间传裸 `dict` / `tuple`。
   - 只有在函数内部临时用一下的局部变量可以是普通结构，但一旦要返回值或传参就建模。
   - 枚举用 `StrEnum`，可选值用 `Literal`，字段加 `Field(description=...)`。
   - 跨 pywebview 桥返回前 `model_dump(mode="json")`，保证可 `json.dumps`。
   - 前端 JS 侧的 `JSDoc` 注释应与这些模型的字段保持一致。
6. **每完成一件事提交一次 commit**：一个独立可验证的改动 = 一个 commit，
   `-m` 写清「做了什么 + 为什么」，不要 `update`、`fix` 这种空话。
   提交前必须 `uv run pytest -q` 和 `uv run mypy . --explicit-package-bases` 都通过。

## 常用命令

```bash
uv sync
uv run main.py            # 主窗口（抽签）
uv run main.py --manage   # 名单管理窗口（需管理员密码）
uv run main.py --auto 3   # 自测：自动连抽 3 次（配合 xwd 截图验收）
uv run pytest -q
uv run mypy . --explicit-package-bases
uv sync --group build && uv run pyinstaller packaging/main.spec   # 打包（仅 Windows）
```

## 架构要点（改代码前必读）

- **API 方法必须是普通 `def`**：pywebview 的 js_api 在独立线程执行并 `json.dumps` 返回值。
  `async def` 会直接报错；返回值必须先转成 pydantic 模型再 `model_dump(mode="json")`。
- **SQLAlchemy `Session` 不是线程安全的**：每次调用用 `with db.session() as s:` 新建。
  engine 设 `connect_args={"check_same_thread": False}`，PRAGMA 用
  `event.listens_for(engine, "connect")` 挂到每条新连接上。
- **`draw_count` 只能原子自增**：`update(Person).values(draw_count=Person.draw_count + 1)`。
  ORM 读-改-写会静默丢更新（并发实测只记到 133/800）。
- **SQLModel 时间戳必须 timezone-aware**：用 `datetime.now(timezone.utc)`，
  否则 `commit()` 抛 `ValueError: Datetime values must have timezone information`。
- **权重 = 优先级**（Plackett–Luce 无放回抽样）。不要改成频率加权——那会破坏
  「每人每轮恰好一次」。UI 文案必须写清这一点。
- **手动停模式**（`draw_mode=manual`，存 `meta`）：主按钮第一下抽签并启动 rAF
  匀速循环，第二下**瞬时落格**——不播补间动画、不 await，变量是 `spinning`。
  条带是假名池循环填充 `MANUAL_PATTERN * MANUAL_REPEATS` 格，赢家名字**不在条带里**，
  只在点停时写进落点格（否则转动中会泄露结果）。落点 = 严格大于当前偏移的
  最小居中位置，最多前进 1 格，所以「点停→出结果」在同一帧完成。
  改这块时注意：`strip.replaceChildren(frag)` 会清空 fragment，量格高必须从
  `strip.firstElementChild` 取，否则格高为 0、转盘根本不动（踩过一次）。
  几何仍由 `_restY()` 实测，不要写死像素。
- **本轮已抽集合只在内存里**（`DrawSession._drawn`），不持久化；`draw_count` 才持久化。
  这是两个不同概念，文案不要混。
- **设置窗口的锁是后端强制的**：`ManageApi` 未解锁时所有业务方法都返回 `LOCKED`。
  新增业务方法必须走 `self._call(...)`（默认 guard），不要自己写 try/except；
  `list_people` / `stats` / `pick_import_file` 曾经就是漏网的。密码只存 Argon2id
  哈希（`meta.admin_password`），解锁态是本进程内存，窗口关闭即失效。
  **密码写入必须走 `db.replace_admin_password(expected, new)`**：先读后写会让
  两个管理窗口互相静默覆盖；条件写失败要回 `ALREADY_CONFIGURED` /
  `PASSWORD_CONFLICT`。校验前先过 `auth._within_limits()`，因为 Argon2 会按
  哈希串里写的参数分配内存，手工改库塞进极端参数会吃光内存。
  **程序不提供重置密码入口**：只有手工删掉 `meta` 里 `admin_password` 行，
  窗口才会回到「设置密码」。这是刻意的，别为了「方便」加回 `--reset-password`。
  这是课堂防误触，不是安全边界——别在文档里把它说成权限系统。
- **滚轮几何全部测量得出**（`getBoundingClientRect`），不要写死像素，否则 125% DPI 会偏。
  层级顺序：`.band`(z-index:0) → `.strip`(z-index:1) → `.fade`(z-index:3)，不能换。
- **Linux 钉死 `gui="qt"`**：pywebview 在 Linux 会先试 GTK，装了 PyGObject 就会悄悄换后端。
- **依赖标记**：`pyside6` / `qtpy` 仅 `sys_platform == 'linux'`。Windows 走 WebView2，
  打包时不应出现任何 Qt 包。
- **`web/` 必须平铺**：pywebview 的 HTTP 根 = 传入 HTML 的所在目录，嵌套子目录会 404。
- **冻结后路径分两套**：`paths.BUNDLE`（资源，=`_internal/`）与 `paths.APP_DIR`
  （exe 所在目录，可写，`callname.db` / `callname.log` 落这里）。spec 里前端必须
  打到 `callname/web`，对不上是白屏而不是构建失败。
- **`pywebview` 在 Windows 运行期才 import `platforms.winforms`**，spec 里必须显式
  `hiddenimports`；`webview.platforms.qt` 不能列，Windows 产物里不该有 Qt。
- **字体随包分发**：`web/MapleMono-NF-CN-Regular.ttf`（OFL 1.1，许可证 `web/OFL.txt`）。
  只有 Regular 一个字重，`font-weight: 700` 不会真的加粗——强调用颜色、
  `text-shadow` 或 `-webkit-text-stroke`。改 `--item` 时不要给 `.cell` 加 padding/border：
  `reel.js` 的 `_restY` 按单元格实测高度定位，高度被撑开会让赢家偏离高亮带。

## 数据

- `callname.db` 在程序目录旁，已被 `.gitignore` 忽略，不要提交。
- 表：`person`（权重 / 累计次数 / 启用）、`draw_log`（审计）、
  `meta`（`roster_version` / `cycle` / `admin_password`）。
- 迁移：`PRAGMA user_version` + `MIGRATIONS` 列表；加迁移时追加函数并递增版本号。

## 测试与验收

- 单测覆盖数据层、抽样语义、导入解析、API 信封。
- 端到端：`uv run main.py --auto N` + `xdotool search --name 点名` + `xwd` / `ffmpeg` 截图。
  **不要用 `xdotool click`** —— 合成鼠标事件落不到 QtWebEngine 页面里（实测无效）。

## 提交习惯

一个独立改动一个 commit（chore → db → draw → ui → manage → docs），
每个 commit 前跑 `uv run pytest -q` 与 `uv run mypy . --explicit-package-bases`。
