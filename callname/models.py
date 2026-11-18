"""SQLModel 表定义：person / draw_log / meta。"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel
from sqlalchemy import CheckConstraint


def _utcnow() -> datetime:
    """SQLModel 要求 timezone-aware 时间戳，naive 会在 commit 时抛 ValueError。"""
    return datetime.now(timezone.utc)


class Person(SQLModel, table=True):
    """名单中的一个人。身份是 id，不是 name（真实班级允许同名）。"""

    __tablename__ = "person"
    __table_args__ = (
        CheckConstraint("weight BETWEEN 1 AND 99", name="ck_person_weight"),
        CheckConstraint("active IN (0,1)", name="ck_person_active"),
        CheckConstraint("draw_count >= 0", name="ck_person_draw_count"),
        CheckConstraint("length(trim(name)) > 0", name="ck_person_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1)
    # 权重 = 优先级（Plackett–Luce 无放回抽样），不是出现频率。
    weight: int = Field(default=1, ge=1, le=99)
    active: bool = Field(default=True)
    # 累计抽中次数，持久化；与本轮内存里的「已抽集合」是两个概念。
    draw_count: int = Field(default=0, ge=0)
    sort_order: int = Field(default=0)
    last_drawn_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class DrawLog(SQLModel, table=True):
    """抽签审计日志，可用来重建 person.draw_count。"""

    __tablename__ = "draw_log"

    id: int | None = Field(default=None, primary_key=True)
    person_id: int = Field(foreign_key="person.id", ondelete="CASCADE")
    name_snapshot: str
    weight_snapshot: int
    cycle: int
    drawn_at: datetime = Field(default_factory=_utcnow)


class Meta(SQLModel, table=True):
    """键值元数据：roster_version / cycle。"""

    __tablename__ = "meta"

    key: str = Field(primary_key=True)
    value: str
