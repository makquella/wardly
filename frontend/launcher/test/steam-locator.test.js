const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const {
  defaultSteamRoots,
  dotaDirFromExecutable,
  libraryFoldersFromVdf,
  locateDota,
  parseRegQueryValue,
  parseVdf
} = require("../steam-locator");

const MODERN_VDF = `
"libraryfolders"
{
	"0"
	{
		"path"		"C:\\\\Program Files (x86)\\\\Steam"
		"label"		""
		"apps"
		{
			"228980"		"417337782"
		}
	}
	"1"
	{
		"path"		"E:\\\\Games\\\\SteamLibrary"
		"apps"
		{
			"570"		"41503957013"
		}
	}
}
`;

const LEGACY_VDF = `
"LibraryFolders"
{
	"TimeNextStatsReport"		"1611111111"
	"ContentStatsID"		"-123"
	"1"		"D:\\\\SteamLibrary"
}
`;

test("parses the current libraryfolders.vdf format", () => {
  const libraries = libraryFoldersFromVdf(parseVdf(MODERN_VDF));
  assert.deepEqual(libraries, [
    { path: "C:\\Program Files (x86)\\Steam", apps: ["228980"] },
    { path: "E:\\Games\\SteamLibrary", apps: ["570"] }
  ]);
});

test("parses the legacy libraryfolders.vdf format and ignores non-library keys", () => {
  assert.deepEqual(libraryFoldersFromVdf(parseVdf(LEGACY_VDF)), [{ path: "D:\\SteamLibrary", apps: [] }]);
});

test("vdf parser keeps unknown escapes and skips comments", () => {
  const parsed = parseVdf('// comment\n"root" { "path" "C:\\Games\\Steam" "quote" "a\\"b" }');
  assert.equal(parsed.root.path, "C:\\Games\\Steam");
  assert.equal(parsed.root.quote, 'a"b');
});

test("reads REG_SZ values from reg.exe output", () => {
  const output = "\r\nHKEY_CURRENT_USER\\Software\\Valve\\Steam\r\n    SteamPath    REG_SZ    c:/program files (x86)/steam\r\n\r\n";
  assert.equal(parseRegQueryValue(output, "SteamPath"), "c:/program files (x86)/steam");
  assert.equal(parseRegQueryValue(output, "InstallPath"), "");
});

test("derives the Dota folder from the running dota2.exe path", () => {
  assert.equal(
    dotaDirFromExecutable("E:\\Games\\SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\bin\\win64\\dota2.exe", "win32"),
    "E:\\Games\\SteamLibrary\\steamapps\\common\\dota 2 beta"
  );
  assert.equal(dotaDirFromExecutable("C:\\Other\\bin\\win64\\dota2.exe", "win32"), "");
  assert.equal(dotaDirFromExecutable("", "win32"), "");
});

function fakeFs(files) {
  const known = new Set();
  for (const file of Object.keys(files)) {
    let current = path.win32.normalize(file).toLowerCase();
    while (current && !known.has(current)) {
      known.add(current);
      const parent = path.win32.dirname(current);
      if (parent === current) {
        break;
      }
      current = parent;
    }
  }
  return {
    existsSync: (target) => known.has(path.win32.normalize(target).toLowerCase()),
    readFileSync: (target) => {
      const key = Object.keys(files).find((file) => file.toLowerCase() === path.win32.normalize(target).toLowerCase());
      if (key === undefined) {
        throw new Error(`ENOENT ${target}`);
      }
      return files[key];
    }
  };
}

test("finds Dota in a secondary library on another drive via registry + libraryfolders.vdf", async () => {
  const fsImpl = fakeFs({
    "D:\\Steam\\steamapps\\libraryfolders.vdf": MODERN_VDF,
    "E:\\Games\\SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\gameinfo.gi": ""
  });
  const registry = {
    "HKCU\\Software\\Valve\\Steam|SteamPath": "d:/steam"
  };
  const result = await locateDota({
    platform: "win32",
    env: { "ProgramFiles(x86)": "C:\\Program Files (x86)", ProgramFiles: "C:\\Program Files" },
    fs: fsImpl,
    queryRegistry: async (key, value) => registry[`${key}|${value}`] || ""
  });
  assert.deepEqual(result.steamRoots, ["d:\\steam"]);
  assert.equal(result.dotaDir, "E:\\Games\\SteamLibrary\\steamapps\\common\\dota 2 beta");
  assert.equal(
    result.gsiDir,
    "E:\\Games\\SteamLibrary\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration"
  );
});

test("reports not found when no library has Dota", async () => {
  const result = await locateDota({
    platform: "win32",
    env: {},
    fs: fakeFs({ "C:\\Program Files (x86)\\Steam\\steamapps\\libraryfolders.vdf": LEGACY_VDF }),
    queryRegistry: async () => ""
  });
  assert.equal(result.dotaDir, "");
  assert.equal(result.gsiDir, "");
  assert.ok(result.libraries.includes("D:\\SteamLibrary"));
});

test("uses the running game's folder when Steam knows nothing about it", async () => {
  const result = await locateDota({
    platform: "win32",
    env: {},
    fs: fakeFs({ "F:\\dota 2 beta\\game\\dota\\gameinfo.gi": "" }),
    queryRegistry: async () => "",
    extraDotaDirs: ["F:\\dota 2 beta"]
  });
  assert.equal(result.dotaDir, "F:\\dota 2 beta");
});

function localConfig(launchOptions) {
  const app = launchOptions === null ? "" : `"570" { "LastPlayed" "1790000000" "LaunchOptions" "${launchOptions}" }`;
  return `"UserLocalConfigStore"
{
	"Software" { "Valve" { "Steam" { "apps" { "440" { "LaunchOptions" "-novid" } ${app} } } } }
}`;
}

function steamWithUsers(users) {
  const fs = require("node:fs");
  const os = require("node:os");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "steam-"));
  for (const [user, text, mtime] of users) {
    const dir = path.join(root, "userdata", user, "config");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "localconfig.vdf"), text);
    fs.utimesSync(path.join(dir, "localconfig.vdf"), mtime, mtime);
  }
  return root;
}

test("the GSI launch option is found among other options, in any case", () => {
  const { dotaLaunchOptionsFromVdf, hasGsiLaunchOption } = require("../steam-locator");
  assert.equal(dotaLaunchOptionsFromVdf(parseVdf(localConfig("-novid -gamestateintegration"))), "-novid -gamestateintegration");
  assert.equal(dotaLaunchOptionsFromVdf(parseVdf(localConfig(null))), null);
  assert.equal(hasGsiLaunchOption("-novid  -GameStateIntegration -high"), true);
  assert.equal(hasGsiLaunchOption("-gamestateintegrationx"), false);
  assert.equal(hasGsiLaunchOption(""), false);
});

test("launch options are read for the linked account, else the latest Steam user", () => {
  const { checkLaunchOptions } = require("../steam-locator");
  const root = steamWithUsers([
    ["52079950", localConfig("-gamestateintegration"), 1000],
    ["11111", localConfig("-novid"), 2000],
    ["0", localConfig("-gamestateintegration"), 3000]
  ]);
  const opts = { steamRoots: [root], platform: "linux" };
  assert.deepEqual(checkLaunchOptions({ ...opts, accountId: 52079950 }), { state: "ok", accountId: "52079950" });
  assert.deepEqual(checkLaunchOptions(opts), { state: "missing", accountId: "11111" });
  assert.deepEqual(checkLaunchOptions({ ...opts, accountId: 999 }), { state: "unknown", accountId: null });
  assert.deepEqual(checkLaunchOptions({ steamRoots: ["/nonexistent"], platform: "linux" }).state, "unknown");
  const noDota = steamWithUsers([["22", localConfig(null), 1000]]);
  assert.equal(checkLaunchOptions({ steamRoots: [noDota], platform: "linux" }).state, "missing");
  const broken = steamWithUsers([["22", "\"UserLocalConfigStore\" { \"Software\" ", 1000]]);
  assert.equal(checkLaunchOptions({ steamRoots: [broken], platform: "linux" }).state, "missing");
});

test("the text scan agrees with the full parse and skips other 570 blocks", () => {
  const { dotaLaunchOptionsFromText, dotaLaunchOptionsFromVdf } = require("../steam-locator");
  for (const options of ["-novid -gamestateintegration", "", '-console \\"quoted\\" { braces }']) {
    const text = localConfig(options);
    assert.equal(dotaLaunchOptionsFromText(text), dotaLaunchOptionsFromVdf(parseVdf(text)));
  }
  assert.equal(dotaLaunchOptionsFromText(localConfig(null)), null);
  const withCloud = `"UserLocalConfigStore" { "Apps" { "570" { "cloud" { "quota" "1" } } } ${localConfig("-gamestateintegration").slice(22)} }`;
  assert.equal(dotaLaunchOptionsFromText(withCloud), "-gamestateintegration");
});

// --- Linux: real temporary folders (symlinks and a second "drive") ------------

function linuxHome(t) {
  const fs = require("node:fs");
  const os = require("node:os");
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-linux-"));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  return { fs, home: path.join(base, "home"), drive: path.join(base, "mnt", "games"), base };
}

function libraryVdf(libraryPath) {
  return `"libraryfolders" { "0" { "path" "/nonexistent/main" "apps" { "228980" "1" } } "1" { "path" "${libraryPath}" "apps" { "570" "1" } } }`;
}

test("linux: Dota in a library on another drive; the ~/.steam/steam symlink is listed once", async (t) => {
  const { fs, home, drive } = linuxHome(t);
  const steam = path.join(home, ".local", "share", "Steam");
  fs.mkdirSync(path.join(steam, "steamapps"), { recursive: true });
  fs.mkdirSync(path.join(home, ".steam"), { recursive: true });
  fs.symlinkSync(steam, path.join(home, ".steam", "steam"));
  fs.writeFileSync(path.join(steam, "steamapps", "libraryfolders.vdf"), libraryVdf(drive));
  const dota = path.join(drive, "steamapps", "common", "dota 2 beta");
  fs.mkdirSync(path.join(dota, "game", "dota"), { recursive: true });

  const result = await locateDota({ platform: "linux", env: {}, homedir: home });
  assert.deepEqual(result.steamRoots, [steam]);
  assert.equal(result.dotaDir, dota);
  assert.equal(result.gsiDir, path.join(dota, "game", "dota", "cfg", "gamestate_integration"));
  assert.deepEqual(result.libraries.filter((dir) => dir === steam).length, 1);
});

test("linux: the Snap and Flatpak Steam roots are searched", async (t) => {
  const { fs, home, drive } = linuxHome(t);
  const roots = defaultSteamRoots({ platform: "linux", env: {}, homedir: home });
  assert.ok(roots.includes(path.join(home, "snap", "steam", "common", ".local", "share", "Steam")));
  assert.ok(roots.includes(path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")));

  const snap = path.join(home, "snap", "steam", "common", ".local", "share", "Steam");
  fs.mkdirSync(path.join(snap, "config"), { recursive: true });
  fs.writeFileSync(path.join(snap, "config", "libraryfolders.vdf"), libraryVdf(drive));
  fs.mkdirSync(path.join(drive, "steamapps", "common", "dota 2 beta", "game", "dota"), { recursive: true });
  const result = await locateDota({ platform: "linux", env: {}, homedir: home });
  assert.deepEqual(result.steamRoots, [snap]);
  assert.equal(result.dotaDir, path.join(drive, "steamapps", "common", "dota 2 beta"));
});

test("linux: XDG_DATA_HOME is honoured and the running game's folder is derived from its exe", async (t) => {
  const { fs, home, base } = linuxHome(t);
  const data = path.join(base, "xdg-data");
  assert.ok(defaultSteamRoots({ platform: "linux", env: { XDG_DATA_HOME: data }, homedir: home }).includes(path.join(data, "Steam")));
  assert.equal(
    dotaDirFromExecutable("/mnt/games/steamapps/common/dota 2 beta/game/bin/linuxsteamrt64/dota2", "linux"),
    "/mnt/games/steamapps/common/dota 2 beta"
  );
  assert.equal(dotaDirFromExecutable("/usr/bin/dota2", "linux"), "");
  const result = await locateDota({ platform: "linux", env: {}, homedir: home, extraDotaDirs: ["/nonexistent/dota 2 beta"] });
  assert.equal(result.dotaDir, "");
  assert.equal(fs.existsSync(home), false);
});
