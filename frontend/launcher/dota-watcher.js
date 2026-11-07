const { spawn } = require("node:child_process");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

// Watches whether dota2.exe is running, whether its window is the active
// (foreground, not minimized) window, where that window is (so the overlay can
// follow Dota to its monitor) and whether Dota runs in exclusive fullscreen,
// where no other window can be drawn on top of it.
//
// Windows: one long-lived hidden PowerShell process calls user32
// GetForegroundWindow/GetWindowThreadProcessId/IsIconic/GetClientRect and
// shell32 SHQueryUserNotificationState in a loop and prints a JSON line
// whenever the state changes (plus a heartbeat line every ~20 polls so the
// launcher can tell it is alive). No native Node modules are needed, and the
// helper exits by itself when the launcher process disappears.
// Linux: /proc is scanned for a "dota2" process. When an X display (X11 or
// XWayland, where Dota runs) and the xprop + xwininfo tools exist, they give the
// rest: the active window (_NET_ACTIVE_WINDOW) is Dota's, its absolute
// geometry, and _NET_WM_STATE_FULLSCREEN. Without them focus is not tracked
// (supported: false) and the overlay follows its on/off switch only.

const WINDOWS_POLL_RUNNING_MS = 300;
const WINDOWS_POLL_IDLE_MS = 1500;
const LINUX_POLL_MS = 2000;
const LINUX_POLL_RUNNING_MS = 1000;
const LINUX_TOOL_TIMEOUT_MS = 1500;
// Consecutive failed X queries before focus tracking is reported unavailable.
const LINUX_MAX_TOOL_FAILURES = 5;
const MAX_FAST_FAILURES = 5;

// SHQueryUserNotificationState returns QUNS_RUNNING_D3D_FULL_SCREEN (3) while
// a Direct3D exclusive-fullscreen app is in front. The flag is sampled while
// Dota is focused and kept until Dota exits, so alt-tab does not clear it.
// The helper is DPI aware: "rect" is in physical screen pixels.
const WINDOWS_WATCH_SCRIPT = String.raw`
$ErrorActionPreference = 'Stop'
$parentPid = __PARENT_PID__
Add-Type -Namespace DotaAICoach -Name Win32 -MemberDefinition @'
[System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr hWnd, out uint processId);
[DllImport("user32.dll")] public static extern bool IsIconic(System.IntPtr hWnd);
public struct POINT { public int X; public int Y; }
[DllImport("user32.dll")] public static extern bool GetClientRect(System.IntPtr hWnd, out RECT rect);
[DllImport("user32.dll")] public static extern bool ClientToScreen(System.IntPtr hWnd, ref POINT point);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
[DllImport("shell32.dll")] public static extern int SHQueryUserNotificationState(out int state);
'@
try { [void][DotaAICoach.Win32]::SetProcessDPIAware() } catch { }
$last = ''
$ticks = 0
$fullscreen = $false
$rect = $null
while ($true) {
  try { $null = [System.Diagnostics.Process]::GetProcessById($parentPid) } catch { exit 0 }
  $running = $false
  $focused = $false
  $exe = ''
  $procs = [System.Diagnostics.Process]::GetProcessesByName('dota2')
  if ($procs.Length -gt 0) {
    $running = $true
    $hwnd = [DotaAICoach.Win32]::GetForegroundWindow()
    [uint32]$fgPid = 0
    [void][DotaAICoach.Win32]::GetWindowThreadProcessId($hwnd, [ref]$fgPid)
    foreach ($p in $procs) {
      if ($p.Id -eq $fgPid -and -not [DotaAICoach.Win32]::IsIconic($hwnd)) { $focused = $true }
      if (-not $exe) { try { $exe = [string]$p.Path } catch { } }
      $main = [System.IntPtr]::Zero
      try { $main = $p.MainWindowHandle } catch { }
      if ($main -ne [System.IntPtr]::Zero -and -not [DotaAICoach.Win32]::IsIconic($main)) {
        $r = New-Object DotaAICoach.Win32+RECT
        $o = New-Object DotaAICoach.Win32+POINT
        if ([DotaAICoach.Win32]::GetClientRect($main, [ref]$r) -and $r.Right -gt 0 -and [DotaAICoach.Win32]::ClientToScreen($main, [ref]$o)) {
          $rect = @($o.X, $o.Y, ($o.X + $r.Right), ($o.Y + $r.Bottom))
        }
      }
      $p.Dispose()
    }
    if ($focused) {
      [int]$quns = 0
      try {
        if ([DotaAICoach.Win32]::SHQueryUserNotificationState([ref]$quns) -eq 0) { $fullscreen = ($quns -eq 3) }
      } catch { }
    }
  } else {
    $fullscreen = $false
    $rect = $null
  }
  $line = [ordered]@{ running = $running; focused = $focused; path = $exe; fullscreen = $fullscreen; rect = $rect } | ConvertTo-Json -Compress
  $ticks++
  if ($line -ne $last -or $ticks -ge 20) {
    [Console]::Out.WriteLine($line)
    [Console]::Out.Flush()
    $last = $line
    $ticks = 0
  }
  if ($running) { Start-Sleep -Milliseconds __POLL_RUNNING_MS__ } else { Start-Sleep -Milliseconds __POLL_IDLE_MS__ }
}
`;

function windowsWatchScript(parentPid) {
  return WINDOWS_WATCH_SCRIPT.replace("__PARENT_PID__", String(Number(parentPid) || 0))
    .replace("__POLL_RUNNING_MS__", String(WINDOWS_POLL_RUNNING_MS))
    .replace("__POLL_IDLE_MS__", String(WINDOWS_POLL_IDLE_MS));
}

function encodePowerShell(script) {
  return Buffer.from(script, "utf16le").toString("base64");
}

function parseWatcherLine(line) {
  try {
    const data = JSON.parse(String(line).trim());
    if (!data || typeof data !== "object") {
      return null;
    }
    const running = Boolean(data.running);
    return {
      running,
      focused: running && Boolean(data.focused),
      exePath: typeof data.path === "string" ? data.path : "",
      exclusiveFullscreen: running && Boolean(data.fullscreen),
      windowRect: running ? parseRect(data.rect) : null
    };
  } catch {
    return null;
  }
}

// [left, top, right, bottom] in physical pixels -> { x, y, width, height }.
function parseRect(value) {
  if (!Array.isArray(value) || value.length !== 4 || !value.every(Number.isFinite)) {
    return null;
  }
  const [left, top, right, bottom] = value;
  if (right <= left || bottom <= top) {
    return null;
  }
  return { x: left, y: top, width: right - left, height: bottom - top };
}

function powershellPath(env = process.env) {
  const systemRoot = env.SystemRoot || env.windir || "C:\\Windows";
  const candidate = path.win32.join(systemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  return fs.existsSync(candidate) ? candidate : "powershell.exe";
}

// [{ pid, exe }] of every running "dota2" process; [] when none (or no /proc).
function findDotaProcessesOnLinux(procDir = "/proc") {
  let entries = [];
  try {
    entries = fs.readdirSync(procDir);
  } catch {
    return [];
  }
  const found = [];
  for (const entry of entries) {
    if (!/^\d+$/.test(entry)) {
      continue;
    }
    try {
      if (fs.readFileSync(path.join(procDir, entry, "comm"), "utf8").trim() !== "dota2") {
        continue;
      }
    } catch {
      // Process exited while scanning.
      continue;
    }
    let exe = "";
    try {
      exe = fs.readlinkSync(path.join(procDir, entry, "exe"));
    } catch {
      // Not readable (another user's process): the pid alone is enough.
    }
    found.push({ pid: Number(entry), exe });
  }
  return found;
}

function isDotaRunningOnLinux(procDir = "/proc") {
  return findDotaProcessesOnLinux(procDir).length > 0;
}

// First executable called `name` on PATH, or "".
function findOnPath(name, envPath = process.env.PATH || "") {
  for (const dir of String(envPath).split(path.delimiter)) {
    if (!dir) {
      continue;
    }
    const candidate = path.join(dir, name);
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      if (fs.statSync(candidate).isFile()) {
        return candidate;
      }
    } catch {
      // Not here.
    }
  }
  return "";
}

// "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4a00007" -> 0x4a00007 (0 = none).
function parseActiveWindow(output) {
  const match = String(output || "").match(/window id # (0x[0-9a-fA-F]+)/);
  if (!match) {
    return null;
  }
  const id = Number.parseInt(match[1], 16);
  return id > 0 ? match[1].toLowerCase() : "";
}

// The output of `xprop -id <w> _NET_WM_PID WM_CLASS _NET_WM_STATE`.
function parseWindowProps(output) {
  const text = String(output || "");
  const pid = text.match(/_NET_WM_PID\(CARDINAL\) = (\d+)/);
  const classes = text.match(/WM_CLASS\(STRING\) = (.*)/);
  const state = text.match(/_NET_WM_STATE\(ATOM\) = (.*)/);
  const states = state ? state[1].split(",").map((item) => item.trim()) : [];
  return {
    pid: pid ? Number(pid[1]) : 0,
    classes: classes ? [...classes[1].matchAll(/"([^"]*)"/g)].map((item) => item[1].toLowerCase()) : [],
    fullscreen: states.includes("_NET_WM_STATE_FULLSCREEN"),
    hidden: states.includes("_NET_WM_STATE_HIDDEN")
  };
}

// `xwininfo -id <w>`: the client area in absolute screen pixels.
function parseXwininfo(output) {
  const text = String(output || "");
  const pick = (label) => {
    const match = text.match(new RegExp(`^\\s*${label}:\\s*(-?\\d+)`, "m"));
    return match ? Number(match[1]) : NaN;
  };
  const x = pick("Absolute upper-left X");
  const y = pick("Absolute upper-left Y");
  const width = pick("Width");
  const height = pick("Height");
  return parseRect([x, y, x + width, y + height]);
}

// Runs a tool with an argv array (no shell), time-boxed; never rejects.
function runTool(spawnImpl, command, args, { env, timeoutMs = LINUX_TOOL_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    let child;
    let out = "";
    let done = false;
    let timer = null;
    const finish = (ok) => {
      if (done) {
        return;
      }
      done = true;
      clearTimeout(timer);
      resolve({ ok, stdout: out });
    };
    try {
      child = spawnImpl(command, args, { env, stdio: ["ignore", "pipe", "ignore"] });
    } catch {
      finish(false);
      return;
    }
    timer = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        // Already gone.
      }
      finish(false);
    }, timeoutMs);
    timer.unref?.();
    child.stdout?.on("data", (chunk) => {
      out += String(chunk);
    });
    child.on("error", () => finish(false));
    child.on("close", (code) => finish(code === 0));
  });
}

/**
 * state: { supported, running, focused, exePath, exclusiveFullscreen, windowRect }
 *   supported           - focus tracking works (Windows; Linux with an X display
 *                         and xprop + xwininfo).
 *   exclusiveFullscreen - Dota was last seen in exclusive fullscreen (no overlay
 *                         can be drawn over it); reset when Dota exits.
 *   windowRect          - Dota's window in physical pixels, or null.
 * Emits "change" with the new state.
 */
function createDotaWatcher({
  platform = process.platform,
  log = () => {},
  spawnImpl = spawn,
  parentPid = process.pid,
  env = process.env,
  procDir = "/proc",
  findTool = (name) => findOnPath(name, env.PATH)
} = {}) {
  const emitter = new EventEmitter();
  let state = {
    supported: platform === "win32",
    running: false,
    focused: false,
    exePath: "",
    exclusiveFullscreen: false,
    windowRect: null
  };
  let child = null;
  let stopped = true;
  let restartTimer = null;
  let linuxTimer = null;
  let fastFailures = 0;

  function update(patch) {
    const next = { ...state, ...patch };
    if (next.exePath === "" && state.exePath && next.running) {
      next.exePath = state.exePath;
    }
    const changed =
      ["supported", "running", "focused", "exePath", "exclusiveFullscreen"].some((key) => next[key] !== state[key]) ||
      JSON.stringify(next.windowRect) !== JSON.stringify(state.windowRect);
    state = next;
    if (changed) {
      emitter.emit("change", { ...state });
    }
  }

  function startWindows() {
    const startedAt = Date.now();
    let sawOutput = false;
    try {
      child = spawnImpl(
        powershellPath(),
        [
          "-NoLogo",
          "-NoProfile",
          "-NonInteractive",
          "-ExecutionPolicy",
          "Bypass",
          "-EncodedCommand",
          encodePowerShell(windowsWatchScript(parentPid))
        ],
        { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] }
      );
    } catch (error) {
      log(`Dota watcher could not start PowerShell: ${error.message}`);
      giveUp();
      return;
    }
    const current = child;
    readline.createInterface({ input: current.stdout }).on("line", (line) => {
      const parsed = parseWatcherLine(line);
      if (parsed) {
        sawOutput = true;
        fastFailures = 0;
        update(parsed);
        emitter.emit("report", { ...state });
      }
    });
    current.stderr.on("data", (chunk) => log(`Dota watcher: ${String(chunk).trim()}`));
    let ended = false;
    const handleEnd = (code) => {
      if (ended) {
        return;
      }
      ended = true;
      if (child === current) {
        child = null;
      }
      if (stopped) {
        return;
      }
      update({ running: false, focused: false, exclusiveFullscreen: false, windowRect: null });
      if (!sawOutput || Date.now() - startedAt < 5000) {
        fastFailures += 1;
      }
      if (fastFailures >= MAX_FAST_FAILURES) {
        giveUp();
        return;
      }
      log(`Dota watcher exited (code ${code}); restarting.`);
      restartTimer = setTimeout(startWindows, 3000);
      restartTimer.unref?.();
    };
    current.on("error", (error) => {
      log(`Dota watcher error: ${error.message}`);
      if (!current.pid) {
        // Spawn failed (e.g. PowerShell missing); "exit" will not follow.
        handleEnd(null);
      }
    });
    current.on("exit", handleEnd);
  }

  function giveUp() {
    log("Dota focus tracking is unavailable; the overlay will follow its on/off switch only.");
    update({ supported: false, running: false, focused: false, exclusiveFullscreen: false, windowRect: null });
    emitter.emit("report", { ...state });
  }

  // X11 queries (xprop/xwininfo) are looked up once; without them, or without a
  // display, only the process scan runs, as before.
  let xTools = null;
  let xFailures = 0;
  let linuxBusy = false;
  let idleTicks = 0;
  let lastDotaWindow = null;
  let linuxFullscreen = false;
  let linuxRect = null;

  function resolveXTools() {
    if (xTools) {
      return xTools;
    }
    xTools = { xprop: "", xwininfo: "" };
    if (!env.DISPLAY) {
      log("Dota focus tracking is off: no X display (X11 or XWayland). The overlay follows its on/off switch only.");
      return xTools;
    }
    const xprop = findTool("xprop");
    const xwininfo = findTool("xwininfo");
    if (!xprop || !xwininfo) {
      log(
        `Dota focus tracking is off: ${[!xprop && "xprop", !xwininfo && "xwininfo"].filter(Boolean).join(" and ")} not found on PATH ` +
          "(Arch: xorg-xprop xorg-xwininfo; Debian/Ubuntu: x11-utils). The overlay follows its on/off switch only."
      );
      return xTools;
    }
    xTools = { xprop, xwininfo };
    return xTools;
  }

  const xEnv = () => ({ ...env, LC_ALL: "C", LANG: "C" });

  // One X query round: is the active window Dota's, where it is, is it fullscreen.
  // Returns { focused, rect?, fullscreen? } or null when X did not answer.
  async function queryX(tools, dota) {
    const root = await runTool(spawnImpl, tools.xprop, ["-root", "_NET_ACTIVE_WINDOW"], { env: xEnv() });
    if (!root.ok) {
      return null;
    }
    const active = parseActiveWindow(root.stdout);
    if (active === null) {
      return null;
    }
    if (!active) {
      return { focused: false };
    }
    const props = await runTool(
      spawnImpl,
      tools.xprop,
      ["-id", active, "_NET_WM_PID", "WM_CLASS", "_NET_WM_STATE"],
      { env: xEnv() }
    );
    if (!props.ok) {
      // The window vanished between the two calls: not an X failure.
      return { focused: false };
    }
    const info = parseWindowProps(props.stdout);
    const isDota = dota.some((item) => item.pid === info.pid) || info.classes.includes("dota2");
    if (!isDota || info.hidden) {
      return { focused: false };
    }
    lastDotaWindow = active;
    const result = { focused: true, fullscreen: info.fullscreen };
    const geometry = await runTool(spawnImpl, tools.xwininfo, ["-id", active], { env: xEnv() });
    if (geometry.ok) {
      result.rect = parseXwininfo(geometry.stdout);
    }
    return result;
  }

  async function linuxTick() {
    if (linuxBusy || stopped) {
      return;
    }
    linuxBusy = true;
    try {
      const dota = findDotaProcessesOnLinux(procDir);
      const running = dota.length > 0;
      const exePath = (dota.find((item) => item.exe) || {}).exe || "";
      const tools = resolveXTools();
      if (!running) {
        lastDotaWindow = null;
        linuxFullscreen = false;
        linuxRect = null;
        update({
          running: false,
          focused: false,
          exclusiveFullscreen: false,
          windowRect: null,
          // Probe the display even before Dota starts, so the overlay is in
          // focus-driven mode (hidden on the desktop) from the first report.
          supported: tools.xprop ? await idleProbe(tools) : false
        });
      } else if (!tools.xprop) {
        update({ running: true, focused: true, exePath, supported: false, windowRect: null });
      } else {
        const result = await queryX(tools, dota);
        if (stopped) {
          return;
        }
        if (result === null) {
          xFailures += 1;
          if (xFailures >= LINUX_MAX_TOOL_FAILURES && state.supported) {
            log("Dota focus tracking stopped: the X server does not answer xprop.");
          }
          update({ running: true, exePath, supported: xFailures < LINUX_MAX_TOOL_FAILURES });
        } else {
          xFailures = 0;
          if (result.focused) {
            // Sampled while Dota is in front, kept until it exits (as on Windows).
            linuxFullscreen = Boolean(result.fullscreen);
            if (result.rect) {
              linuxRect = result.rect;
            }
          }
          update({
            running: true,
            focused: result.focused,
            exePath,
            supported: true,
            exclusiveFullscreen: linuxFullscreen,
            windowRect: linuxRect
          });
        }
      }
    } catch (error) {
      log(`Dota watcher: ${error.message}`);
    } finally {
      linuxBusy = false;
    }
    if (!stopped) {
      emitter.emit("report", { ...state });
      clearTimeout(linuxTimer);
      linuxTimer = setTimeout(linuxTick, state.running ? LINUX_POLL_RUNNING_MS : LINUX_POLL_MS);
      linuxTimer.unref?.();
    }
  }

  // One xprop call at start and then every ~30 s while Dota is not running.
  async function idleProbe(tools) {
    idleTicks += 1;
    if (state.supported && idleTicks % 15 !== 0) {
      return true;
    }
    return probeX(tools);
  }

  async function probeX(tools) {
    const root = await runTool(spawnImpl, tools.xprop, ["-root", "_NET_ACTIVE_WINDOW"], { env: xEnv() });
    const ok = root.ok && parseActiveWindow(root.stdout) !== null;
    xFailures = ok ? 0 : xFailures + 1;
    if (!ok && state.supported === false && xFailures === 1) {
      log("Dota focus tracking is off: xprop cannot read the X server.");
    }
    return ok;
  }

  function startLinux() {
    linuxTick();
  }

  emitter.start = () => {
    if (!stopped) {
      return;
    }
    stopped = false;
    if (platform === "win32") {
      startWindows();
    } else if (platform === "linux") {
      startLinux();
    }
  };

  emitter.stop = () => {
    stopped = true;
    clearTimeout(restartTimer);
    clearTimeout(linuxTimer);
    if (child) {
      try {
        child.kill();
      } catch {
        // Already gone.
      }
      child = null;
    }
  };

  emitter.getState = () => ({ ...state });
  return emitter;
}

module.exports = {
  createDotaWatcher,
  findDotaProcessesOnLinux,
  findOnPath,
  parseActiveWindow,
  parseRect,
  parseWatcherLine,
  parseWindowProps,
  parseXwininfo,
  windowsWatchScript,
  encodePowerShell
};
