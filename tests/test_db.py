"""数据层测试：迁移、PRAGMA、约束、原子计数、导入。"""

import threading
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from callname.db import META_ADMIN_PASSWORD, Database, DbError
from callname.models import DrawLog, Meta, Person
from callname.schemas import ImportMode, PersonPatch


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "m.db"
    database = Database(path)
    database.migrate()
    database.migrate()
    with database.engine.connect() as conn:
        version = conn.exec_driver_sql("PRAGMA user_version").scalar()
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert version == 1
    assert str(mode).lower() == "wal"


def test_foreign_keys_cascade(db: Database) -> None:
    person = db.add_person("张三", 1).person
    assert person.id is not None
    db.record_draw(person.id, "张三", 1, 1)
    with db.session() as session:
        assert len(session.scalars(select(DrawLog)).all()) == 1
    assert db.delete_person(person.id) is True
    with db.session() as session:
        assert session.scalars(select(DrawLog)).all() == []


def test_duplicate_name_warns_but_inserts(db: Database) -> None:
    first = db.add_person("李四", 1)
    second = db.add_person("李四", 2)
    assert first.warning is None
    assert second.warning == "DUPLICATE_NAME"
    assert len(db.list_people()) == 2


def test_bad_weight_rejected(db: Database) -> None:
    with pytest.raises(DbError) as info:
        db.add_person("王五", 0)
    assert info.value.code == "BAD_WEIGHT"
    with pytest.raises(DbError) as info2:
        db.update_person(1, PersonPatch(weight=100))
    assert info2.value.code in {"BAD_WEIGHT", "NOT_FOUND"}


def test_empty_name_rejected(db: Database) -> None:
    with pytest.raises(DbError) as info:
        db.add_person("   ", 1)
    assert info.value.code == "BAD_NAME"


def test_record_draw_is_atomic(db: Database) -> None:
    person = db.add_person("并发", 1).person
    assert person.id is not None
    pid = person.id
    workers = 8
    per_worker = 100

    def work() -> None:
        for _ in range(per_worker):
            db.record_draw(pid, "并发", 1, 1)

    threads = [threading.Thread(target=work) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    refreshed = db.get_person(pid)
    assert refreshed is not None
    assert refreshed.draw_count == workers * per_worker
    with db.session() as session:
        assert len(session.scalars(select(DrawLog)).all()) == workers * per_worker


def test_clear_draw_counts_clears_logs(db: Database) -> None:
    person = db.add_person("清零", 1).person
    assert person.id is not None
    db.record_draw(person.id, "清零", 1, 1)
    result = db.clear_draw_counts()
    assert result.people == 1
    refreshed = db.get_person(person.id)
    assert refreshed is not None
    assert refreshed.draw_count == 0
    assert refreshed.last_drawn_at is None
    with db.session() as session:
        assert session.scalars(select(DrawLog)).all() == []


def test_roster_version_only_bumps_on_roster_changes(db: Database) -> None:
    assert db.get_roster_version() == 0
    person = db.add_person("版本", 1).person
    assert db.get_roster_version() == 1
    assert person.id is not None
    db.record_draw(person.id, "版本", 1, 1)
    assert db.get_roster_version() == 1, "抽签不应改变名单版本"
    db.update_person(person.id, PersonPatch(weight=5))
    assert db.get_roster_version() == 2
    db.set_active(person.id, False)
    assert db.get_roster_version() == 3
    db.delete_person(person.id)
    assert db.get_roster_version() == 4


def test_delete_many(db: Database) -> None:
    ids = [db.add_person(f"人{index}", 1).person.id for index in range(3)]
    valid = [pid for pid in ids if pid is not None]
    result = db.delete_many(valid[:2])
    assert result.deleted == 2
    assert len(db.list_people()) == 1


def test_list_people_search_and_order(db: Database) -> None:
    for index in range(3):
        db.add_person(f"甲{index}", 1)
    person = db.add_person("乙", 1).person
    assert person.id is not None
    db.record_draw(person.id, "乙", 1, 1)
    listed = db.list_people()
    assert listed[0].name == "乙", "按累计抽中次数降序"
    assert [item.name for item in db.list_people("甲")] == ["甲0", "甲1", "甲2"]


def test_import_merge_dedupes(db: Database) -> None:
    db.add_person("已存在", 1)
    result = db.import_people(
        ["已存在", "新人"], [3, 2], ImportMode.MERGE, 1, True
    )
    assert (result.added, result.updated, result.skipped) == (1, 0, 1)
    people = {item.name: item.weight for item in db.list_people()}
    assert people["新人"] == 2
    assert people["已存在"] == 1, "去重模式下不覆盖已有权重"


def test_import_merge_overwrite_weight(db: Database) -> None:
    db.add_person("已存在", 1)
    result = db.import_people(
        ["已存在"], [9], ImportMode.MERGE, 1, False
    )
    assert result.updated == 1
    assert db.list_people()[0].weight == 9


def test_import_replace_wipes_roster(db: Database) -> None:
    old = db.add_person("旧人", 1).person
    assert old.id is not None
    db.record_draw(old.id, "旧人", 1, 1)
    result = db.import_people(["新人"], [1], ImportMode.REPLACE, 1, True)
    assert result.added == 1
    assert [item.name for item in db.list_people()] == ["新人"]
    with db.session() as session:
        assert session.scalars(select(DrawLog)).all() == []


def test_import_preserves_file_order(db: Database) -> None:
    db.import_people(["丙", "甲", "乙"], [1, 1, 1], ImportMode.MERGE, 1, True)
    assert [item.sort_order for item in db.list_people()] == [0, 1, 2]


def test_bad_weight_falls_back_in_import(db: Database) -> None:
    db.import_people(["甲", "乙"], [0, 500], ImportMode.MERGE, 7, True)
    weights = {item.name: item.weight for item in db.list_people()}
    assert weights == {"甲": 7, "乙": 7}


def test_meta_cycle(db: Database) -> None:
    assert db.get_cycle() == 1
    assert db.bump_cycle() == 2
    assert db.bump_cycle() == 3
    assert db.get_cycle() == 3


def test_zero_weight_blocked_by_check_constraint(db: Database) -> None:
    """CheckConstraint 在数据库层面兜底，绕过 ORM 也写不进 0 权重。

    抽取逻辑仍然为「全 0 权重」保留了均匀抽样分支（见 test_draw.py，
    那里用伪造对象验证），因为手改库或未来迁移都可能造出这种数据。
    """
    person = db.add_person("零权重", 1).person
    assert person.id is not None
    with pytest.raises(IntegrityError):
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE person SET weight = 0 WHERE id = :pid"),
                {"pid": person.id},
            )


def test_replace_admin_password_is_conditional(db: Database) -> None:
    """条件写：只有当前哈希仍等于读到的值时才写入。

    两个管理窗口同时改密码时，后写者不能静默覆盖先写者。
    """
    assert db.get_admin_password_hash() == ""
    # 首次设置：行不存在 → 插入
    assert db.replace_admin_password("", "hash-a") is True
    assert db.get_admin_password_hash() == "hash-a"

    # 用旧值再改一次：条件不成立 → 失败，库里的值不动
    assert db.replace_admin_password("", "hash-b") is False
    assert db.get_admin_password_hash() == "hash-a"

    # 读到的是最新值 → 写入成功
    assert db.replace_admin_password("hash-a", "hash-c") is True
    assert db.get_admin_password_hash() == "hash-c"


def test_replace_admin_password_insert_race(db: Database) -> None:
    """两个进程都以为「还没设置」时，只有一个能插入成功。

    直接用一条已经占位的行模拟「对方已抢先插入」，条件写必须返回 False
    而不是抛异常——调用方据此回 ALREADY_CONFIGURED。
    """
    with db.transaction() as session:
        session.add(Meta(key=META_ADMIN_PASSWORD, value="first"))

    assert db.replace_admin_password("", "second") is False
    assert db.get_admin_password_hash() == "first"
