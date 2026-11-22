"""设置窗口的锁：首次设置密码、解锁、修改密码，以及未解锁时的统一拒绝。"""

import json

import pytest

from callname.api import ManageApi
from callname.db import META_ADMIN_PASSWORD, Database
from callname.models import Meta


def _json(payload: object) -> dict[str, object]:
    loaded = json.loads(json.dumps(payload, ensure_ascii=False))
    assert isinstance(loaded, dict)
    return loaded


def _error(payload: dict[str, object]) -> str:
    error = payload["error"]
    assert isinstance(error, dict)
    code = error["code"]
    assert isinstance(code, str)
    return code


def _data(payload: dict[str, object]) -> dict[str, object]:
    data = payload["data"]
    assert isinstance(data, dict)
    return data


def test_fresh_db_starts_locked_and_unconfigured(db: Database) -> None:
    api = ManageApi(db=db)
    state = _data(_json(api.auth_state()))
    assert state == {"configured": False, "unlocked": False}
    assert _error(_json(api.list_people())) == "LOCKED"
    assert _error(_json(api.stats())) == "LOCKED"
    assert _error(_json(api.add_person("张三", 1))) == "LOCKED"
    assert _error(_json(api.pick_import_file())) == "LOCKED"


def test_setup_password_unlocks_and_stores_hash(db: Database) -> None:
    api = ManageApi(db=db)
    result = _json(api.setup_password("教室密码", "教室密码"))
    assert result["ok"] is True
    assert _data(result) == {"configured": True, "unlocked": True}
    assert db.get_admin_password_hash().startswith("$argon2id$")
    assert _json(api.list_people())["ok"] is True


def test_setup_rejects_mismatch_and_short_password(db: Database) -> None:
    api = ManageApi(db=db)
    assert _error(_json(api.setup_password("abcd", "abce"))) == "PASSWORD_MISMATCH"
    assert _error(_json(api.setup_password("abc", "abc"))) == "PASSWORD_TOO_SHORT"
    assert db.get_admin_password_hash() == ""
    assert _data(_json(api.auth_state()))["configured"] is False


def test_setup_is_refused_once_configured(db: Database) -> None:
    ManageApi(db=db).setup_password("abcd", "abcd")
    second = ManageApi(db=db)
    assert _error(_json(second.setup_password("efgh", "efgh"))) == "ALREADY_CONFIGURED"
    assert _data(_json(second.auth_state())) == {"configured": True, "unlocked": False}


def test_unlock_flow(db: Database) -> None:
    first = ManageApi(db=db)
    first.setup_password("abcd", "abcd")

    locked = ManageApi(db=db)
    assert _data(_json(locked.auth_state()))["unlocked"] is False
    assert _error(_json(locked.unlock("wrong"))) == "BAD_PASSWORD"
    assert _data(_json(locked.auth_state()))["unlocked"] is False
    assert _json(locked.unlock("abcd"))["ok"] is True
    assert _data(_json(locked.auth_state()))["unlocked"] is True
    assert _json(locked.list_people())["ok"] is True


def test_unlock_before_setup_is_rejected(db: Database) -> None:
    api = ManageApi(db=db)
    assert _error(_json(api.unlock("abcd"))) == "NOT_CONFIGURED"


def test_change_password(manage_api: ManageApi, db: Database) -> None:
    assert _error(_json(manage_api.change_password("wrong", "efgh", "efgh"))) == "BAD_PASSWORD"
    assert _error(_json(manage_api.change_password("test-pass", "efgh", "efgi"))) == "PASSWORD_MISMATCH"
    assert _json(manage_api.change_password("test-pass", "efgh", "efgh"))["ok"] is True

    reopened = ManageApi(db=db)
    assert _error(_json(reopened.unlock("test-pass"))) == "BAD_PASSWORD"
    assert _json(reopened.unlock("efgh"))["ok"] is True


def test_change_password_requires_unlock(db: Database) -> None:
    ManageApi(db=db).setup_password("abcd", "abcd")
    locked = ManageApi(db=db)
    assert _error(_json(locked.change_password("abcd", "efgh", "efgh"))) == "LOCKED"


def test_password_change_conflict_is_reported(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两个窗口同时改密码：后写的一方必须收到明确失败，而不是静默覆盖。

    在「验证旧密码」和「条件写入」之间插一次竞争：模拟另一个窗口此刻
    已经改掉密码。条件写发现哈希不再是最初读到的那个，必须回
    PASSWORD_CONFLICT，而不是把对方的新密码盖掉。
    """
    from callname import auth as auth_module

    api = ManageApi(db=db)
    api.setup_password("abcd", "abcd")

    real_verify = auth_module.verify_password

    def verify_then_compete(password: str, stored: str) -> bool:
        ok = real_verify(password, stored)
        if ok:
            db.replace_admin_password(stored, "other-window-hash")
        return ok

    monkeypatch.setattr(auth_module, "verify_password", verify_then_compete)

    payload = _json(api.change_password("abcd", "efgh", "efgh"))
    assert payload["ok"] is False
    assert _error(payload) == "PASSWORD_CONFLICT"
    assert db.get_admin_password_hash() == "other-window-hash"

    # 竞争失败的那次改密不应让本进程以为新密码生效了。
    monkeypatch.setattr(auth_module, "verify_password", real_verify)
    assert _error(_json(ManageApi(db=db).unlock("efgh"))) == "BAD_PASSWORD"


def test_concurrent_setup_only_one_wins(db: Database) -> None:
    """首次设置也走条件写：后到的窗口拿到 ALREADY_CONFIGURED。"""
    first = ManageApi(db=db)
    assert first.setup_password("abcd", "abcd")["ok"] is True

    second = ManageApi(db=db)
    payload = _json(second.setup_password("efgh", "efgh"))
    assert payload["ok"] is False
    assert _error(payload) == "ALREADY_CONFIGURED"
    assert ManageApi(db=db).unlock("abcd")["ok"] is True


def test_missing_password_row_asks_to_setup_again(manage_api: ManageApi, db: Database) -> None:
    """没有内置重置入口；只有手工清掉 meta 行，窗口才回到「设置密码」。"""
    manage_api.add_person("张三", 1)
    with db.transaction() as session:
        row = session.get(Meta, META_ADMIN_PASSWORD)
        assert row is not None
        session.delete(row)

    state = _data(_json(manage_api.auth_state()))
    assert state == {"configured": False, "unlocked": True}
    # 已解锁的进程不受影响；新进程回到「设置密码」。
    fresh = ManageApi(db=db)
    assert _data(_json(fresh.auth_state())) == {"configured": False, "unlocked": False}
    assert _json(fresh.setup_password("wxyz", "wxyz"))["ok"] is True
    assert len(_json(fresh.list_people())["data"]) == 1  # type: ignore[arg-type]
