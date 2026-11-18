"""打包与依赖声明测试：防止 Qt 被误装到 Windows，或依赖被绕过 uv 添加。"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_python_requires() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    assert project["requires-python"] == ">=3.14"


def test_qt_is_linux_only() -> None:
    """Windows 走 WebView2，不应带上任何 Qt 包。"""
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    qt = [item for item in dependencies if item.startswith(("pyside6", "qtpy"))]
    assert len(qt) == 2
    for requirement in qt:
        assert "sys_platform == 'linux'" in requirement


def test_uv_uses_configured_mirror() -> None:
    """禁止回落到官方 PyPI；索引必须是项目里写明的那一个。"""
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    uv = tool["uv"]
    assert isinstance(uv, dict)
    indexes = uv["index"]
    assert isinstance(indexes, list) and indexes
    assert indexes[0]["default"] is True
    assert indexes[0]["url"].startswith("https://mirrors.")
