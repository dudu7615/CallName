"""API 信封测试：不启动窗口，直接实例化两个 js_api 类。"""

import json
import random
from pathlib import Path

from callname.api import MainApi, ManageApi
from callname.db import Database
from callname.draw import DrawSession


def _as_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [entry for entry in value if isinstance(entry, dict)]


def _assert_json(payload: object) -> dict[str, object]:
    dumped = json.dumps(payload, ensure_ascii=False)
    loaded = json.loads(dumped)
    assert isinstance(loaded, dict)
    return loaded


def test_main_flow_is_json_serialisable(db: Database) -> None:
    db.add_person("甲", 1)
    db.add_person("乙", 2)
    session = DrawSession(db, rng=random.Random(21))
    api = MainApi(session=session, db=db)

    status = _assert_json(api.status())
    assert status["ok"] is True
    assert status["data"]["active"] == 2  # type: ignore[index]

    drawn = _assert_json(api.draw())
    assert drawn["ok"] is True
    assert drawn["data"]["name"] in {"甲", "乙"}  # type: ignore[index]
    assert len(drawn["data"]["decoys"]) in {0, 31}  # type: ignore[index]

    reset = _assert_json(api.reset())
    assert reset["ok"] is True
    assert reset["data"]["remaining"] == 2  # type: ignore[index]


def test_main_empty_roster_envelope(db: Database) -> None:
    api = MainApi(session=DrawSession(db), db=db)
    payload = _assert_json(api.draw())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "EMPTY_ROSTER"  # type: ignore[index]


def test_manage_crud_envelopes(db: Database) -> None:
    api = ManageApi(db=db)

    added = _assert_json(api.add_person("张三", 3))
    assert added["ok"] is True
    assert added["data"]["person"]["weight"] == 3  # type: ignore[index]
    pid = added["data"]["person"]["id"]  # type: ignore[index]

    listed = _assert_json(api.list_people())
    assert len(listed["data"]) == 1  # type: ignore[arg-type]

    updated = _assert_json(api.update_person(pid, {"weight": 7, "active": False}))
    assert updated["data"]["weight"] == 7  # type: ignore[index]
    assert updated["data"]["active"] is False  # type: ignore[index]

    active = _assert_json(api.set_active(pid, True))
    assert active["data"]["active"] is True  # type: ignore[index]

    deleted = _assert_json(api.delete_person(pid))
    assert deleted["data"]["deleted"] is True  # type: ignore[index]

    stats = _assert_json(api.stats())
    assert stats["data"]["total"] == 0  # type: ignore[index]


def test_manage_error_envelope(db: Database) -> None:
    api = ManageApi(db=db)
    payload = _assert_json(api.add_person("  ", 1))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BAD_NAME"  # type: ignore[index]

    weight = _assert_json(api.add_person("李四", 0))
    assert weight["error"]["code"] == "BAD_WEIGHT"  # type: ignore[index]

    missing = _assert_json(api.delete_person(9999))
    assert missing["ok"] is True
    assert missing["data"]["deleted"] is False  # type: ignore[index]


def test_manage_duplicate_warning(db: Database) -> None:
    api = ManageApi(db=db)
    api.add_person("张三", 1)
    payload = _assert_json(api.add_person("张三", 1))
    assert payload["data"]["warning"] == "DUPLICATE_NAME"  # type: ignore[index]


def test_manage_import_flow(db: Database, tmp_path: Path) -> None:
    api = ManageApi(db=db)
    path = tmp_path / "roster.txt"
    path.write_text("张三\n李四\n", encoding="utf-8")

    preview = _assert_json(api.preview_import(str(path)))
    assert preview["ok"] is True
    assert preview["data"]["count"] == 2  # type: ignore[index]
    assert preview["data"]["db_dups"] == 0  # type: ignore[index]

    committed = _assert_json(api.commit_import(str(path), "merge", 1, True))
    assert committed["data"] == {"added": 2, "updated": 0, "skipped": 0}

    again = _assert_json(api.preview_import(str(path)))
    assert again["data"]["db_dups"] == 2  # type: ignore[index]


def test_manage_builtin_import(db: Database) -> None:
    api = ManageApi(db=db)
    listed = _assert_json(api.builtin_rosters())
    keys = [entry["key"] for entry in _as_list(listed["data"])]
    assert keys == ["2", "93", "94", "96"]

    preview = _assert_json(api.preview_builtin("2"))
    assert preview["data"]["count"] == 52  # type: ignore[index]

    committed = _assert_json(api.commit_builtin("2", "merge", 1, True))
    assert committed["data"]["added"] == 52  # type: ignore[index]

    rejected = _assert_json(api.preview_builtin("nope"))
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "BAD_KEY"  # type: ignore[index]


def test_pick_import_file_without_window(db: Database) -> None:
    api = ManageApi(db=db)
    payload = _assert_json(api.pick_import_file())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NO_WINDOW"  # type: ignore[index]
