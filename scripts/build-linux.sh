#!/usr/bin/env bash
# One-command Linux build of Wardly (x86_64): AppImage, pacman and deb.
#
#   1. Creates backend/.venv-build (if missing) and installs the hashed
#      backend/requirements-build.txt.
#   2. Builds the backend with PyInstaller (backend/dist/dota-ai-coach-backend/).
#   3. Installs the Electron app dependencies (npm ci) in frontend/launcher.
#   4. Packs the Electron app with electron-builder:
#        frontend/launcher/dist/Wardly-<version>-x86_64.AppImage
#        frontend/launcher/dist/Wardly-<version>-x86_64.pacman
#        frontend/launcher/dist/Wardly_<version>_amd64.deb
#        frontend/launcher/dist/latest-linux.yml      (AppImage auto-update feed)
#        frontend/launcher/dist/linux-unpacked/wardly (unpacked app)
#
# Needs: Python 3.11+, Node.js 22.12+ with npm, bsdtar and zstd (Ubuntu/Debian:
# libarchive-tools zstd; Arch: libarchive zstd; used by the pacman target). For the
# smoke test also xvfb (xvfb-run) and dpkg-deb. Build on the oldest distro you
# want to support (CI: ubuntu-22.04): the PyInstaller backend needs a glibc at
# least as new as the build machine's.
#
# Options:
#   --skip-backend   reuse an existing backend/dist build (frontend-only rebuild)
#   --python PATH    Python used to create backend/.venv-build (default: python3)
#   --targets "A B"  electron-builder targets (default: "AppImage pacman deb")
#   -h, --help       this text
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
LAUNCHER_DIR="$REPO_ROOT/frontend/launcher"
VENV_PYTHON="$BACKEND_DIR/.venv-build/bin/python"
BACKEND_BIN="$BACKEND_DIR/dist/dota-ai-coach-backend/dota-ai-coach-backend"

PYTHON="${PYTHON:-python3}"
SKIP_BACKEND=0
TARGETS="AppImage pacman deb"

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-backend) SKIP_BACKEND=1 ;;
    --python) PYTHON="${2:?--python needs a path}"; shift ;;
    --targets) TARGETS="${2:?--targets needs a list}"; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n==> %s\n' "$1"; }

if [ "$(uname -s)" != "Linux" ]; then
  echo "This script builds the Linux packages and must run on Linux." >&2
  exit 1
fi
case "$(uname -m)" in
  x86_64) ;;
  *) echo "Only x86_64 is supported (got $(uname -m))." >&2; exit 1 ;;
esac
if [[ " $TARGETS " == *" pacman "* ]]; then
  command -v bsdtar >/dev/null 2>&1 || { echo "bsdtar is required for the pacman target (Ubuntu/Debian: libarchive-tools, Arch: libarchive)." >&2; exit 1; }
  command -v zstd >/dev/null 2>&1 || { echo "zstd is required for the pacman target (package: zstd)." >&2; exit 1; }
fi

# No code signing on Linux: do not let electron-builder look for a certificate.
export CSC_IDENTITY_AUTO_DISCOVERY=false

if [ "$SKIP_BACKEND" -eq 0 ]; then
  cd "$BACKEND_DIR"
  if [ ! -x "$VENV_PYTHON" ]; then
    step "Create backend/.venv-build"
    "$PYTHON" -m venv .venv-build
  fi
  step "Install backend build requirements"
  "$VENV_PYTHON" -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements-build.txt
  step "Check backend build requirements"
  "$VENV_PYTHON" -m pip check
  rm -rf build dist
  step "Build backend with PyInstaller"
  "$VENV_PYTHON" -m PyInstaller --noconfirm --clean packaging/dota_ai_coach_backend.spec
fi

if [ ! -x "$BACKEND_BIN" ]; then
  echo "Backend executable was not found: $BACKEND_BIN" >&2
  exit 1
fi

cd "$LAUNCHER_DIR"
step "Install Electron app dependencies"
npm ci --no-audit --no-fund
rm -rf dist
step "Build Electron app + packages ($TARGETS)"
# shellcheck disable=SC2086 # the target list is split on purpose
npx --no-install electron-builder --linux $TARGETS --publish never

echo
echo "Build finished:"
for file in dist/*.AppImage dist/*.pacman dist/*.deb dist/latest-linux.yml; do
  [ -e "$file" ] && printf '  %-60s %s\n' "$LAUNCHER_DIR/$file" "$(du -h "$file" | cut -f1)"
done
echo "  app: $LAUNCHER_DIR/dist/linux-unpacked/wardly"
