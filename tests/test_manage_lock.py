"""设置窗口的锁：首次设置密码、解锁、修改密码，以及未解锁时的统一拒绝。"""

import json

from callname.api import ManageApi
from callname.db import Database


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


def test_reset_makes_window_ask_to_setup_again(db: Database) -> None:
    api = ManageApi(db=db)
    api.setup_password("abcd", "abcd")
    db.clear_admin_password()
    state = _data(_json(api.auth_state()))
    assert state == {"configured": False, "unlocked": True}
    # 已解锁的进程不受影响；新进程回到「设置密码」。
    fresh = ManageApi(db=db)
    assert _data(_json(fresh.auth_state())) == {"configured": False, "unlocked": False}
    assert _json(fresh.setup_password("wxyz", "wxyz"))["ok"] is True
