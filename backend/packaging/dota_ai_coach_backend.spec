# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None

BACKEND_DIR = Path(SPECPATH).parent
REPO_ROOT = BACKEND_DIR.parent


def data_dir(source: Path, destination: str):
    return [(str(source), destination)] if source.exists() else []


datas = []
datas += data_dir(REPO_ROOT / "data" / "heroes", "data/heroes")
datas += data_dir(REPO_ROOT / "data" / "meta", "data/meta")
datas += data_dir(REPO_ROOT / "data" / "knowledge_base", "data/knowledge_base")
datas += data_dir(REPO_ROOT / "data" / "live", "data/live")

hiddenimports = []
for package in (
    "app",
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "pydantic_core",
    "anyio",
    "sniffio",
):
    hiddenimports += collect_submodules(package)

a = Analysis(
    [
        str(BACKEND_DIR / "packaging" / "backend_server.py"),
        str(BACKEND_DIR / "packaging" / "demo_playback.py"),
    ],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# a.scripts starts with PyInstaller's bootstrap and runtime hooks, followed by
# the entry scripts. Each exe needs all of the former plus exactly one of the
# latter; indexing a.scripts[0] would pick the bootstrap and the exe would exit
# immediately without starting the server.
ENTRY_SCRIPTS = ("backend_server", "demo_playback")
runtime_scripts = [entry for entry in a.scripts if entry[0] not in ENTRY_SCRIPTS]


def scripts_for(entry_name: str):
    entry = [item for item in a.scripts if item[0] == entry_name]
    assert len(entry) == 1, f"entry script {entry_name!r} not found in Analysis"
    return runtime_scripts + entry


backend_exe = EXE(
    pyz,
    scripts_for("backend_server"),
    [],
    exclude_binaries=True,
    name="dota-ai-coach-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

demo_exe = EXE(
    pyz,
    scripts_for("demo_playback"),
    [],
    exclude_binaries=True,
    name="dota-ai-coach-demo-playback",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    backend_exe,
    demo_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="dota-ai-coach-backend",
)
