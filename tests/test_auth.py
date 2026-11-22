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


def test_extreme_parameters_are_rejected_before_allocating() -> None:
    """verify() 会按哈希里写的参数分配内存，必须在上限外直接拒绝。

    手工把 m 改到 4 GiB 仍是「合法」哈希串；若真的交给 argon2，管理窗口
    会在返回 False 之前先被内存耗尽。
    """
    absurd = hash_password("abcd").replace("m=65536", "m=4294967295")
    assert verify_password("abcd", absurd) is False
    assert needs_rehash(absurd) is False

    slow = hash_password("abcd").replace("t=3", "t=999999")
    assert verify_password("abcd", slow) is False

    # 长度异常的串不必解析
    assert verify_password("abcd", "$argon2id$" + "x" * 4096) is False


def test_slightly_stronger_parameters_still_verify() -> None:
    """上限要留余量：将来把参数调高（例如 m=96 MiB）时旧哈希仍可用。"""
    from argon2 import PasswordHasher

    stronger = PasswordHasher(time_cost=4, memory_cost=98304, parallelism=2).hash("abcd")
    assert verify_password("abcd", stronger) is True


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
