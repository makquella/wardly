from __future__ import annotations

import importlib.util
import io
import os
import stat
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_config() -> ModuleType:
    # A private copy, so the app's real ``app.config`` values stay untouched.
    return _load_module("_config_under_test", BACKEND_DIR / "app" / "config.py")


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("DOTA_AI_BACKEND_PORT", "DOTA_AI_BACKEND_HOST", "SESSION_RECORDS_DIR"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_source_checkout_paths(clean_env):
    clean_env.delattr(sys, "frozen", raising=False)
    config = _load_config()

    assert config.IS_FROZEN is False
    assert config.DATA_DIR == REPO_ROOT / "data"
    assert config.LOGS_DIR == BACKEND_DIR / "logs"
    assert config.SESSION_RECORDS_DIR == BACKEND_DIR / "session_records"
    assert config.GSI_DEBUG_SAMPLES_DIR == BACKEND_DIR / "gsi_debug_samples"
    assert config.HERO_PROFILES_PATH.exists()
    assert config.ITEM_TIMING_RULES_PATH.exists()
    assert config.BACKEND_PORT == 8000


def test_frozen_paths_use_meipass_and_appdata(clean_env, tmp_path):
    bundle = tmp_path / "bundle"
    appdata = tmp_path / "Roaming"
    clean_env.setattr(sys, "frozen", True, raising=False)
    clean_env.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    clean_env.setenv("APPDATA", str(appdata))
    clean_env.setenv("DOTA_AI_BACKEND_PORT", "51234")

    config = _load_config()

    user_dir = appdata / "DotaAICoach"
    assert config.IS_FROZEN is True
    assert bundle / "data" == config.DATA_DIR
    assert bundle / "data" / "knowledge_base" == config.KNOWLEDGE_BASE_DIR
    assert bundle / "data" / "heroes" / "hero_profiles.json" == config.HERO_PROFILES_PATH
    assert user_dir == config.WRITABLE_DIR
    assert user_dir / "logs" == config.LOGS_DIR
    assert user_dir / "session_records" == config.SESSION_RECORDS_DIR
    assert user_dir / "gsi_debug_samples" == config.GSI_DEBUG_SAMPLES_DIR
    assert config.BACKEND_PORT == 51234


def test_frozen_linux_uses_xdg_config_home_and_private_dir(clean_env, tmp_path):
    xdg = tmp_path / "xdg"
    clean_env.setattr(sys, "frozen", True, raising=False)
    clean_env.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    clean_env.setattr(sys, "platform", "linux")
    clean_env.delenv("APPDATA", raising=False)
    clean_env.setenv("XDG_CONFIG_HOME", str(xdg))

    config = _load_config()

    assert xdg / "DotaAICoach" == config.WRITABLE_DIR
    assert xdg / "DotaAICoach" / "logs" == config.LOGS_DIR
    if os.name == "posix":
        assert stat.S_IMODE(config.WRITABLE_DIR.stat().st_mode) == 0o700


def test_frozen_linux_defaults_to_home_config(clean_env, tmp_path):
    clean_env.setattr(sys, "frozen", True, raising=False)
    clean_env.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    clean_env.setattr(sys, "platform", "linux")
    clean_env.delenv("APPDATA", raising=False)
    clean_env.setenv("HOME", str(tmp_path / "home"))
    clean_env.setenv("USERPROFILE", str(tmp_path / "home"))
    # A relative XDG_CONFIG_HOME is ignored (XDG Base Directory spec).
    for value in ("", "relative/path"):
        clean_env.setenv("XDG_CONFIG_HOME", value)
        assert tmp_path / "home" / ".config" / "DotaAICoach" == _load_config().WRITABLE_DIR


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_player_database_is_owner_only(tmp_path):
    from app.player_store import PlayerStore

    store = PlayerStore(tmp_path / "player_data" / "coach.sqlite3")
    try:
        assert stat.S_IMODE(store.db_path.stat().st_mode) == 0o600
    finally:
        store.close()


@pytest.mark.parametrize("raw_port", ["not-a-port", "0", "70000"])
def test_invalid_port_falls_back_to_default(clean_env, raw_port):
    clean_env.setenv("DOTA_AI_BACKEND_PORT", raw_port)
    assert _load_config().BACKEND_PORT == 8000


def _load_backend_server() -> ModuleType:
    return _load_module(
        "_backend_server_under_test", BACKEND_DIR / "packaging" / "backend_server.py"
    )


def test_stdin_shutdown_command_stops_server():
    server = SimpleNamespace(should_exit=False)
    stream = io.StringIO("noise\nshutdown\nignored\n")

    _load_backend_server().watch_stdin_for_shutdown(server, stream)

    assert server.should_exit is True
    assert stream.readline() == "ignored\n"


@pytest.mark.parametrize("stream", [io.StringIO(""), None])
def test_stdin_eof_stops_server(stream):
    server = SimpleNamespace(should_exit=False)

    _load_backend_server().watch_stdin_for_shutdown(server, stream)

    assert server.should_exit is True


class _BrokenStdout(io.StringIO):
    def write(self, _text):
        raise BrokenPipeError("launcher is gone")


def test_stdin_eof_stops_server_even_when_stdout_is_broken(monkeypatch):
    # When the launcher is killed, stdout is a broken pipe too; stopping must not depend on it.
    monkeypatch.setattr(sys, "stdout", _BrokenStdout())
    server = SimpleNamespace(should_exit=False)

    _load_backend_server().watch_stdin_for_shutdown(server, io.StringIO(""))

    assert server.should_exit is True
