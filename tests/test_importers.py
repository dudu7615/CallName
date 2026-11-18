"""名单解析测试。"""

import json
import pickle
from pathlib import Path

import pytest

from callname.importers import RosterError, parse_roster
from callname.schemas import ImportFormat


def _write(tmp_path: Path, name: str, data: bytes | str) -> Path:
    path = tmp_path / name
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def test_yaml_list_of_strings(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.yml", "- 张三\n- 李四\n")
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四"]
    assert parsed.format is ImportFormat.YAML
    assert parsed.weights == [None, None], "没写权重 = 交给默认权重"


def test_yaml_list_of_objects(tmp_path: Path) -> None:
    path = _write(tmp_path, "b.yaml", "- name: 张三\n  weight: 3\n- name: 李四\n")
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四"]
    assert parsed.weights == [3, None]


def test_yaml_with_names_key(tmp_path: Path) -> None:
    path = _write(tmp_path, "c.yml", "names:\n  - 甲\n  - 乙\n")
    assert parse_roster(path).names == ["甲", "乙"]


def test_txt_utf8_bom_and_numbering(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.txt", b"\xef\xbb\xbf1. \xe5\xbc\xa0\xe4\xb8\x89\n2\xe3\x80\x81\xe6\x9d\x8e\xe5\x9b\x9b\n\n")
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四"]
    assert parsed.format is ImportFormat.TXT


def test_txt_gb18030(tmp_path: Path) -> None:
    path = tmp_path / "gbk.txt"
    path.write_bytes("王五\n赵六\n".encode("gb18030"))
    assert parse_roster(path).names == ["王五", "赵六"]


def test_txt_space_and_comma_separators(tmp_path: Path) -> None:
    path = _write(tmp_path, "sep.txt", "张三 李四\n王五,赵六，孙七、周八\t吴九")
    assert parse_roster(path).names == ["张三", "李四", "王五", "赵六", "孙七", "周八", "吴九"]


def test_txt_fullwidth_space(tmp_path: Path) -> None:
    path = _write(tmp_path, "full.txt", "张三　李四")
    assert parse_roster(path).names == ["张三", "李四"]


def test_txt_numbered_tokens_are_dropped(tmp_path: Path) -> None:
    path = _write(tmp_path, "num.txt", "1. 张三 2. 李四\n3 王五")
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四", "王五"]
    assert parsed.skipped == 0, "序号残留不应算作文件内重复"


def test_csv_with_header_and_weight(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.csv", "姓名,权重\n张三,5\n李四,0\n")
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四"]
    assert parsed.weights == [5, None], "非法权重视为未指定，由默认权重兜底"


def test_csv_without_header(tmp_path: Path) -> None:
    path = _write(tmp_path, "b.csv", "张三\n李四\n")
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四"]
    assert parsed.weights == [None, None]


def test_json_shapes(tmp_path: Path) -> None:
    strings = _write(tmp_path, "a.json", json.dumps(["张三", "李四"]))
    objects = _write(tmp_path, "b.json", json.dumps([{"name": "张三", "weight": 4}, {"name": "李四"}]))
    parsed_strings = parse_roster(strings)
    assert parsed_strings.names == ["张三", "李四"]
    assert parsed_strings.weights == [None, None]
    parsed = parse_roster(objects)
    assert parsed.names == ["张三", "李四"]
    assert parsed.weights == [4, None]


def test_txt_weights_unset(tmp_path: Path) -> None:
    path = _write(tmp_path, "w.txt", "张三 李四\n")
    parsed = parse_roster(path)
    assert parsed.weights == [None, None]


def test_pkl_list_of_strings(tmp_path: Path) -> None:
    path = tmp_path / "a.pkl"
    path.write_bytes(pickle.dumps(["张三", "李四"], protocol=4))
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四"]
    assert parsed.format is ImportFormat.PKL


def test_pkl_rejects_non_string_list(tmp_path: Path) -> None:
    path = tmp_path / "bad.pkl"
    path.write_bytes(pickle.dumps({"name": "张三"}, protocol=4))
    with pytest.raises(RosterError) as info:
        parse_roster(path)
    assert info.value.code == "BAD_PICKLE"


def test_duplicates_collapse_and_are_counted(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.txt", "张三\n李四\n张三\n")
    parsed = parse_roster(path)
    assert parsed.names == ["张三", "李四"]
    assert parsed.skipped == 1


def test_unsupported_suffix(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.docx", "x")
    with pytest.raises(RosterError) as info:
        parse_roster(path)
    assert info.value.code == "UNSUPPORTED_FORMAT"


def test_empty_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.txt", "\n  \n")
    with pytest.raises(RosterError) as info:
        parse_roster(path)
    assert info.value.code == "EMPTY_FILE"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RosterError) as info:
        parse_roster(tmp_path / "nope.txt")
    assert info.value.code == "NO_FILE"
