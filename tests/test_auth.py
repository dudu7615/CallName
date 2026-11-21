"""管理员密码：Argon2id 哈希、校验与强度规则。"""

from pathlib import Path

import pytest

from callname.auth import (
    AuthError,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)
from callname.db import META_ADMIN_PASSWORD, Database


def test_hash_roundtrip_and_structure() -> None:
    stored = hash_password("教室密码")
    assert stored.startswith("$argon2id$")
    assert "m=65536,t=3,p=1" in stored
    assert "教室密码" not in stored
    assert verify_password("教室密码", stored) is True
    assert verify_password("教室密馬", stored) is False


def test_salt_is_random() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_corrupt_hash_is_a_failure_not_a_crash() -> None:
    for stored in ("", "not-a-hash", "$argon2id$broken"):
        assert verify_password("whatever", stored) is False
        assert needs_rehash(stored) is False


def test_rehash_detects_weaker_parameters() -> None:
    current = hash_password("abcd")
    assert needs_rehash(current) is False
    # 模拟旧版用更小内存写下的哈希：校验仍成功，但应被标记为需要升级。
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("abcd")
    assert verify_password("abcd", weak) is True
    assert needs_rehash(weak) is True


def test_password_length_rules() -> None:
    with pytest.raises(AuthError) as short:
        validate_password("abc")
    assert short.value.code == "PASSWORD_TOO_SHORT"

    with pytest.raises(AuthError) as long:
        validate_password("x" * 129)
    assert long.value.code == "PASSWORD_TOO_LONG"

    assert validate_password("abcd") == "abcd"


def test_meta_password_slot(db: Database) -> None:
    assert db.get_admin_password_hash() == ""
    db.set_admin_password_hash(hash_password("abcd"))
    stored = db.get_admin_password_hash()
    assert verify_password("abcd", stored) is True
    # 键名稳定，外部手工改库与测试都依赖它；程序本身不提供重置入口
    assert META_ADMIN_PASSWORD == "admin_password"


def test_password_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "auth.db"
    first = Database(path)
    first.migrate()
    first.set_admin_password_hash(hash_password("abcd"))
    first.close()

    second = Database(path)
    second.migrate()
    assert verify_password("abcd", second.get_admin_password_hash()) is True
    second.close()
