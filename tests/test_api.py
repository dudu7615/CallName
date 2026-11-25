"""API 信封测试：不启动窗口，直接实例化两个 js_api 类。"""

import json
import random
from pathlib import Path

from callname.api import MainApi, ManageApi
from callname.db import Database
from callname.draw import DrawSession


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


def test_main_settings_roundtrip(db: Database) -> None:
    api = MainApi(session=DrawSession(db), db=db)
    assert _assert_json(api.get_settings())["data"] == {
        "draw_mode": "auto",
        "sound_enabled": True,
    }

    saved = _assert_json(api.set_draw_mode("manual"))
    assert saved["ok"] is True
    assert saved["data"] == {"draw_mode": "manual", "sound_enabled": True}
    assert _assert_json(api.get_settings())["data"] == {
        "draw_mode": "manual",
        "sound_enabled": True,
    }

    bad = _assert_json(api.set_draw_mode("sometimes"))
    assert bad["ok"] is False
    assert bad["error"]["code"] == "BAD_MODE"  # type: ignore[index]
    assert _assert_json(api.get_settings())["data"] == {
        "draw_mode": "manual",
        "sound_enabled": True,
    }


def test_main_sound_toggle_roundtrip(db: Database) -> None:
    """静音开关与 draw_mode 一样走 meta 表，setter 要回完整设置快照。"""
    api = MainApi(session=DrawSession(db), db=db)
    assert _assert_json(api.get_settings())["data"] == {
        "draw_mode": "auto",
        "sound_enabled": True,
    }

    muted = _assert_json(api.set_sound_enabled(False))
    assert muted["ok"] is True
    assert muted["data"] == {"draw_mode": "auto", "sound_enabled": False}
    assert _assert_json(api.get_settings())["data"] == {
        "draw_mode": "auto",
        "sound_enabled": False,
    }

    # 切模式不能把静音状态带回去
    _assert_json(api.set_draw_mode("manual"))
    assert _assert_json(api.get_settings())["data"] == {
        "draw_mode": "manual",
        "sound_enabled": False,
    }

    unmuted = _assert_json(api.set_sound_enabled(True))
    assert unmuted["data"] == {"draw_mode": "manual", "sound_enabled": True}


def test_manage_crud_envelopes(manage_api: ManageApi) -> None:
    api = manage_api

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


def test_manage_error_envelope(manage_api: ManageApi) -> None:
    api = manage_api
    payload = _assert_json(api.add_person("  ", 1))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BAD_NAME"  # type: ignore[index]

    weight = _assert_json(api.add_person("李四", 0))
    assert weight["error"]["code"] == "BAD_WEIGHT"  # type: ignore[index]

    missing = _assert_json(api.delete_person(9999))
    assert missing["ok"] is True
    assert missing["data"]["deleted"] is False  # type: ignore[index]


def test_bad_patch_payload_stays_in_envelope(manage_api: ManageApi, db: Database) -> None:
    """pydantic 校验失败也必须走统一信封，不能把 ValidationError 抛给桥。"""
    api = manage_api
    pid = db.add_person("张三", 1).person.id
    assert pid is not None

    bad_patches: list[dict[str, object]] = [
        {"weight": "abc"},
        {"name": 123},
        {"active": "maybe"},
    ]
    for patch in bad_patches:
        payload = _assert_json(api.update_person(pid, patch))
        assert payload["ok"] is False, patch
        assert payload["error"]["code"] == "BAD_PAYLOAD"  # type: ignore[index]
        assert payload["error"]["message"]  # type: ignore[index]


def test_manage_duplicate_warning(manage_api: ManageApi) -> None:
    api = manage_api
    api.add_person("张三", 1)
    payload = _assert_json(api.add_person("张三", 1))
    assert payload["data"]["warning"] == "DUPLICATE_NAME"  # type: ignore[index]


def test_manage_import_flow(manage_api: ManageApi, db: Database, tmp_path: Path) -> None:
    api = manage_api
    path = tmp_path / "roster.txt"
    path.write_text("张三\n李四\n", encoding="utf-8")

    preview = _assert_json(api.preview_import(str(path)))
    assert preview["ok"] is True
    assert preview["data"]["count"] == 2  # type: ignore[index]
    assert preview["data"]["db_dups"] == 0  # type: ignore[index]
    assert preview["data"]["unweighted"] == 2  # type: ignore[index]

    committed = _assert_json(api.commit_import(str(path), "merge", 3, True))
    assert committed["data"] == {"added": 2, "updated": 0, "skipped": 0}
    assert {person.weight for person in db.list_people()} == {3}, "txt 未写权重 → 默认权重"

    again = _assert_json(api.preview_import(str(path)))
    assert again["data"]["db_dups"] == 2  # type: ignore[index]


def test_import_keeps_explicit_weights_and_fills_default(manage_api: ManageApi, db: Database, tmp_path: Path) -> None:
    api = manage_api
    path = tmp_path / "mixed.yml"
    path.write_text("- name: 张三\n  weight: 5\n- name: 李四\n", encoding="utf-8")

    preview = _assert_json(api.preview_import(str(path)))
    assert preview["data"]["unweighted"] == 1  # type: ignore[index]

    _assert_json(api.commit_import(str(path), "merge", 2, True))
    weights = {person.name: person.weight for person in db.list_people()}
    assert weights == {"张三": 5, "李四": 2}


def test_pick_import_file_without_window(manage_api: ManageApi) -> None:
    api = manage_api
    payload = _assert_json(api.pick_import_file())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NO_WINDOW"  # type: ignore[index]
