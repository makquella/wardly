"""
config.py — paths and global settings for the application.

Two runtime layouts are supported:

* Source checkout: read-only data comes from ``<repo>/data`` and writable files
  (logs, session records, GSI debug samples) live under ``backend/``.
* Frozen PyInstaller build (``sys.frozen``): read-only data is bundled next to
  the modules in ``sys._MEIPASS`` and writable files go to the per-user
  ``%APPDATA%\\DotaAICoach`` folder, because the install directory may be
  read-only.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

APP_DIR_NAME = "DotaAICoach"

IS_FROZEN = bool(getattr(sys, "frozen", False))

# Root of the repository (app/ -> backend/ -> dota-ai-coach/)
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"


def _resource_root() -> Path:
    """Directory that contains the read-only ``data/`` tree."""
    if IS_FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return REPO_ROOT


def _user_data_dir() -> Path:
    """Writable per-user directory for the frozen app (``%APPDATA%\\DotaAICoach``)."""
    appdata = os.getenv("APPDATA", "").strip()
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / APP_DIR_NAME


RESOURCE_ROOT = _resource_root()
DATA_DIR = RESOURCE_ROOT / "data"

# Root for logs, recordings and other files the backend writes at runtime.
WRITABLE_DIR = _user_data_dir() if IS_FROZEN else BACKEND_DIR

if IS_FROZEN:
    # Packaged users keep their optional LLM keys next to the logs.
    load_dotenv(WRITABLE_DIR / ".env", override=False)
else:
    load_dotenv(BACKEND_DIR / ".env", override=False)
    load_dotenv(REPO_ROOT / ".env", override=False)

# Where Markdown knowledge-base files live
KNOWLEDGE_BASE_DIR = DATA_DIR / "knowledge_base"
HERO_PROFILES_PATH = DATA_DIR / "heroes" / "hero_profiles.json"
ITEM_TIMING_RULES_PATH = DATA_DIR / "meta" / "item_timing_rules.json"

# Where per-request log files are written
LOGS_DIR = WRITABLE_DIR / "logs"

# HTTP server address. The desktop launcher picks a free port and passes it in.
BACKEND_HOST = os.getenv("DOTA_AI_BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
try:
    BACKEND_PORT = int(os.getenv("DOTA_AI_BACKEND_PORT", "8000"))
except ValueError:
    BACKEND_PORT = 8000
if not 0 < BACKEND_PORT < 65536:
    BACKEND_PORT = 8000

# How many RAG paragraphs to return
RAG_TOP_K = 3

# Optional runtime LLM provider settings
USE_LLM = os.getenv("USE_LLM", "false").lower() == "true"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "disabled").strip().lower()

try:
    LLM_TIMEOUT = max(1.0, min(float(os.getenv("LLM_TIMEOUT", "6")), 30.0))
except ValueError:
    LLM_TIMEOUT = 6.0

try:
    LLM_MAX_TOKENS = max(1, min(int(os.getenv("LLM_MAX_TOKENS", "350")), 2000))
except ValueError:
    LLM_MAX_TOKENS = 350

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free").strip()

# Google Gemini (AI Studio key); used by the post-match AI coach only.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

LLAMACPP_BASE_URL = os.getenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8080").strip().rstrip("/")
LLAMACPP_MODEL = os.getenv("LLAMACPP_MODEL", "local-gpt-oss-20b").strip()

# Optional live GSI payload inspection. Raw samples can be noisy and should stay local.
GSI_DEBUG_LOG = os.getenv("GSI_DEBUG_LOG", "false").strip().lower() == "true"
GSI_DEBUG_SAMPLES_DIR = WRITABLE_DIR / "gsi_debug_samples"

# Live Dota GSI readiness and recording.
# How often coaching advice may appear: calm | normal | active (the launcher
# passes the player's choice; see app/scheduler/frequency.py).
ADVICE_FREQUENCY = os.getenv("DOTA_AI_ADVICE_FREQUENCY", "normal").strip().lower()
# The player's position for timers and role tips: auto | carry | mid | offlane |
# support (app/live_role.py), and whether the overlay shows map hints at all.
ADVICE_ROLE = os.getenv("DOTA_AI_ROLE", "auto").strip().lower()
MAP_HINTS = os.getenv("DOTA_AI_MAP_HINTS", "true").strip().lower() != "false"
# A week of match recordings kept on disk (match_records.py; off unless switched on).
MATCH_RECORDS_ENABLED = os.getenv("DOTA_AI_MATCH_RECORDS", "false").strip().lower() == "true"
LIVE_CONSERVATIVE_MODE = os.getenv("LIVE_CONSERVATIVE_MODE", "true").strip().lower() != "false"
try:
    GSI_STALE_SECONDS = max(1.0, float(os.getenv("GSI_STALE_SECONDS", "5")))
except ValueError:
    GSI_STALE_SECONDS = 5.0
SESSION_RECORDS_DIR = Path(os.getenv("SESSION_RECORDS_DIR", str(WRITABLE_DIR / "session_records")))


def path_from_env(name: str, default: Path) -> Path:
    """An empty value (e.g. `NAME=` copied from .env.example) means "use the default"."""
    value = os.getenv(name, "").strip()
    return Path(value) if value else default


# Player profile, match history and post-match reviews (SQLite + OpenDota).
PLAYER_DATA_DIR = path_from_env("PLAYER_DATA_DIR", WRITABLE_DIR / "player_data")
OPENDOTA_ENABLED = os.getenv("OPENDOTA_ENABLED", "true").strip().lower() != "false"
OPENDOTA_API_URL = os.getenv("OPENDOTA_API_URL", "https://api.opendota.com/api").strip().rstrip("/")
OPENDOTA_API_KEY = os.getenv("OPENDOTA_API_KEY", "").strip()
# Wardly's shared cache of OpenDota reference data (hero stats, items, per-hero
# timings), tried before OpenDota. Set to an empty value to switch it off.
_opendota_cache_url = os.getenv("WARDLY_OPENDOTA_CACHE_URL")
OPENDOTA_CACHE_URL = (
    "https://api.luhovyimvp.dev/v1/opendota"
    if _opendota_cache_url is None
    else _opendota_cache_url.strip().rstrip("/")
)
