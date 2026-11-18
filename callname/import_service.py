"""导入流程的编排层：解析文件 -> 去重预览 -> 落库。

解析本身在 importers.py；这里只负责把 ParsedRoster 与数据库现状结合。
"""

from pathlib import Path

from loguru import logger

from callname.db import Database
from callname.importers import RosterError, parse_roster
from callname.schemas import (
    ImportMode,
    ImportPreview,
    ImportResult,
    ParsedRoster,
)


def _unweighted_count(parsed: ParsedRoster) -> int:
    """文件里没写权重的名字数（含 weights 比 names 短的情况）。"""
    count = 0
    for index in range(len(parsed.names)):
        if index >= len(parsed.weights) or parsed.weights[index] is None:
            count += 1
    return count


def _preview(db: Database, parsed: ParsedRoster, source: str) -> ImportPreview:
    existing = db.duplicate_names(parsed.names)
    names = [name for name in parsed.names if name not in existing]
    return ImportPreview(
        path=source,
        format=parsed.format,
        count=len(parsed.names),
        file_dups=parsed.skipped,
        db_dups=len(parsed.names) - len(names),
        unweighted=_unweighted_count(parsed),
        names=names,
    )


def preview_import(db: Database, path: Path) -> ImportPreview:
    """解析文件并给出预览，不落库。"""
    logger.info("preview import {}", path)
    parsed = parse_roster(path)
    return _preview(db, parsed, str(path))


def _resolve_weights(parsed: ParsedRoster, weight: int) -> list[int]:
    """文件未指定权重的条目统一用弹层的默认权重。"""
    weights: list[int] = []
    for index in range(len(parsed.names)):
        explicit = parsed.weights[index] if index < len(parsed.weights) else None
        weights.append(weight if explicit is None else explicit)
    return weights


def _apply(
    db: Database, parsed: ParsedRoster, mode: ImportMode, weight: int, dedupe: bool
) -> ImportResult:
    result = db.import_people(
        names=parsed.names,
        weights=_resolve_weights(parsed, weight),
        mode=mode,
        weight_default=weight,
        dedupe=dedupe,
    )
    logger.info(
        "import done mode={} added={} updated={} skipped={}",
        mode,
        result.added,
        result.updated,
        result.skipped,
    )
    return result


def commit_import(
    db: Database,
    path: Path,
    mode: ImportMode,
    weight: int = 1,
    dedupe: bool = True,
) -> ImportResult:
    """把文件里的名单写进数据库。"""
    parsed = parse_roster(path)
    return _apply(db, parsed, mode, weight, dedupe)


__all__ = [
    "RosterError",
    "commit_import",
    "preview_import",
]
