"""Check the release version across actual backend, package, lock and catalogs."""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"0\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


def check(root: Path) -> str:
    launcher = root / "frontend/launcher"
    package = json.loads((launcher / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((launcher / "package-lock.json").read_text(encoding="utf-8"))
    current = package["version"]
    if not isinstance(current, str) or not VERSION.fullmatch(current):
        raise ValueError("Launcher package.json needs a 0.MINOR.PATCH version")
    versions = {
        "package": current,
        "lock": lock.get("version"),
        "lock root package": lock.get("packages", {}).get("", {}).get("version"),
    }
    tree = ast.parse((root / "backend/app/main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "LocalApiApp"
        ):
            for keyword in node.keywords:
                if keyword.arg == "version":
                    versions["backend app"] = ast.literal_eval(keyword.value)
        if isinstance(node, ast.FunctionDef) and node.name == "root":
            for expression in ast.walk(node):
                if isinstance(expression, ast.Dict):
                    for key, value in zip(expression.keys, expression.values, strict=True):
                        if isinstance(key, ast.Constant) and key.value == "version":
                            versions["backend root"] = ast.literal_eval(value)
    if "backend app" not in versions or "backend root" not in versions:
        raise ValueError("Missing backend app/root version metadata")
    mismatched = [f"{name}: {value!r}" for name, value in versions.items() if value != current]
    if mismatched:
        raise ValueError("Version mismatch: " + "; ".join(mismatched))
    node_executable = shutil.which("node")
    if node_executable is None:
        raise ValueError("Node is required to check the actual UK/EN catalog module")
    result = subprocess.run(
        [
            node_executable,
            "-e",
            "const m=require(process.argv[1]);process.stdout.write(JSON.stringify({en:m.texts('en'),uk:m.texts('uk')}));",
            str(launcher / "renderer/whats-new.js"),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    tables = json.loads(result.stdout)
    for language in ("uk", "en"):
        table = tables[language]
        bullets = table.get(current)
        if (
            not isinstance(bullets, list)
            or not bullets
            or any(not isinstance(b, str) or not b.strip() for b in bullets)
        ):
            raise ValueError(f"Missing nonempty {language} update copy for {current}")
        latest = max(table, key=lambda v: tuple(map(int, v.split("."))))
        if latest != current:
            raise ValueError(f"Latest {language} update version {latest} differs from {current}")
    notes = root / "docs/release-notes" / f"v{current}.md"
    if not notes.is_file():
        raise ValueError(f"Missing release notes: {notes.name}")
    copy = notes.read_text(encoding="utf-8")
    sections = copy.split("**In English:**", 1)
    if len(sections) != 2 or not sections[0].strip() or not sections[1].strip():
        raise ValueError("Release notes need Ukrainian and English sections")
    latest_notes = max(
        (p.stem[1:] for p in notes.parent.glob("v*.md")),
        key=lambda v: tuple(map(int, v.split("."))),
    )
    if latest_notes != current:
        raise ValueError(f"Latest notes {latest_notes} differ from {current}")
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        required=True,
        help="Read-only validation; copy and cache/rule bumps remain explicit",
    )
    args = parser.parse_args()
    try:
        if args.check:
            print(
                f"Version {check(ROOT)} is consistent across backend, package, lock, UK/EN copy and notes"
            )
        return 0
    except (
        ValueError,
        KeyError,
        OSError,
        SyntaxError,
        subprocess.SubprocessError,
    ) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
