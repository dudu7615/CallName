"""pytest 公共夹具：每个用例一个独立的临时数据库。"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from callname.db import Database


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "test.db")
    database.migrate()
    yield database
    database.close()


@pytest.fixture()
def seeded(db: Database) -> Database:
    """52 个名字，权重全 1，便于验证「每轮每人恰好一次」。"""
    for index in range(52):
        db.add_person(f"学生{index:02d}", 1)
    return db
