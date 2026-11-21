"""数据库：engine、PRAGMA、迁移与 CRUD（全部走 SQLModel）。

线程模型：SQLAlchemy 的 Session 不是线程安全的，而 pywebview 的每个 js_api
调用都在独立线程里执行，所以每次调用都用 `with db.session() as s:` 新建。
engine 本身是线程安全的，连接池会把连接借给任意线程，因此必须设置
`check_same_thread=False`，PRAGMA 则挂在每条新连接的 connect 事件上。
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.engine import Connection, Engine, create_engine
from sqlmodel import Session, SQLModel, col

from callname.models import DrawLog, Meta, Person
from callname.paths import DB_PATH
from callname.schemas import (
    AddPersonResult,
    ClearCountsResult,
    DeleteManyResult,
    ImportMode,
    ImportResult,
    PersonItem,
    PersonPatch,
    StatsResult,
)

META_ROSTER_VERSION = "roster_version"
META_CYCLE = "cycle"
META_ADMIN_PASSWORD = "admin_password"


class DbError(Exception):
    """可直接映射成 ApiError 的领域错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
    """每条新连接都要设，否则池里换一条连接就丢 PRAGMA。"""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _v1_create_all(conn: Connection) -> None:
    """v1：建表。create_all 本身幂等。"""
    SQLModel.metadata.create_all(conn)


MIGRATIONS: list[Callable[[Connection], None]] = [_v1_create_all]


def _to_item(person: Person) -> PersonItem:
    return PersonItem(
        id=person.id or 0,
        name=person.name,
        weight=person.weight,
        active=person.active,
        draw_count=person.draw_count,
        sort_order=person.sort_order,
        last_drawn_at=person.last_drawn_at,
    )


def _valid_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise DbError("BAD_NAME", "姓名不能为空")
    return cleaned


def _valid_weight(weight: int) -> int:
    if not 1 <= weight <= 99:
        raise DbError("BAD_WEIGHT", "权重必须在 1 到 99 之间")
    return weight


class Database:
    """SQLite 数据库门面。所有写操作在本进程内由一把 RLock 串行化。"""

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False, "timeout": 5},
            pool_pre_ping=True,
        )
        event.listen(self.engine, "connect", _set_pragmas)
        self._lock = threading.RLock()

    # -- 生命周期 ---------------------------------------------------------
    def migrate(self) -> None:
        """按 PRAGMA user_version 递增迁移，幂等。"""
        with self.engine.begin() as conn:
            current = int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)
            target = len(MIGRATIONS)
            if current >= target:
                logger.debug("db schema up to date: version={}", current)
                return
            for version in range(current, target):
                logger.info("migrating db to version {}", version + 1)
                MIGRATIONS[version](conn)
            conn.exec_driver_sql(f"PRAGMA user_version = {target}")

    def close(self) -> None:
        self.engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """成功提交，异常回滚。"""
        with self._lock, Session(self.engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    # -- 读取 -------------------------------------------------------------
    def active_people(self) -> list[Person]:
        """启用的人，按 sort_order, id 排序；抽签逻辑用。"""
        with self.session() as session:
            statement = (
                select(Person)
                .where(col(Person.active) == True)  # noqa: E712 - SQL 表达式
                .order_by(col(Person.sort_order), col(Person.id))
            )
            return list(session.scalars(statement).all())

    def list_people(self, query: str = "") -> list[PersonItem]:
        """全部人员（含停用），按累计抽中次数降序。"""
        with self.session() as session:
            statement = select(Person)
            needle = query.strip()
            if needle:
                statement = statement.where(col(Person.name).contains(needle))
            statement = statement.order_by(
                col(Person.draw_count).desc(),
                col(Person.sort_order),
                col(Person.id),
            )
            return [_to_item(person) for person in session.scalars(statement).all()]

    def get_person(self, pid: int) -> PersonItem | None:
        with self.session() as session:
            person = session.get(Person, pid)
            return _to_item(person) if person is not None else None

    def duplicate_names(self, names: list[str]) -> set[str]:
        """返回 names 中已存在于数据库的名字（导入预览用）。"""
        if not names:
            return set()
        with self.session() as session:
            statement = select(col(Person.name)).where(col(Person.name).in_(names))
            return set(session.scalars(statement).all())

    def stats(self) -> StatsResult:
        with self.session() as session:
            people = list(session.scalars(select(Person)).all())
            last = session.scalar(
                select(col(DrawLog.drawn_at))
                .order_by(col(DrawLog.drawn_at).desc())
                .limit(1)
            )
        return StatsResult(
            total=len(people),
            active=sum(1 for person in people if person.active),
            sum_draws=sum(person.draw_count for person in people),
            last_draw_at=last,
        )

    # -- meta -------------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        with self.session() as session:
            row = session.get(Meta, key)
            return row.value if row is not None else default

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as session:
            row = session.get(Meta, key)
            if row is None:
                session.add(Meta(key=key, value=value))
            else:
                row.value = value
                session.add(row)

    def get_cycle(self) -> int:
        return int(self.get_meta(META_CYCLE, "1"))

    def bump_cycle(self) -> int:
        with self.transaction() as session:
            row = session.get(Meta, META_CYCLE)
            value = int(row.value) + 1 if row is not None else 2
            if row is None:
                session.add(Meta(key=META_CYCLE, value=str(value)))
            else:
                row.value = str(value)
                session.add(row)
            return value

    def get_roster_version(self) -> int:
        return int(self.get_meta(META_ROSTER_VERSION, "0"))

    # -- 管理员密码 -------------------------------------------------------
    def get_admin_password_hash(self) -> str:
        """空串表示尚未设置密码（首次打开设置窗口时要求设置）。"""
        return self.get_meta(META_ADMIN_PASSWORD, "")

    def set_admin_password_hash(self, value: str) -> None:
        self.set_meta(META_ADMIN_PASSWORD, value)

    def clear_admin_password(self) -> None:
        """找回：清掉哈希后，下次打开设置窗口回到「设置密码」。"""
        self.set_meta(META_ADMIN_PASSWORD, "")

    def bump_roster_version(self) -> int:
        with self.transaction() as session:
            return self._bump_roster_version(session)

    @staticmethod
    def _next_sort_order(session: Session) -> int:
        current = session.scalar(select(func.max(col(Person.sort_order))))
        return int(current) + 1 if current is not None else 0

    def _bump_roster_version(self, session: Session) -> int:
        row = session.get(Meta, META_ROSTER_VERSION)
        value = int(row.value) + 1 if row is not None else 1
        if row is None:
            session.add(Meta(key=META_ROSTER_VERSION, value=str(value)))
        else:
            row.value = str(value)
            session.add(row)
        return value

    # -- 写 ---------------------------------------------------------------
    def add_person(self, name: str, weight: int = 1) -> AddPersonResult:
        cleaned = _valid_name(name)
        _valid_weight(weight)
        with self.transaction() as session:
            duplicate = session.scalar(
                select(Person).where(col(Person.name) == cleaned).limit(1)
            )
            sort_order = self._next_sort_order(session)
            person = Person(name=cleaned, weight=weight, sort_order=sort_order)
            session.add(person)
            session.flush()
            self._bump_roster_version(session)
            return AddPersonResult(
                person=_to_item(person),
                warning="DUPLICATE_NAME" if duplicate is not None else None,
            )

    def update_person(self, pid: int, patch: PersonPatch) -> PersonItem:
        with self.transaction() as session:
            person = session.get(Person, pid)
            if person is None:
                raise DbError("NOT_FOUND", "找不到这个人")
            if patch.name is not None:
                person.name = _valid_name(patch.name)
            if patch.weight is not None:
                person.weight = _valid_weight(patch.weight)
            if patch.active is not None:
                person.active = patch.active
            session.add(person)
            self._bump_roster_version(session)
            session.flush()
            return _to_item(person)

    def set_active(self, pid: int, active: bool) -> PersonItem:
        return self.update_person(pid, PersonPatch(active=active))

    def delete_person(self, pid: int) -> bool:
        with self.transaction() as session:
            person = session.get(Person, pid)
            if person is None:
                return False
            session.delete(person)
            self._bump_roster_version(session)
            return True

    def delete_many(self, ids: list[int]) -> DeleteManyResult:
        if not ids:
            return DeleteManyResult(deleted=0)
        with self.transaction() as session:
            result = session.execute(delete(Person).where(col(Person.id).in_(ids)))
            deleted = int(getattr(result, "rowcount", 0) or 0)
            if deleted:
                self._bump_roster_version(session)
            return DeleteManyResult(deleted=deleted)

    def record_draw(
        self, person_id: int, name: str, weight: int, cycle: int
    ) -> None:
        """一次抽签：原子自增 draw_count + 写审计日志。

        必须用 `draw_count = draw_count + 1` 的 UPDATE；ORM 读-改-写在并发
        下会静默丢更新（实测 8 线程 800 次只记到 133 次）。
        """
        with self.transaction() as session:
            session.execute(
                update(Person)
                .where(col(Person.id) == person_id)
                .values(
                    draw_count=col(Person.draw_count) + 1,
                    last_drawn_at=_utcnow(),
                )
            )
            session.add(
                DrawLog(
                    person_id=person_id,
                    name_snapshot=name,
                    weight_snapshot=weight,
                    cycle=cycle,
                )
            )

    def clear_draw_counts(self) -> ClearCountsResult:
        with self.transaction() as session:
            people = session.scalars(select(Person)).all()
            session.execute(update(Person).values(draw_count=0, last_drawn_at=None))
            session.execute(delete(DrawLog))
            self._bump_roster_version(session)
            return ClearCountsResult(people=len(people))

    def import_people(
        self,
        names: list[str],
        weights: list[int],
        mode: ImportMode,
        weight_default: int = 1,
        dedupe: bool = True,
    ) -> ImportResult:
        """导入名单；merge 追加，replace 先清空。"""
        if mode not in (ImportMode.MERGE, ImportMode.REPLACE):
            raise DbError("BAD_MODE", "导入模式只能是 merge 或 replace")
        fallback = _valid_weight(weight_default)
        cleaned: list[tuple[str, int]] = []
        for index, raw in enumerate(names):
            name = raw.strip()
            if not name:
                continue
            raw_weight = weights[index] if index < len(weights) else fallback
            weight = raw_weight if 1 <= raw_weight <= 99 else fallback
            cleaned.append((name, weight))

        with self.transaction() as session:
            if mode is ImportMode.REPLACE:
                session.execute(delete(Person))
                existing: dict[str, Person] = {}
            else:
                existing = {
                    person.name: person
                    for person in session.scalars(select(Person)).all()
                }

            sort_order = self._next_sort_order(session)
            added = 0
            updated = 0
            skipped = 0
            for name, weight in cleaned:
                person = existing.get(name)
                if person is not None:
                    if dedupe:
                        skipped += 1
                        continue
                    person.weight = weight
                    session.add(person)
                    updated += 1
                    continue
                session.add(
                    Person(name=name, weight=weight, sort_order=sort_order)
                )
                sort_order += 1
                added += 1
            self._bump_roster_version(session)
            return ImportResult(added=added, updated=updated, skipped=skipped)


__all__ = ["Database", "DbError", "MIGRATIONS"]
