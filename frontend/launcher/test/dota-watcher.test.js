const assert = require("node:assert/strict");
const test = require("node:test");

const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  createDotaWatcher,
  encodePowerShell,
  findDotaProcessesOnLinux,
  findOnPath,
  parseActiveWindow,
  parseRect,
  parseWatcherLine,
  parseWindowProps,
  parseXwininfo,
  windowsWatchScript
} = require("../dota-watcher");

test("parses watcher lines", () => {
  assert.deepEqual(parseWatcherLine('{"running":true,"focused":true,"path":"C:\\\\dota2.exe"}'), {
    running: true,
    focused: true,
    exePath: "C:\\dota2.exe",
    exclusiveFullscreen: false,
    windowRect: null
  });
  assert.deepEqual(parseWatcherLine('{"running":false,"focused":true,"path":"","fullscreen":true,"rect":[0,0,10,10]}'), {
    running: false,
    focused: false,
    exePath: "",
    exclusiveFullscreen: false,
    windowRect: null
  });
  assert.equal(parseWatcherLine("not json"), null);
});

test("parses exclusive fullscreen and the Dota window rect", () => {
  const state = parseWatcherLine(
    '{"running":true,"focused":true,"path":"","fullscreen":true,"rect":[1920,0,4480,1440]}'
  );
  assert.equal(state.exclusiveFullscreen, true);
  assert.deepEqual(state.windowRect, { x: 1920, y: 0, width: 2560, height: 1440 });
});

test("rejects malformed window rects", () => {
  assert.equal(parseRect(null), null);
  assert.equal(parseRect([0, 0, 10]), null);
  assert.equal(parseRect([0, 0, "10", 10]), null);
  assert.equal(parseRect([10, 0, 0, 10]), null);
  assert.deepEqual(parseRect([-1920, -200, 0, 880]), { x: -1920, y: -200, width: 1920, height: 1080 });
});

test("watch script embeds the parent pid and fits a command line", () => {
  const script = windowsWatchScript(4321);
  assert.match(script, /\$parentPid = 4321/);
  assert.doesNotMatch(script, /__[A-Z_]+__/);
  assert.ok(encodePowerShell(script).length < 8000);
});

const { PassThrough } = require("node:stream");

function failingSpawn() {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.pid = undefined;
  child.kill = () => {};
  setImmediate(() => child.emit("error", new Error("spawn powershell.exe ENOENT")));
  return child;
}

test("a watcher whose helper cannot spawn restarts and finally falls back", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let spawns = 0;
  const watcher = createDotaWatcher({
    platform: "win32",
    spawnImpl: (...args) => {
      spawns += 1;
      return failingSpawn(...args);
    }
  });
  const reports = [];
  watcher.on("report", (state) => reports.push(state));
  watcher.start();
  for (let i = 0; i < 10 && !reports.length; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
    t.mock.timers.tick(3000);
  }
  watcher.stop();
  assert.equal(spawns, 5);
  assert.equal(reports.length, 1);
  assert.equal(reports[0].supported, false);
  assert.equal(watcher.getState().supported, false);
});

// --- Linux -------------------------------------------------------------------

function fakeProc(t, processes) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-proc-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  for (const [pid, comm, exe] of processes) {
    fs.mkdirSync(path.join(dir, String(pid)));
    fs.writeFileSync(path.join(dir, String(pid), "comm"), `${comm}\n`);
    if (exe) {
      fs.symlinkSync(exe, path.join(dir, String(pid), "exe"));
    }
  }
  fs.mkdirSync(path.join(dir, "self"));
  return dir;
}

const DOTA_EXE = "/home/u/.steam/steam/steamapps/common/dota 2 beta/game/bin/linuxsteamrt64/dota2";

// `screen` is mutable: the tests change the active window between polls.
function fakeX(screen) {
  const calls = [];
  const spawnImpl = (command, args, options) => {
    calls.push({ command, args, options });
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.kill = () => {};
    setImmediate(() => {
      let out = "";
      let code = 0;
      const tool = path.basename(command);
      if (screen.down) {
        code = 1;
      } else if (tool === "xprop" && args[0] === "-root") {
        out = `_NET_ACTIVE_WINDOW(WINDOW): window id # ${screen.active}\n`;
      } else if (tool === "xprop") {
        out = screen.props[args[1]] || "";
        if (!out) code = 1;
      } else if (tool === "xwininfo") {
        out = screen.geometry[args[1]] || "";
      }
      if (out) child.stdout.emit("data", Buffer.from(out));
      child.emit("close", code);
    });
    return child;
  };
  return { spawnImpl, calls };
}

const PROPS = (pid, klass, state = "") =>
  `_NET_WM_PID(CARDINAL) = ${pid}\nWM_CLASS(STRING) = "${klass}", "${klass}"\n` +
  (state ? `_NET_WM_STATE(ATOM) = ${state}\n` : "_NET_WM_STATE:  not found.\n");
const GEOMETRY = (x, y, w, h) =>
  `xwininfo: Window id: 0x1\n  Absolute upper-left X:  ${x}\n  Absolute upper-left Y:  ${y}\n  Relative upper-left X:  0\n  Relative upper-left Y:  0\n  Width: ${w}\n  Height: ${h}\n`;

function linuxWatcher(t, { processes, screen, env = { DISPLAY: ":0", PATH: "/usr/bin" }, tools = true }) {
  const x = fakeX(screen);
  const logs = [];
  const watcher = createDotaWatcher({
    platform: "linux",
    env,
    procDir: fakeProc(t, processes),
    spawnImpl: x.spawnImpl,
    findTool: (name) => (tools ? `/usr/bin/${name}` : ""),
    log: (message) => logs.push(message)
  });
  t.after(() => watcher.stop());
  return { watcher, x, logs };
}

const nextReport = (watcher) => new Promise((resolve) => watcher.once("report", resolve));

test("the X helpers' output is parsed", () => {
  assert.equal(parseActiveWindow("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4A00007\n"), "0x4a00007");
  assert.equal(parseActiveWindow("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n"), "");
  assert.equal(parseActiveWindow("_NET_ACTIVE_WINDOW:  not found."), null);
  assert.deepEqual(parseWindowProps(PROPS(77, "dota2", "_NET_WM_STATE_FULLSCREEN, _NET_WM_STATE_ABOVE")), {
    pid: 77,
    classes: ["dota2", "dota2"],
    fullscreen: true,
    hidden: false
  });
  assert.equal(parseWindowProps(PROPS(77, "x", "_NET_WM_STATE_HIDDEN")).hidden, true);
  assert.equal(parseWindowProps("garbage").pid, 0);
  assert.deepEqual(parseXwininfo(GEOMETRY(1920, 0, 2560, 1440)), { x: 1920, y: 0, width: 2560, height: 1440 });
  assert.equal(parseXwininfo("nothing"), null);
});

test("the /proc scan finds dota2 with its executable and ignores other processes", (t) => {
  const dir = fakeProc(t, [
    [10, "bash", null],
    [4321, "dota2", DOTA_EXE],
    [4322, "dota2", null]
  ]);
  assert.deepEqual(findDotaProcessesOnLinux(dir), [
    { pid: 4321, exe: DOTA_EXE },
    { pid: 4322, exe: "" }
  ]);
  assert.deepEqual(findDotaProcessesOnLinux(path.join(dir, "missing")), []);
});

test("findOnPath returns the first executable file", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-path-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(dir, "xprop"), "#!/bin/sh\n", { mode: 0o755 });
  fs.writeFileSync(path.join(dir, "plain"), "x", { mode: 0o644 });
  assert.equal(findOnPath("xprop", `/nonexistent${path.delimiter}${dir}`), path.join(dir, "xprop"));
  assert.equal(findOnPath("plain", dir), "");
  assert.equal(findOnPath("xwininfo", dir), "");
});

test("linux: focus, window rect and exe come from the X tools while Dota is active", async (t) => {
  const screen = {
    active: "0x400001",
    props: { "0x400001": PROPS(4321, "dota2") },
    geometry: { "0x400001": GEOMETRY(0, 0, 1920, 1080) }
  };
  const { watcher, x } = linuxWatcher(t, { processes: [[4321, "dota2", DOTA_EXE]], screen });
  const report = nextReport(watcher);
  watcher.start();
  const state = await report;
  assert.equal(state.supported, true);
  assert.equal(state.running, true);
  assert.equal(state.focused, true);
  assert.equal(state.exePath, DOTA_EXE);
  assert.equal(state.exclusiveFullscreen, false);
  assert.deepEqual(state.windowRect, { x: 0, y: 0, width: 1920, height: 1080 });
  // Argv arrays only, never a shell; the output format does not depend on the locale.
  assert.ok(x.calls.every((call) => Array.isArray(call.args) && !call.options.shell && call.options.env.LC_ALL === "C"));
});

test("linux: the class is enough when the window has no _NET_WM_PID", async (t) => {
  const screen = {
    active: "0x5",
    props: { "0x5": 'WM_CLASS(STRING) = "dota2", "dota2"\n_NET_WM_STATE:  not found.\n' },
    geometry: { "0x5": GEOMETRY(10, 20, 800, 600) }
  };
  const { watcher } = linuxWatcher(t, { processes: [[4321, "dota2", null]], screen });
  const report = nextReport(watcher);
  watcher.start();
  assert.equal((await report).focused, true);
});

test("linux: another active window is not focus; the last Dota rect is kept", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const screen = {
    active: "0x1",
    props: { "0x1": PROPS(4321, "dota2"), "0x2": PROPS(999, "firefox") },
    geometry: { "0x1": GEOMETRY(100, 50, 1280, 720) }
  };
  const { watcher } = linuxWatcher(t, { processes: [[4321, "dota2", DOTA_EXE]], screen });
  let report = nextReport(watcher);
  watcher.start();
  assert.equal((await report).focused, true);

  screen.active = "0x2";
  report = nextReport(watcher);
  t.mock.timers.tick(1000);
  const away = await report;
  assert.equal(away.focused, false);
  assert.equal(away.running, true);
  assert.deepEqual(away.windowRect, { x: 100, y: 50, width: 1280, height: 720 });

  screen.active = "0x0"; // nothing active, e.g. the desktop was clicked
  report = nextReport(watcher);
  t.mock.timers.tick(1000);
  assert.equal((await report).focused, false);
});

test("linux: _NET_WM_STATE_FULLSCREEN is the exclusive fullscreen flag, kept until Dota exits", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const screen = {
    active: "0x1",
    props: { "0x1": PROPS(4321, "dota2", "_NET_WM_STATE_FULLSCREEN"), "0x2": PROPS(999, "konsole") },
    geometry: { "0x1": GEOMETRY(0, 0, 2560, 1440) }
  };
  const dir = fakeProc(t, [[4321, "dota2", DOTA_EXE]]);
  const x = fakeX(screen);
  const watcher = createDotaWatcher({
    platform: "linux",
    env: { DISPLAY: ":0" },
    procDir: dir,
    spawnImpl: x.spawnImpl,
    findTool: (name) => `/usr/bin/${name}`
  });
  t.after(() => watcher.stop());
  let report = nextReport(watcher);
  watcher.start();
  assert.equal((await report).exclusiveFullscreen, true);

  screen.active = "0x2"; // alt-tab
  report = nextReport(watcher);
  t.mock.timers.tick(1000);
  const tabbed = await report;
  assert.equal(tabbed.focused, false);
  assert.equal(tabbed.exclusiveFullscreen, true);

  fs.rmSync(path.join(dir, "4321"), { recursive: true });
  report = nextReport(watcher);
  t.mock.timers.tick(1000);
  const closed = await report;
  assert.equal(closed.running, false);
  assert.equal(closed.exclusiveFullscreen, false);
  assert.equal(closed.windowRect, null);
});

test("linux: a minimized Dota window is not focused", async (t) => {
  const screen = {
    active: "0x1",
    props: { "0x1": PROPS(4321, "dota2", "_NET_WM_STATE_HIDDEN") },
    geometry: {}
  };
  const { watcher } = linuxWatcher(t, { processes: [[4321, "dota2", DOTA_EXE]], screen });
  const report = nextReport(watcher);
  watcher.start();
  assert.equal((await report).focused, false);
});

test("linux: without Dota the watcher is supported but idle and spawns one probe", async (t) => {
  const screen = { active: "0x0", props: {}, geometry: {} };
  const { watcher, x } = linuxWatcher(t, { processes: [[10, "bash", null]], screen });
  const report = nextReport(watcher);
  watcher.start();
  const state = await report;
  assert.equal(state.supported, true);
  assert.equal(state.running, false);
  assert.equal(state.focused, false);
  assert.equal(x.calls.length, 1);
});

test("linux: without xprop/xwininfo it keeps the process scan and says so once", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { watcher, x, logs } = linuxWatcher(t, {
    processes: [[4321, "dota2", DOTA_EXE]],
    screen: { active: "0x1", props: {}, geometry: {} },
    tools: false
  });
  let report = nextReport(watcher);
  watcher.start();
  const state = await report;
  assert.equal(state.supported, false);
  assert.equal(state.running, true);
  assert.equal(state.focused, true, "today's behaviour: running counts as focused");
  assert.equal(state.exePath, DOTA_EXE);
  report = nextReport(watcher);
  t.mock.timers.tick(1000);
  await report;
  assert.equal(x.calls.length, 0);
  assert.equal(logs.filter((line) => line.includes("xprop")).length, 1);
});

test("linux: without an X display focus tracking is off", async (t) => {
  const { watcher, x, logs } = linuxWatcher(t, {
    processes: [[4321, "dota2", DOTA_EXE]],
    screen: { active: "0x1", props: {}, geometry: {} },
    env: { PATH: "/usr/bin" }
  });
  const report = nextReport(watcher);
  watcher.start();
  assert.equal((await report).supported, false);
  assert.equal(x.calls.length, 0);
  assert.match(logs[0], /no X display/);
});

test("linux: an X server that stops answering turns tracking off after repeated failures", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const screen = { active: "0x1", props: { "0x1": PROPS(4321, "dota2") }, geometry: { "0x1": GEOMETRY(0, 0, 800, 600) } };
  const { watcher, logs } = linuxWatcher(t, { processes: [[4321, "dota2", DOTA_EXE]], screen });
  let report = nextReport(watcher);
  watcher.start();
  assert.equal((await report).supported, true);
  screen.down = true;
  let last;
  for (let i = 0; i < 5; i += 1) {
    report = nextReport(watcher);
    t.mock.timers.tick(1000);
    last = await report;
  }
  assert.equal(last.supported, false);
  assert.equal(last.running, true);
  assert.ok(logs.some((line) => line.includes("stopped")));
  screen.down = false;
  report = nextReport(watcher);
  t.mock.timers.tick(1000);
  assert.equal((await report).supported, true);
});

test("linux: a hanging tool is killed after its time box and never throws", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let killed = false;
  const watcher = createDotaWatcher({
    platform: "linux",
    env: { DISPLAY: ":0" },
    procDir: fakeProc(t, [[4321, "dota2", DOTA_EXE]]),
    findTool: (name) => `/usr/bin/${name}`,
    spawnImpl: () => {
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.kill = () => {
        killed = true;
      };
      return child; // never closes
    }
  });
  t.after(() => watcher.stop());
  const report = nextReport(watcher);
  watcher.start();
  await new Promise((resolve) => setImmediate(resolve));
  t.mock.timers.tick(1500);
  const state = await report;
  assert.equal(killed, true);
  assert.equal(state.running, true);
});
