"""Version checks read actual Python AST, JSON locks and executed UK/EN catalogs."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "bump_version", REPOSITORY / "scripts/bump_version.py"
)
assert spec and spec.loader
versions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(versions)


@pytest.fixture
def release_tree(tmp_path: Path) -> Path:
    current = json.loads((REPOSITORY / "frontend/launcher/package.json").read_text())["version"]
    for name in (
        "backend/app/main.py",
        "frontend/launcher/package.json",
        "frontend/launcher/package-lock.json",
        "frontend/launcher/renderer/whats-new.js",
        f"docs/release-notes/v{current}.md",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / name, target)
    return tmp_path


def _edit_json(path: Path, mutate: Any) -> None:
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value))


def test_actual_release_version_cli_passes_without_mutation(release_tree: Path) -> None:
    current = versions.check(release_tree)
    result = subprocess.run(
        [sys.executable, str(REPOSITORY / "scripts/bump_version.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and f"Version {current} is consistent" in result.stdout


@pytest.mark.parametrize("source", ["app", "root", "lock", "lock_package"])
def test_mismatched_backend_and_lock_metadata_fail_before_success(
    release_tree: Path, source: str
) -> None:
    if source in {"app", "root"}:
        path = release_tree / "backend/app/main.py"
        current = versions.check(release_tree)
        text = path.read_text()
        if source == "app":
            text = text.replace(f'version="{current}"', 'version="0.53.999"')
        else:
            text = text.replace(f'"version": "{current}"', '"version": "0.53.999"')
        path.write_text(text)
    else:
        path = release_tree / "frontend/launcher/package-lock.json"
        if source == "lock":
            _edit_json(path, lambda v: v.update(version="0.53.999"))
        else:
            _edit_json(path, lambda v: v["packages"][""].update(version="0.53.999"))
    with pytest.raises(ValueError, match="Version mismatch"):
        versions.check(release_tree)


@pytest.mark.parametrize("language", ["uk", "en"])
def test_missing_actual_locale_copy_fails(release_tree: Path, language: str) -> None:
    current = versions.check(release_tree)
    path = release_tree / "frontend/launcher/renderer/whats-new.js"
    text = path.read_text()
    start = text.index(f"    {language}: {{")
    version = text.index(f'"{current}"', start)
    text = text[:version] + text[version:].replace(f'"{current}"', '"0.0.0"', 1)
    path.write_text(text)
    with pytest.raises(ValueError, match=f"Missing nonempty {language}"):
        versions.check(release_tree)


@pytest.mark.parametrize("damage", ["missing", "one_language", "future"])
def test_notes_are_required_in_both_languages_at_current_latest_version(
    release_tree: Path, damage: str
) -> None:
    current = versions.check(release_tree)
    path = release_tree / "docs/release-notes" / f"v{current}.md"
    if damage == "missing":
        path.unlink()
    elif damage == "one_language":
        path.write_text("Only one section")
    else:
        major, minor, patch = current.split(".")
        (path.parent / f"v{major}.{minor}.{int(patch) + 1}.md").write_text("future draft")
    with pytest.raises(ValueError, match="notes|English"):
        versions.check(release_tree)
