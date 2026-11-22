"""跨模块 / 跨 pywebview 桥的 pydantic 结构。

规则（CLAUDE.md）：不使用 TypedDict / NamedTuple，不传裸 dict；
枚举用 StrEnum，可选值用 Literal；过桥前 model_dump(mode="json")。
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    """统一错误信封。code 是稳定 ASCII 键，message 是直接展示的中文。"""

    code: str = Field(description="稳定 ASCII 错误码，测试与前端分支使用")
    message: str = Field(description="面向用户的中文提示")


class ApiResponse[T](BaseModel):
    """所有 js_api 方法的统一返回信封。"""

    ok: bool = Field(description="是否成功")
    data: T | None = Field(default=None, description="成功时的负载")
    error: ApiError | None = Field(default=None, description="失败时的错误")


def ok[T](data: T) -> ApiResponse[T]:
    """构造成功信封。"""
    return ApiResponse[T](ok=True, data=data)


def fail[T](code: str, message: str) -> ApiResponse[T]:
    """构造失败信封。"""
    return ApiResponse[T](ok=False, error=ApiError(code=code, message=message))


class StatusResult(BaseModel):
    """主窗口状态快照。"""

    total: int = Field(description="名单总人数（含停用）")
    active: int = Field(description="启用人数")
    remaining: int = Field(description="本轮还剩多少人没抽")
    drawn: int = Field(description="本轮已抽人数")
    cycle: int = Field(description="当前轮次，从 1 开始")
    roster_version: int = Field(description="名单版本号，每次名单变更 +1")
    names: list[str] = Field(default_factory=list, description="启用者的名字，前端造假名用")


class DrawResult(BaseModel):
    """一次抽签的结果。"""

    id: int = Field(description="被抽中者的 person.id")
    name: str = Field(description="被抽中者的名字")
    weight: int = Field(description="被抽中者的权重")
    decoys: list[str] = Field(default_factory=list, description="滚轮上方/下方的假名")
    total: int = Field(description="名单总人数")
    remaining: int = Field(description="本次抽完后本轮还剩多少人")
    cycle: int = Field(description="本次抽签所属轮次")
    auto_reset: bool = Field(default=False, description="是否因抽完而自动开启了新一轮")
    roster_version: int = Field(description="名单版本号")


class PersonItem(BaseModel):
    """管理窗口的一行。"""

    id: int = Field(description="person.id")
    name: str = Field(description="姓名")
    weight: int = Field(description="权重 = 优先级")
    active: bool = Field(description="是否参与抽签")
    draw_count: int = Field(description="累计抽中次数")
    sort_order: int = Field(description="排序键")
    last_drawn_at: datetime | None = Field(
        default=None, description="最后一次抽中时间（UTC）"
    )


class PersonPatch(BaseModel):
    """管理窗口的可选更新字段；None 表示不修改。"""

    name: str | None = Field(default=None, description="新姓名")
    weight: int | None = Field(default=None, description="新权重")
    active: bool | None = Field(default=None, description="新启用状态")


class AddPersonResult(BaseModel):
    """添加人员的结果，同名不阻止但给出警告。"""

    person: PersonItem = Field(description="新建的人员")
    warning: Literal["DUPLICATE_NAME"] | None = Field(
        default=None, description="同名警告；仍会创建"
    )


class StatsResult(BaseModel):
    """管理窗口顶部的统计。"""

    total: int = Field(description="总人数")
    active: int = Field(description="启用人数")
    sum_draws: int = Field(description="累计抽中次数之和")
    last_draw_at: datetime | None = Field(
        default=None, description="最近一次抽签时间（UTC）"
    )


class ImportFormat(StrEnum):
    """支持的名单文件格式。"""

    YAML = "yaml"
    TXT = "txt"
    CSV = "csv"
    JSON = "json"
    PKL = "pkl"


class ParsedRoster(BaseModel):
    """解析后的名单，内部结构，也可直接序列化给前端。"""

    names: list[str] = Field(description="去重保序后的名字")
    weights: list[int | None] = Field(
        default_factory=list,
        description="与 names 对齐的权重；None = 文件未指定，落库时用导入弹层的默认权重",
    )
    format: ImportFormat = Field(description="来源格式")
    skipped: int = Field(default=0, description="解析时跳过的行数（空行/表头等）")


class ImportPreview(BaseModel):
    """导入前的预览，不落库。"""

    path: str = Field(description="文件绝对路径")
    format: ImportFormat = Field(description="来源格式")
    count: int = Field(description="文件中的有效名字数")
    file_dups: int = Field(description="文件内部重复被去掉的数量")
    db_dups: int = Field(description="库中已存在同名的数量")
    unweighted: int = Field(
        default=0, description="文件未写权重、将使用默认权重的名字数"
    )
    names: list[str] = Field(default_factory=list, description="待导入的名字（已去重）")


class ImportMode(StrEnum):
    """导入模式。"""

    MERGE = "merge"
    REPLACE = "replace"


class ImportResult(BaseModel):
    """导入落库后的结果。"""

    added: int = Field(description="新增人数")
    updated: int = Field(description="更新权重的人数")
    skipped: int = Field(description="因重复被跳过的人数")


class DeleteOneResult(BaseModel):
    """删除单人的结果。"""

    deleted: bool = Field(description="是否真的删除了（False = 本来就不存在）")


class FilePickResult(BaseModel):
    """文件选择框结果；path 为 None 表示用户取消。"""

    path: str | None = Field(default=None, description="选中的文件绝对路径")


class LaunchResult(BaseModel):
    """启动管理窗口的结果。"""

    launched: bool = Field(description="是否已启动")
    already_running: bool = Field(description="是否复用了已在运行的实例")


class DeleteManyResult(BaseModel):
    """批量删除结果。"""

    deleted: int = Field(description="实际删除的行数")


class ClearCountsResult(BaseModel):
    """清零累计次数的结果。"""

    people: int = Field(description="被清零的人数")


class AuthState(BaseModel):
    """设置窗口的锁状态；前端据此决定显示「设置密码」还是「解锁」。"""

    configured: bool = Field(description="是否已经设置过管理员密码")
    unlocked: bool = Field(description="当前进程是否已解锁")



