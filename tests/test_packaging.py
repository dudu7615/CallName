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


def test_pyinstaller_in_build_group() -> None:
    """PyInstaller 只在打包时需要，不能混进日常开发或运行依赖。"""
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    assert "pyinstaller" not in " ".join(str(item) for item in dependencies).lower()

    groups = _pyproject()["dependency-groups"]
    assert isinstance(groups, dict)
    build = groups["build"]
    assert isinstance(build, list)
    assert any(str(item).startswith("pyinstaller") for item in build)


def test_version_matches() -> None:
    """pyproject.toml 的 version 是发布流水线读版本号的唯一来源，
    callname/__init__.py 里那份是给 --version 用的，两者不能分叉。"""
    import re

    project = _pyproject()["project"]
    assert isinstance(project, dict)
    init = (ROOT / "callname" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', init)
    assert match is not None
    assert match.group(1) == project["version"]


def _spec() -> str:
    return (ROOT / "packaging" / "main.spec").read_text(encoding="utf-8")


def test_web_assets_are_bundled_at_package_path() -> None:
    """前端必须落到 callname/web：冻结后 paths.WEB_DIR 按 __file__ 解析，
    dest 写成 "web" 会白屏，而 PyInstaller 不会报错。"""
    spec = _spec()
    assert '(str(ROOT / "callname" / "web"), "callname/web")' in spec


def test_windows_backend_is_hidden_import() -> None:
    """pywebview 在 Windows 上运行期才 import winforms，静态分析追不到。"""
    spec = _spec()
    assert "webview.platforms.winforms" in spec.split("hiddenimports")[1]


def test_packaging_files_are_tracked() -> None:
    """.gitignore 里的 *.spec 不能把打包配置一起忽略，否则干净克隆打不了包。"""
    import subprocess

    for relative in ("packaging/main.spec", "packaging/setup.iss", "packaging/killapp.ps1"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", relative],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 1, f"{relative} 被 .gitignore 忽略了"


def test_installer_names_match_release_workflow() -> None:
    """exe 名与产物名在 setup.iss / release.yml / spec 三处必须一致。"""
    iss = (ROOT / "packaging" / "setup.iss").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert '#define AppExeName "CallName.exe"' in iss
    assert 'name="CallName"' in _spec()
    assert 'f"CallName-Setup-{version}.exe"' in workflow
    assert 'f"CallName-portable-{version}.zip"' in workflow
    assert "dist\\CallName\\*" in workflow
