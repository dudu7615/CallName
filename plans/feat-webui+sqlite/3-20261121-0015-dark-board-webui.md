# 重做 WebUI：深色电子看板

## Context

主窗口与管理窗口现在的视觉是「浅绿渐变 + 白卡片」，能用但不像一块课堂用的电子看板：
背景渐变与白色滚轮对比弱、按钮层级不清、管理窗口是新拟物白底表格，两窗口观感也不统一。
用户要求把它做好看，并指定用本机的 `MapleMono-NF-CN-Regular.ttf` 作为字体。

目标：主窗口与管理窗口统一成一套**深色电子看板**设计（深靛底、暖白字、琥珀金高亮），
字体走内置 Maple Mono，且**不改动任何后端 / API / schema**。所有既有交互
（滚轮自下而上、空格抽签、`--auto` 自测、导入弹层）行为不变。

## 已确认的决策

- 视觉方向：深色电子看板（用户已选）。
- 字体：内置 Maple Mono NF CN，等宽字形承载姓名与数字（中文覆盖 20,976 字，已核对本班 117 个用字全覆盖）。
- 打包方式（用户已选）：**原样 20 MB TTF**，不做子集化、不改名，随包附上游 OFL 许可证全文。
- 不改 API：`status / draw / reset / open_manage` 与全部 manage 接口保持原样。
  HUD 进度条直接复用 `StatusResult.drawn / active / remaining`，无需新字段。
- `callname/web/` 保持平铺（CLAUDE.md 硬性要求），字体文件直接放 `callname/web/` 下。
- 不使用任何构建步骤：纯 HTML/CSS/JS，`@font-face` 直接吃仓库里的字体文件。

## 实测结论（已在本机验证，不用再试）

- QtWebEngine 140（PySide6 6.12）能正常加载 woff2 与 ttf；20 MB TTF 首次加载约 **124 ms**。
- 单字重字体下 `font-weight: 700` 几乎不加粗；强调要用 `-webkit-text-stroke` 或颜色/发光，不能靠 bold。
- `xdotool click` 落不到 QtWebEngine 页面，验收只能 `evaluate_js` + `xwd` 截图。
- pywebview 的 bottle server 现在能取到子目录，但仍按约定保持 `web/` 平铺。

## 设计规格

### 设计令牌（`style.css` 顶部 `:root`）

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--bg` / `--bg-deep` | `#070d18` / `#04080f` | 舞台底色 / 暗角 |
| `--panel` | `#0d1726` | 滚轮与表格容器 |
| `--line` | `rgba(150,183,222,.16)` | 一像素分隔线 |
| `--ink` | `#f2e7d5` | 主字（暖白） |
| `--ink-soft` | `#8ea1ba` | 次要信息 |
| `--gold` / `--gold-soft` | `#ffc24b` / `rgba(255,194,75,.16)` | 赢家、主按钮、进度条 |
| `--danger` | `#ff7a6b` | 危险操作 |
| `--radius` | `16px` / `999px` | 面板 / 胶囊按钮 |

字体栈统一 `'MapleMono NF CN', 'Noto Sans Mono CJK SC', monospace`。

### 主窗口

- 背景：深靛底 + 细网格（`repeating-linear-gradient`，2% 透明度）+ 径向暗角，模拟看板背板。
- HUD：左侧「第 N 轮」大号数字标签；中间一条细进度条（`drawn / active`，金色填充，带 1 帧过渡）；
  右侧「剩余 R / A」等宽数字。整条 HUD 用 `--line` 与主体隔开。
- 滚轮：深色面板 + 1px 描边 + 内阴影；中央高亮带改为金色上下双线 + 径向暖光；
  `.fade` 渐变从白改为 `--panel`（层级 band(0) → strip(1) → fade(3) 顺序不变）。
- `.cell` 字号 62 → 72px；`.cell.win` 用金色 + 轻微 `-webkit-text-stroke` + 发光，并保留 `pop` 动画。
- 按钮：主按钮金色实心（深色字）、次要按钮描边、⚙ 图标按钮方形圆角；
  主按钮右侧加 `空格` 键提示（`<kbd>`）。
- Toast 改为底部状态条（左侧状态点），不与按钮争视觉。

### 管理窗口

- 顶栏：标题 + 「总人数 / 启用 / 累计」三块等宽统计数字（替换现在的一句话）。
- 工具条：搜索框带放大镜前缀；新增区做成一组「姓名 + 权重 + 添加」；导入/删除/清零放右侧。
- 表格：深色行、1px `--line` 分隔、表头 sticky 且带背景；hover 行淡金底；
  启用状态改成小型开关（`button` + `aria-pressed`），停用行整体降透明度。
- 弹层：深色卡片 + 毛玻璃背景；导入选项由裸 radio 改成整块可点的选项卡。
- **Toast 修复**：现在 `toast()` 直接改 `#stats` 的文本（`manage.js:43-50`），
  改成页面里独立的 `#toast` 元素（与主窗口同一套样式）。

## 改动

### Commit 1 — `feat(ui): 内置 Maple Mono 字体并建立深色设计令牌`

- 新增 `callname/web/MapleMono-NF-CN-Regular.ttf`（从 `~/.fonts/` 原样复制，**不做子集化/改名**，
  规避 OFL 保留字体名条款）与 `callname/web/OFL.txt`（上游许可证全文）。
- 仓库体积会因此增加约 20 MB，属于用户已确认的取舍；`.gitignore` 不放行任何压缩包，字体文件直接入库。
- `callname/web/style.css`：`@font-face` + 上表设计令牌 + 基础排版/按钮/Toast/弹层骨架。
- `callname/app.py`：两个 `create_window` 加 `background_color="#070d18"`，消除启动白闪。

### Commit 2 — `feat(ui): 主窗口改为深色电子看板`

- `callname/web/index.html`：HUD 拆成「轮次 / 进度条 / 剩余」，按钮区加 `空格` 提示，加状态点。
- `callname/web/style.css`：看板背景、滚轮面板与高亮带、赢家样式、按钮态。
- `callname/web/main.js`：HUD 渲染改为「轮次 + 进度条宽度 + 剩余」三段；其余逻辑（`busy`、
  轮询、`window.clickStart`、`window.__state`）**一字不改**，保证 `--auto` 自测继续可用。
- `callname/web/reel.js`：只允许改字体相关，不改 `ABOVE/BELOW`、`_restY` 与过渡曲线。

### Commit 3 — `feat(manage): 名单管理窗口改为深色看板`

- `callname/web/manage.html`：统计三块、独立 `#toast`、导入选项卡结构。
- `callname/web/manage.css`：表格/工具条/弹层深色化。
- `callname/web/manage.js`：`toast()` 改写到独立元素；启用状态改成 `aria-pressed` 开关；
  `loadAll()` 仍全量重渲染（几十行，不做增量）。

### Commit 4 — `docs: 更新 README 与前端说明`

- README 补一句「界面使用内置 Maple Mono 字体，LICENSE 见 `callname/web/OFL.txt`」，
  并把文件表里 `callname/web/` 一行补上「字体」。

## 不做的事

- 不引入 JS 框架、构建链、CSS 预处理器。
- 不改滚轮几何算法（测量式 `_restY`），不改抽样语义与文案含义。
- 不加新 API / 新 schema 字段；HUD 只用现有 `StatusResult`。

## 验证

```bash
uv run pytest -q
uv run mypy . --explicit-package-bases
```

界面验收（本机 X11）：

1. `uv run main.py` → `xdotool search --name "^点名$"` → `xwd` 截图：确认深色看板、字体已生效
   （截图中字母/数字应为等宽字形）、中央高亮带与赢家样式。
2. `uv run main.py --auto 2` → 抽签结束后截图：确认赢家仍精确停在中央高亮带
   （几何没被新样式破坏），并检查日志里 `auto final state`。
3. `uv run main.py --manage` → 截图：表格可读性、开关、深色弹层（点「导入文件…」触发一次预览）。
4. 125% DPI 复核：`QT_SCALE_FACTOR=1.25 uv run main.py` 再截一次，确认赢家不偏离高亮带。
5. 键盘：空格连续抽 3 次不卡；抽完一轮自动进下一轮时进度条与「第 N 轮」同步。
