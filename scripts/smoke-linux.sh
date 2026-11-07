#!/usr/bin/env bash
# Smoke-tests the Linux build produced by scripts/build-linux.sh.
#
#   1. Backend: starts dota-ai-coach-backend on a free port (the way the app
#      does), checks /health, local-API auth, /overlay/recommendation, that
#      writable files land under $XDG_CONFIG_HOME/DotaAICoach (owner-only), then
#      stops it gracefully via stdin and expects exit code 0.
#   2. Unpacked app: dist/linux-unpacked/wardly --smoke-test=<result.json> under
#      xvfb-run (the app starts its bundled backend, checks /health, stops it and
#      exits 0; no backend process may be left behind).
#   3. Auto-update files: dist/latest-linux.yml names the AppImage and
#      resources/app-update.yml points at GitHub releases.
#   4. AppImage: the same smoke test through --appimage-extract-and-run (no FUSE
#      needed, as on CI).
#   5. pacman and deb: the archives hold the app, the backend, the desktop entry
#      and the icon, and carry the expected metadata.
#
# Needs: xvfb-run, python3, curl, bsdtar (libarchive-tools), dpkg-deb. The app
# runs with a throw-away HOME/XDG tree, so nothing of the real profile is used.
#
# Options: --timeout SECONDS (default 90), --skip-packages (steps 4-5).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_BIN="$REPO_ROOT/backend/dist/dota-ai-coach-backend/dota-ai-coach-backend"
DIST_DIR="$REPO_ROOT/frontend/launcher/dist"
APP_DIR="$DIST_DIR/linux-unpacked"
APP_BIN="$APP_DIR/wardly"
TIMEOUT=90
SKIP_PACKAGES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT="${2:?--timeout needs seconds}"; shift ;;
    --skip-packages) SKIP_PACKAGES=1 ;;
    -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

WORK="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/wardly-smoke.XXXXXX")"
export HOME="$WORK/home"
export XDG_CONFIG_HOME="$WORK/config"
export XDG_DATA_HOME="$WORK/data"
export XDG_CACHE_HOME="$WORK/cache"
unset APPDATA
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME"
USER_DATA="$XDG_CONFIG_HOME/DotaAICoach"

BACKEND_PID=""
cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  exec 3>&- 2>/dev/null || true
  # Keep the launcher log for the CI artifact step.
  if [ -f "$USER_DATA/logs/launcher.log" ]; then
    cp -f "$USER_DATA/logs/launcher.log" "$(dirname "$WORK")/launcher.log" 2>/dev/null || true
  fi
  for f in "$WORK"/smoke-*.json; do
    [ -e "$f" ] && cp -f "$f" "$(dirname "$WORK")/" 2>/dev/null || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
assert() { # assert "message" command...
  local message="$1"; shift
  if "$@"; then pass "$message"; else fail "$message"; fi
}
header() { printf '\n==> %s\n' "$1"; }

free_port() {
  python3 - <<'PY'
import socket
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
}

http_status() { # http_status METHOD URL [curl args...]
  local method="$1" url="$2"; shift 2
  curl -s -o /dev/null -w '%{http_code}' -X "$method" --max-time 5 "$@" "$url" || true
}

backend_left() { pgrep -f 'backend/dota-ai-coach-backend' >/dev/null 2>&1; }

assert_no_backend_left() {
  sleep 2
  if backend_left; then
    pgrep -af 'backend/dota-ai-coach-backend' >&2 || true
    fail "a dota-ai-coach-backend process is left running"
  fi
  pass "no dota-ai-coach-backend process left running"
}

# --- 1. backend ------------------------------------------------------------------

test_backend() {
  header "Backend: $BACKEND_BIN"
  assert "backend binary exists" test -x "$BACKEND_BIN"

  local port control gsi base out err
  port="$(free_port)"
  control="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  gsi="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  base="http://127.0.0.1:$port"
  out="$WORK/backend.out"
  err="$WORK/backend.err"

  mkfifo "$WORK/backend.stdin"
  DOTA_AI_BACKEND_PORT="$port" DOTA_AI_BACKEND_STDIN_CONTROL=1 \
    DOTA_AI_CONTROL_TOKEN="$control" DOTA_AI_GSI_TOKEN="$gsi" \
    "$BACKEND_BIN" <"$WORK/backend.stdin" >"$out" 2>"$err" &
  BACKEND_PID=$!
  exec 3>"$WORK/backend.stdin" # our end of stdin; closing it is the EOF signal

  local healthy=0 deadline=$((SECONDS + TIMEOUT))
  while [ $SECONDS -lt $deadline ] && kill -0 "$BACKEND_PID" 2>/dev/null; do
    if curl -sf --max-time 2 "$base/health" 2>/dev/null | grep -q '"status" *: *"ok"'; then healthy=1; break; fi
    sleep 0.5
  done
  if [ "$healthy" -ne 1 ]; then
    echo "--- backend stdout ---"; cat "$out"; echo "--- backend stderr ---"; cat "$err"
    fail "backend answers $base/health"
  fi
  pass "backend answers $base/health"

  assert "backend rejects an unauthorized local mutation (401)" \
    test "$(http_status POST "$base/session/reset")" = 401
  assert "backend rejects a foreign origin even with a control token (403)" \
    test "$(http_status POST "$base/session/reset" -H "Authorization: Bearer $control" \
      -H 'Origin: https://audit.invalid' -H 'Content-Type: application/json' -d '{}')" = 403

  local overlay
  overlay="$(curl -sf --max-time 5 -H "Authorization: Bearer $control" "$base/overlay/recommendation")"
  assert "/overlay/recommendation returns a status" \
    python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1]).get("status") else 1)' "$overlay"

  local recording session_dir
  recording="$(curl -sf --max-time 5 -X POST -H "Authorization: Bearer $control" "$base/session-recording/start")"
  curl -sf --max-time 5 -X POST -H "Authorization: Bearer $control" "$base/session-recording/stop" >/dev/null
  curl -sf --max-time 5 -X POST -H 'Content-Type: application/json' "$base/gsi" -o /dev/null \
    -d "{\"auth\":{\"token\":\"$gsi\"},\"provider\":{\"name\":\"Dota 2\"},\"map\":{\"game_state\":\"DOTA_GAMERULES_STATE_PRE_GAME\"}}"
  session_dir="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["session_dir"])' "$recording")"
  assert "session records go to $USER_DATA ($session_dir)" test "${session_dir#"$USER_DATA"/}" != "$session_dir"
  assert "session record folder was created" test -d "$session_dir"
  assert "user data folder is owner-only (0700)" test "$(stat -c %a "$USER_DATA")" = 700
  local db
  db="$(find "$USER_DATA" -name '*.sqlite3' -print -quit)"
  if [ -n "$db" ]; then
    assert "SQLite database is owner-only (0600)" test "$(stat -c %a "$db")" = 600
  fi

  printf 'shutdown\n' >&3
  exec 3>&-
  local exited=0
  for _ in $(seq 1 30); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then exited=1; break; fi
    sleep 0.5
  done
  assert "backend exits after the stdin shutdown command" test "$exited" -eq 1
  local code=0
  wait "$BACKEND_PID" || code=$?
  BACKEND_PID=""
  assert "backend exit code is 0 (got $code)" test "$code" -eq 0
}

# --- 2/4. the app ----------------------------------------------------------------

# The Chromium sandbox needs either a SUID chrome-sandbox or unprivileged user
# namespaces; neither holds for an unpacked app in CI (or as root), so skip it
# there. This does not weaken what is tested: the sandbox is Chromium's.
sandbox_args() {
  if [ "$(id -u)" -eq 0 ] || ! unshare -Ur true 2>/dev/null; then echo "--no-sandbox"; fi
}

test_app() { # test_app LABEL COMMAND...
  local label="$1"; shift
  header "App smoke test ($label): $*"
  local result="$WORK/smoke-$label.json" code=0
  rm -f "$result"
  # shellcheck disable=SC2046 # sandbox_args is empty or one flag
  timeout "$TIMEOUT" xvfb-run -a -s "-screen 0 1920x1080x24" "$@" --smoke-test="$result" $(sandbox_args) || code=$?
  if [ "$code" -eq 124 ]; then
    pkill -f 'backend/dota-ai-coach-backend' 2>/dev/null || true
    fail "$label did not finish the smoke test within ${TIMEOUT}s"
  fi
  assert "$label wrote its result file" test -f "$result"
  python3 - "$result" <<'PY' || fail "$label smoke test failed"
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))
for step in result.get("steps", []):
    print("  {} {} {}".format("ok  " if step.get("ok") else "FAIL", step.get("name"), step.get("detail", "")))
if not result.get("ok"):
    print(result.get("logs", ""))
sys.exit(0 if result.get("ok") else 1)
PY
  pass "$label smoke test passed"
  assert "$label exit code is 0 (got $code)" test "$code" -eq 0
  assert_no_backend_left
}

# --- 3. auto-update files --------------------------------------------------------

test_update_files() {
  header "Auto-update files"
  local latest="$DIST_DIR/latest-linux.yml" appimage
  assert "dist/latest-linux.yml exists (electron-updater feed)" test -f "$latest"
  appimage="$(basename "$(ls "$DIST_DIR"/Wardly-*-x86_64.AppImage | head -n 1)")"
  assert "latest-linux.yml points at $appimage" grep -qF "$appimage" "$latest"
  local config="$APP_DIR/resources/app-update.yml"
  assert "resources/app-update.yml exists" test -f "$config"
  assert "app-update.yml uses GitHub releases" \
    bash -c 'grep -Eq "provider:[[:space:]]*github" "$1" && grep -Eq "repo:[[:space:]]*wardly" "$1"' _ "$config"
}

# --- 5. pacman and deb -----------------------------------------------------------

has_entry() { grep -Eq "$1" <<<"$2"; }

test_pacman() {
  local pkg listing info desktop
  pkg="$(ls "$DIST_DIR"/Wardly-*-x86_64.pacman | head -n 1)"
  header "pacman package: $pkg"
  listing="$(bsdtar -tf "$pkg")"
  for entry in '^opt/Wardly/wardly$' '^opt/Wardly/resources/backend/dota-ai-coach-backend$' \
    '^opt/Wardly/resources/app\.asar$' '^usr/share/applications/wardly\.desktop$' \
    '^usr/share/icons/hicolor/256x256/apps/wardly\.png$'; do
    assert "pacman package contains ${entry//\\/}" has_entry "$entry" "$listing"
  done
  info="$(bsdtar -xOf "$pkg" .PKGINFO)"
  assert "pacman pkgname is wardly" has_entry '^pkgname = wardly$' "$info"
  assert "pacman depends on gtk3, nss and libsecret" bash -c \
    'grep -q "^depend = gtk3$" <<<"$1" && grep -q "^depend = nss$" <<<"$1" && grep -q "^depend = libsecret$" <<<"$1"' _ "$info"
  assert "pacman has no hard dependency on optional tools" bash -c \
    '! grep -Eq "^depend = (speech-dispatcher|xorg-xprop|xorg-xwininfo|libayatana-appindicator)" <<<"$1"' _ "$info"
  assert "pacman lists optional dependencies" has_entry '^optdepend = speech-dispatcher' "$info"
  desktop="$(bsdtar -xOf "$pkg" usr/share/applications/wardly.desktop)"
  check_desktop_entry "$desktop"
}

test_deb() {
  local pkg listing info desktop
  pkg="$(ls "$DIST_DIR"/Wardly_*_amd64.deb | head -n 1)"
  header "deb package: $pkg"
  listing="$(dpkg-deb -c "$pkg")"
  for entry in ' \./opt/Wardly/wardly$' ' \./opt/Wardly/resources/backend/dota-ai-coach-backend$' \
    ' \./opt/Wardly/resources/app\.asar$' ' \./usr/share/applications/wardly\.desktop$' \
    ' \./usr/share/icons/hicolor/256x256/apps/wardly\.png$'; do
    assert "deb contains ${entry//\\/}" has_entry "$entry" "$listing"
  done
  info="$(dpkg-deb -f "$pkg")"
  assert "deb Package is wardly" has_entry '^Package: wardly$' "$info"
  assert "deb Architecture is amd64" has_entry '^Architecture: amd64$' "$info"
  assert "deb depends on libsecret and xdg-utils" bash -c \
    'grep -E "^Depends:" <<<"$1" | grep -q libsecret-1-0 && grep -E "^Depends:" <<<"$1" | grep -q xdg-utils' _ "$info"
  assert "deb has no hard dependency on speech-dispatcher" bash -c \
    '! grep -E "^Depends:" <<<"$1" | grep -q speech-dispatcher' _ "$info"
  assert "deb recommends speech-dispatcher" bash -c 'grep -E "^Recommends:" <<<"$1" | grep -q speech-dispatcher' _ "$info"
  desktop="$(dpkg-deb --fsys-tarfile "$pkg" | bsdtar -xOf - ./usr/share/applications/wardly.desktop)"
  check_desktop_entry "$desktop"
}

check_desktop_entry() {
  local desktop="$1"
  assert "desktop entry is Name=Wardly" has_entry '^Name=Wardly$' "$desktop"
  assert "desktop entry is in the Game category" has_entry '^Categories=.*Game' "$desktop"
  assert "desktop entry has a StartupWMClass" has_entry '^StartupWMClass=.+' "$desktop"
  assert "desktop entry starts /opt/Wardly/wardly" has_entry '^Exec="?/opt/Wardly/wardly' "$desktop"
}

# ---------------------------------------------------------------------------------

test_backend
assert_no_backend_left
assert "unpacked app exists ($APP_BIN)" test -x "$APP_BIN"
test_app "linux-unpacked" "$APP_BIN"
test_update_files
if [ "$SKIP_PACKAGES" -eq 0 ]; then
  appimage="$(ls "$DIST_DIR"/Wardly-*-x86_64.AppImage | head -n 1)"
  assert "AppImage exists" test -x "$appimage"
  test_app "appimage" "$appimage" --appimage-extract-and-run
  test_pacman
  test_deb
fi

printf '\nAll Linux smoke tests passed.\n'
