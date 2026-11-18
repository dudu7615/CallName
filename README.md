# CallName 随机点名

Web UI 桌面点名器：滚轮从下往上滚动抽签，SQLite 存名单，每人可设权重。

## 安装

```bash
uv sync
```

> 本项目**只用 `uv`** 管理依赖和运行脚本。不要用 `pip`，也不要用 `uv pip install`。

## 运行

```bash
uv run main.py            # 主窗口：抽签
uv run main.py --manage   # 名单管理窗口（也可以点主窗口右下角 ⚙）
```

数据库 `callname.db` 生成在程序目录旁边，拷走整个目录即可换电脑。

## 用法

- **开始点名**：滚轮从下往上转，停在中间高亮带的名字就是本轮被点到的人。
- 抽到过的人本轮不再出现；全部抽完会自动进入下一轮（HUD 显示「第 N 轮」）。
- **重置列表**：重新开始一轮（**不清空**数据库里的累计抽中次数）。
- **⚙**：打开名单管理，可增删改名字、改权重、启用/停用、导入旧名单、清零累计次数。

## 权重是什么

**权重 = 优先级，不是频率。**

每人每轮仍然恰好被点到一次；权重只决定「谁更可能先被点到」——
权重 3 的人比权重 1 的人更早出现的概率约 3 倍，但一轮下来两人的次数一样。

## 导入名单

管理窗口 →「导入文件…」，支持 `.yml` / `.yaml` / `.txt` / `.csv` / `.json` / `.pkl`。

也可以「快速导入」内置的 4 份旧班级名单（2 / 93 / 94 / 96，共 205 个名字）。

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
| `callname/draw.py` | 本轮会话与加权抽样 |
| `callname/importers.py` | 名单解析（yml/txt/csv/json/pkl） |
| `callname/import_service.py` | 导入预览与落库编排 |
| `callname/builtin_rosters.py` | 内嵌的 4 份旧班级名单 |
| `callname/api.py` | pywebview 的 js_api 桥 |
| `callname/app.py` | 启动参数与窗口 |
| `callname/web/` | 前端（原生 HTML/CSS/JS，无构建步骤） |

## 历史

`doc/` 下的文档描述的是 V1 的 QML 实现，已过时，仅作存档。

`1-webui-2-sqlite-memoized-eagle.md` 是 V2 的设计与实测记录。
