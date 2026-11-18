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


def _preview(db: Database, parsed: ParsedRoster, source: str) -> ImportPreview:
    existing = db.duplicate_names(parsed.names)
    names = [name for name in parsed.names if name not in existing]
    return ImportPreview(
        path=source,
        format=parsed.format,
        count=len(parsed.names),
        file_dups=parsed.skipped,
        db_dups=len(parsed.names) - len(names),
        names=names,
    )


def preview_import(db: Database, path: Path) -> ImportPreview:
    """解析文件并给出预览，不落库。"""
    logger.info("preview import {}", path)
    parsed = parse_roster(path)
    return _preview(db, parsed, str(path))


def _apply(
    db: Database, parsed: ParsedRoster, mode: ImportMode, weight: int, dedupe: bool
) -> ImportResult:
    weights = parsed.weights if parsed.weights else [weight] * len(parsed.names)
    result = db.import_people(
        names=parsed.names,
        weights=weights,
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
