"""名单文件解析：yml/yaml、txt、csv、json、pkl -> ParsedRoster。

解析只负责「文件 -> 名字列表」，不碰数据库；去重预览与落库在
import_service.py，数据库现状由 Database 提供。
"""

import csv
import io
import json
import pickle
from pathlib import Path

import yaml
from loguru import logger

from callname.schemas import ImportFormat, ParsedRoster

TEXT_ENCODINGS = ("utf-8-sig", "gb18030")
CSV_HEADERS = {"姓名", "名字", "name", "学生", "学生姓名", "学生名字"}
WEIGHT_HEADERS = {"weight", "权重"}
MIN_WEIGHT = 1
MAX_WEIGHT = 99


class RosterError(Exception):
    """名单解析失败；code 供前端分支，message 直接展示。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _decode(data: bytes, path: Path) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            logger.debug("decode with {} failed for {}", encoding, path)
    raise RosterError("PARSE_ERROR", "无法识别文件编码（试过 UTF-8 与 GB18030）")


def _clean_name(raw: str) -> str:
    """去掉序号、列表符号与首尾空白。"""
    text = raw.strip().lstrip("﻿").strip()
    for prefix in ("- ", "·", "*", "•"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    # "1. 张三" / "1、张三" / "1) 张三"
    for index in range(len(text)):
        char = text[index]
        if char.isdigit():
            continue
        if char in ".)、)） " and index > 0:
            text = text[index + 1 :].strip()
        break
    return text


def _normalise_weight(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str, float)):
        return MIN_WEIGHT
    try:
        weight = int(value)
    except (TypeError, ValueError):
        return MIN_WEIGHT
    return weight if MIN_WEIGHT <= weight <= MAX_WEIGHT else MIN_WEIGHT


def _collect(
    entries: list[tuple[str, int]], fmt: ImportFormat, skipped: int = 0
) -> ParsedRoster:
    """按名字去重保序（保留首次出现的权重）。"""
    names: list[str] = []
    weights: list[int] = []
    seen: set[str] = set()
    dropped = skipped
    for raw_name, weight in entries:
        name = _clean_name(raw_name)
        if not name:
            dropped += 1
            continue
        if name in seen:
            dropped += 1
            continue
        seen.add(name)
        names.append(name)
        weights.append(weight)
    if not names:
        raise RosterError("EMPTY_FILE", "文件里没有可用的名字")
    return ParsedRoster(
        names=names, weights=weights, format=fmt, skipped=dropped
    )


def _from_yaml(data: bytes, path: Path) -> ParsedRoster:
    try:
        document = yaml.safe_load(_decode(data, path))
    except yaml.YAMLError as exc:
        raise RosterError("PARSE_ERROR", f"YAML 解析失败：{exc}") from exc

    if isinstance(document, dict):
        document = document.get("names", [])
    if not isinstance(document, list):
        raise RosterError("PARSE_ERROR", "YAML 必须是名字列表或含 names 的对象")

    entries: list[tuple[str, int]] = []
    skipped = 0
    for item in document:
        if isinstance(item, str):
            entries.append((item, MIN_WEIGHT))
        elif isinstance(item, dict):
            raw_name = item.get("name")
            if not isinstance(raw_name, str):
                skipped += 1
                continue
            entries.append((raw_name, _normalise_weight(item.get("weight", MIN_WEIGHT))))
        else:
            skipped += 1
    return _collect(entries, ImportFormat.YAML, skipped)


def _from_txt(data: bytes, path: Path) -> ParsedRoster:
    entries = [(line, MIN_WEIGHT) for line in _decode(data, path).splitlines()]
    return _collect(entries, ImportFormat.TXT)


def _from_csv(data: bytes, path: Path) -> ParsedRoster:
    reader = csv.reader(io.StringIO(_decode(data, path)))
    entries: list[tuple[str, int]] = []
    skipped = 0
    weight_column: int | None = None
    for row in reader:
        if not row:
            skipped += 1
            continue
        first = row[0].strip().lstrip("﻿").strip().lower()
        if first in CSV_HEADERS:
            weight_column = None
            for index, cell in enumerate(row[1:], start=1):
                if cell.strip().lower() in WEIGHT_HEADERS:
                    weight_column = index
            skipped += 1
            continue
        weight = (
            _normalise_weight(row[weight_column])
            if weight_column is not None and len(row) > weight_column
            else MIN_WEIGHT
        )
        entries.append((row[0], weight))
    return _collect(entries, ImportFormat.CSV, skipped)


def _from_json(data: bytes, path: Path) -> ParsedRoster:
    try:
        document = json.loads(_decode(data, path))
    except json.JSONDecodeError as exc:
        raise RosterError("PARSE_ERROR", f"JSON 解析失败：{exc}") from exc

    if isinstance(document, dict):
        document = document.get("names", [])
    if not isinstance(document, list):
        raise RosterError("PARSE_ERROR", "JSON 必须是名字数组或含 names 的对象")

    entries: list[tuple[str, int]] = []
    skipped = 0
    for item in document:
        if isinstance(item, str):
            entries.append((item, MIN_WEIGHT))
        elif isinstance(item, dict):
            raw_name = item.get("name")
            if not isinstance(raw_name, str):
                skipped += 1
                continue
            entries.append((raw_name, _normalise_weight(item.get("weight", MIN_WEIGHT))))
        else:
            skipped += 1
    return _collect(entries, ImportFormat.JSON, skipped)


def _from_pkl(data: bytes, path: Path) -> ParsedRoster:
    """只接受 list[str]：pickle 会执行任意代码，必须限制结果形态。"""
    try:
        loaded: object = pickle.loads(data)
    except Exception as exc:  # pickle 可能抛任何异常
        raise RosterError("BAD_PICKLE", f"pickle 文件无法读取：{exc}") from exc
    if not isinstance(loaded, list) or not all(
        isinstance(item, str) for item in loaded
    ):
        raise RosterError(
            "BAD_PICKLE", "只支持由本程序生成的 list[str] 名单文件"
        )
    return _collect([(item, MIN_WEIGHT) for item in loaded], ImportFormat.PKL)


def parse_roster(path: Path) -> ParsedRoster:
    """按扩展名分派解析。"""
    if not path.is_file():
        raise RosterError("NO_FILE", f"找不到文件：{path}")
    data = path.read_bytes()
    if not data:
        raise RosterError("EMPTY_FILE", "文件是空的")

    suffix = path.suffix.lower()
    logger.debug("parse roster {} ({})", path, suffix)
    if suffix in (".yml", ".yaml"):
        return _from_yaml(data, path)
    if suffix == ".txt":
        return _from_txt(data, path)
    if suffix == ".csv":
        return _from_csv(data, path)
    if suffix == ".json":
        return _from_json(data, path)
    if suffix == ".pkl":
        return _from_pkl(data, path)
    raise RosterError("UNSUPPORTED_FORMAT", f"不支持的名单格式：{suffix or '无扩展名'}")


__all__ = ["RosterError", "parse_roster"]
