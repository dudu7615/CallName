# 去除内置名单 + txt 分隔符与默认权重

## Context

管理窗口目前有两处不符合课堂实际使用：

1. `callname/builtin_rosters.py` 内嵌了 4 份旧班级名单（2 / 93 / 94 / 96，共 205 人），
   管理窗口里有一个「快速导入…」下拉框。老师每次用的都是自己班的名单，这份内置数据只会
   增加仓库体积、UI 杂音和维护成本（测试里还硬编码了人数）。
2. txt 导入只按换行切分，且每行权重恒为 1。实际拿到的 txt 经常是「一行多个名字、用空格或
   逗号隔开」，导入后会被当成一个超长姓名；同时导入弹层里的「默认权重」对 txt 完全失效
   （`ParsedRoster.weights` 永远非空，`import_service._apply` 的回退分支永不触发）。

目标：移除内置名单功能（仅运行时代码与 UI，磁盘上的历史数据保留），并让 txt 支持
空白 / 中英文逗号 / 顿号分隔；所有格式中「未写权重」的条目统一使用导入弹层的默认权重。

## 已确认的决策

- 清理范围：删运行时代码 + UI + 测试 + README 相关描述；保留 `data/`、`names.pkl`、
  `namelists/` 等历史归档文件，不动它们。
- txt 分隔符：`\s`（空格、制表符、换行、全角空格 U+3000）+ `,` `，` `、`。
- txt **不引入**权重语法（不做「姓名 3」这类解析）。
- 「未写权重」在所有格式（yml/yaml/json/csv/txt/pkl）中都用弹层的默认权重，不再硬编码 1。

## 改动

### Commit 1 — `refactor(import): 移除内置名单的运行时与 UI`

- 删除 `callname/builtin_rosters.py`。
- `callname/schemas.py`：删 `BuiltinRoster`（183-189）、`BuiltinRosterData`（191-195）。
- `callname/import_service.py`：删 import 里的 `BuiltinRosterData`、`preview_builtin`（42-52）、
  `commit_builtin`（88-100）及 `__all__` 中对应两项。
- `callname/api.py`：删 import 的 `BuiltinRoster` / `BuiltinRosterData`（22-23）与
  `preview_builtin`（174-177）、`commit_builtin`（196-206）、`builtin_rosters`（208-211）。
- `callname/web/manage.html`：删 `<select id="builtin">`（29-31）。
- `callname/web/manage.js`：
  - 删 `builtinEl`（20）、`loadAll()` 里的 `builtin_rosters()`（163-178）与选项填充；
  - `pendingImport` 简化为 `{ key: string, preview: ImportPreview }`；
  - `ingestLabel()` 删 `builtin:` 分支（直接用 `preview.path`）；
  - 删 `pickBuiltin()`（332-343）、`builtinEl` 监听（374）；
  - `commitImport()` 固定走 `commit_import`。
- `callname/web/manage.css`：删已无引用的 `.select`（59）。
- 测试：删 `tests/test_importers.py` 中 `builtin_rosters` import 与
  `test_builtin_roster_counts` / `test_builtin_helpers`（120-135），更新文件 docstring；
  删 `tests/test_api.py::test_manage_builtin_import`（114-128）及不再使用的 `_as_list`（若无其它引用）。
- 文档：`README.md` 删「快速导入内置 4 份名单」句（40）与文件表里
  `callname/builtin_rosters.py` 行（69）。

### Commit 2 — `feat(import): txt 支持空白、逗号与顿号分隔姓名`

`callname/importers.py`：

- 新增 `import re` 与 `TXT_SEPARATOR_RE = re.compile(r"[\s,，、]+")`。
- 重写 `_from_txt`（126-128）：逐行切 token，空 token 直接丢弃（连续分隔符不产生名字），
  纯数字 token（序号残留）丢弃；整行没有有效 token 计入 `skipped`。
  每个 token 以「未指定权重」入列（见 Commit 3 的 `None`）。
- 模块 docstring 补充 txt 分隔规则。
- `tests/test_importers.py` 新增：
  - `test_txt_space_and_comma_separators`：`"张三 李四\n王五,赵六，孙七、周八\t吴九"` →
    `names == ["张三","李四","王五","赵六","孙七","周八","吴九"]`。
  - `test_txt_fullwidth_space`：`"张三　李四"` → 两个人。
  - `test_txt_numbered_tokens`：`"1. 张三 2. 李四"` → `["张三","李四"]`，且 `skipped == 0`
    （序号残留不应被算成「文件内重复」）。
  - 既有 `test_txt_utf8_bom_and_numbering` / `test_txt_gb18030` 保持通过。
- `README.md`「导入名单」补一句分隔符说明。

### Commit 3 — `fix(import): 未写权重的条目统一使用导入弹层默认权重`

- `callname/schemas.py`：
  - `ParsedRoster.weights` 改为 `list[int | None]`，描述写明 `None = 未指定，落库时用默认权重`。
  - `ImportPreview` 新增 `unweighted: int`（未写权重的名字数）。
- `callname/importers.py`：
  - `_normalise_weight` 返回 `int | None`：缺失、非数字、越界（不在 1..99）一律 `None`。
  - `_collect` 形参改为 `list[tuple[str, int | None]]`；yml/json 中 `item.get("weight")`
    （去掉 `MIN_WEIGHT` 默认值）；csv 无权重列 → `None`，有权重列但值非法 → `None`；
    pkl / txt → `None`。
- `callname/import_service.py`：
  - `_preview` 计算 `unweighted`：`len(names) - 显式权重个数`。
  - `_apply` 显式解析：按 `len(names)` 生成对齐的 `list[int]`，
    `None` 或无对应项时填弹层 `weight`，再交给 `db.import_people(...)`（db 内的越界回退保留作兜底）。
- `callname/web/manage.js` / `manage.html`：
  - `ImportPreview` JSDoc 加 `unweighted:number`；
  - 预览事实列表加一行「未写权重」；
  - 弹层默认权重下加提示：`txt 支持空格、制表符、中英文逗号、顿号或换行分隔姓名；
    没写权重的条目使用这里的默认权重。`
- 测试更新/新增：
  - `test_yaml_list_of_objects` → `weights == [3, None]`。
  - `test_csv_with_header_and_weight` → `weights == [5, None]`（0 视为未指定）。
  - 新增 `test_txt_weights_unset`（txt 解析结果全为 `None`）。
  - `tests/test_api.py::test_manage_import_flow`：断言 `preview["data"]["unweighted"] == 2`；
    以 `weight=3` 提交后 `db.list_people()` 的权重均为 3。
- `README.md` 权重说明补「未写权重 → 默认权重」。

### 收尾

按全局规则，用户批准后把本计划复制到
`plans/feat-webui+sqlite/2-<YYYYMMDD-HHMM>-remove-builtin-and-txt-separators.md`。

## 关键边界

- `_clean_name` 在 `_collect` 中仍然生效；`_from_txt` 预过滤时也调用它判断 token 是否有效，
  保证 `"1."` 这类序号 token 不进入 `skipped`（避免「文件内重复」虚高）。
- 连续分隔符、空行、BOM、GB18030 均由现有 `_decode` / 过滤逻辑覆盖。
- 姓名中含空格会被拆开——这是分隔规则的已知取舍，已在 README 写清。
- `db.import_people` 的签名（`list[int]`）与 1..99 回退逻辑不改；`None` 的解析只发生在 service 层。

## 验证

```bash
uv run pytest -q
uv run mypy . --explicit-package-bases
uv run main.py --manage   # 确认下拉框已消失；导入含混合分隔符的 txt
```

端到端：准备

```text
张三 李四
王五，赵六、孙七
```

预览应显示 7 人、未写权重 7；默认权重填 3 后确认导入，名单权重应全为 3。
再导入一份 yml（部分条目带 `weight: 5`），确认带权重的保持 5、未写的取弹层默认值。
