const { execFile } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// Finds the Dota 2 install through Steam: registry -> Steam root(s) ->
// steamapps/libraryfolders.vdf -> every library on every drive. No Electron
// imports, so it can be unit-tested with plain `node --test`.

const DOTA_APP_ID = "570";
const DOTA_FOLDER = "dota 2 beta";
const GSI_RELATIVE_DIR = ["game", "dota", "cfg", "gamestate_integration"];

const STEAM_REGISTRY_VALUES = [
  ["HKCU\\Software\\Valve\\Steam", "SteamPath"],
  ["HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam", "InstallPath"],
  ["HKLM\\SOFTWARE\\Valve\\Steam", "InstallPath"]
];
const DOTA_UNINSTALL_REGISTRY_VALUES = [
  ["HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Steam App 570", "InstallLocation"],
  ["HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Steam App 570", "InstallLocation"]
];

// Minimal Valve KeyValues (VDF) text parser: quoted or bare tokens, nested
// blocks, `//` comments and backslash escapes. Keys are kept as written.
function parseVdf(text) {
  const tokens = tokenizeVdf(String(text || ""));
  let index = 0;

  function parseBlock() {
    const block = {};
    while (index < tokens.length) {
      const token = tokens[index];
      if (token.type === "close") {
        index += 1;
        return block;
      }
      if (token.type !== "string") {
        index += 1;
        continue;
      }
      const key = token.value;
      index += 1;
      const next = tokens[index];
      if (!next) {
        break;
      }
      if (next.type === "open") {
        index += 1;
        block[key] = parseBlock();
      } else if (next.type === "string") {
        index += 1;
        block[key] = next.value;
      }
    }
    return block;
  }

  return parseBlock();
}

function tokenizeVdf(text) {
  const tokens = [];
  let i = 0;
  while (i < text.length) {
    const char = text[i];
    if (char === "/" && text[i + 1] === "/") {
      while (i < text.length && text[i] !== "\n") {
        i += 1;
      }
    } else if (char === "{") {
      tokens.push({ type: "open" });
      i += 1;
    } else if (char === "}") {
      tokens.push({ type: "close" });
      i += 1;
    } else if (char === '"') {
      let value = "";
      i += 1;
      while (i < text.length && text[i] !== '"') {
        const escaped = text[i + 1];
        if (text[i] === "\\" && ["\\", '"', "n", "t"].includes(escaped)) {
          value += escaped === "n" ? "\n" : escaped === "t" ? "\t" : escaped;
          i += 2;
        } else {
          // Unknown escapes (e.g. a single "\" in a hand-edited path) stay literal.
          value += text[i];
          i += 1;
        }
      }
      i += 1;
      tokens.push({ type: "string", value });
    } else if (/\s/.test(char)) {
      i += 1;
    } else {
      let value = "";
      while (i < text.length && !/[\s{}"]/.test(text[i])) {
        value += text[i];
        i += 1;
      }
      tokens.push({ type: "string", value });
    }
  }
  return tokens;
}

function findKey(object, name) {
  if (!object || typeof object !== "object") {
    return undefined;
  }
  const wanted = name.toLowerCase();
  const key = Object.keys(object).find((candidate) => candidate.toLowerCase() === wanted);
  return key === undefined ? undefined : object[key];
}

// Supports both the current format ("0" { "path" "D:\\SteamLibrary" "apps" { "570" "..." } })
// and the legacy one ("1" "D:\\SteamLibrary").
function libraryFoldersFromVdf(parsed) {
  const root = findKey(parsed, "libraryfolders");
  if (!root || typeof root !== "object") {
    return [];
  }
  const libraries = [];
  for (const [key, value] of Object.entries(root)) {
    if (!/^\d+$/.test(key)) {
      continue;
    }
    if (typeof value === "string") {
      libraries.push({ path: value, apps: [] });
    } else if (value && typeof value === "object") {
      const libraryPath = findKey(value, "path");
      if (typeof libraryPath === "string" && libraryPath) {
        const apps = findKey(value, "apps");
        libraries.push({ path: libraryPath, apps: apps && typeof apps === "object" ? Object.keys(apps) : [] });
      }
    }
  }
  return libraries;
}

function parseRegQueryValue(output, valueName) {
  const pattern = new RegExp(`^\\s*${valueName}\\s+REG_(?:EXPAND_)?SZ\\s+(.+?)\\s*$`, "im");
  const match = String(output || "").match(pattern);
  return match ? match[1] : "";
}

function queryRegistryValue(key, valueName) {
  return new Promise((resolve) => {
    execFile(
      "reg.exe",
      ["query", key, "/v", valueName],
      { windowsHide: true, timeout: 4000 },
      (error, stdout) => resolve(error ? "" : parseRegQueryValue(stdout, valueName))
    );
  });
}

function defaultSteamRoots({ platform = process.platform, env = process.env, homedir = os.homedir() } = {}) {
  if (platform === "win32") {
    const programFilesX86 = env["ProgramFiles(x86)"] || "C:\\Program Files (x86)";
    const programFiles = env.ProgramFiles || "C:\\Program Files";
    return [path.win32.join(programFilesX86, "Steam"), path.win32.join(programFiles, "Steam")];
  }
  const dataHome = env && env.XDG_DATA_HOME && path.isAbsolute(env.XDG_DATA_HOME) ? env.XDG_DATA_HOME : "";
  return [
    path.join(homedir, ".steam", "steam"),
    path.join(homedir, ".local", "share", "Steam"),
    ...(dataHome ? [path.join(dataHome, "Steam")] : []),
    // Flatpak and Snap keep Steam in their own home.
    path.join(homedir, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
    path.join(homedir, "snap", "steam", "common", ".local", "share", "Steam")
  ];
}

function normalizeDir(dir, platform) {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  return pathApi.normalize(String(dir).trim());
}

function uniqueDirs(dirs, platform) {
  const seen = new Set();
  const result = [];
  for (const dir of dirs) {
    if (!dir) {
      continue;
    }
    const normalized = normalizeDir(dir, platform);
    const key = platform === "win32" ? normalized.toLowerCase() : normalized;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(normalized);
    }
  }
  return result;
}

function dotaDirForLibrary(libraryDir, platform) {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  return pathApi.join(libraryDir, "steamapps", "common", DOTA_FOLDER);
}

function gsiDirForDotaDir(dotaDir, platform = process.platform) {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  return pathApi.join(dotaDir, ...GSI_RELATIVE_DIR);
}

// ...\dota 2 beta\game\bin\win64\dota2.exe -> ...\dota 2 beta
function dotaDirFromExecutable(executablePath, platform = process.platform) {
  if (!executablePath) {
    return "";
  }
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  const dir = pathApi.resolve(pathApi.dirname(executablePath), "..", "..", "..");
  return pathApi.basename(dir).toLowerCase() === DOTA_FOLDER ? dir : "";
}

/**
 * Locate Dota 2. Returns { steamRoots, libraries, dotaDir, gsiDir, source }.
 * dotaDir/gsiDir are "" when Dota is not installed in any known library.
 */
async function locateDota(options = {}) {
  const platform = options.platform || process.platform;
  const fsImpl = options.fs || fs;
  const queryRegistry = options.queryRegistry || queryRegistryValue;
  const exists = (target) => {
    try {
      return fsImpl.existsSync(target);
    } catch {
      return false;
    }
  };
  const pathApi = platform === "win32" ? path.win32 : path.posix;

  const registryRoots = [];
  const registryDotaDirs = [];
  if (platform === "win32") {
    for (const [key, valueName] of STEAM_REGISTRY_VALUES) {
      registryRoots.push(await queryRegistry(key, valueName));
    }
    for (const [key, valueName] of DOTA_UNINSTALL_REGISTRY_VALUES) {
      registryDotaDirs.push(await queryRegistry(key, valueName));
    }
  }

  // ~/.steam/steam is a symlink to ~/.local/share/Steam on most Linux installs:
  // list each real folder once.
  const realOf = (dir) => {
    if (platform === "win32" || typeof fsImpl.realpathSync !== "function") {
      return dir;
    }
    try {
      return fsImpl.realpathSync(dir);
    } catch {
      return dir;
    }
  };
  const steamRoots = uniqueDirs(
    uniqueDirs(
      [...registryRoots, ...defaultSteamRoots({ platform, env: options.env, homedir: options.homedir })],
      platform
    )
      .filter(exists)
      .map(realOf),
    platform
  );

  const libraries = [];
  for (const root of steamRoots) {
    libraries.push({ path: root, apps: [], source: "steam root" });
    for (const vdfPath of [
      pathApi.join(root, "steamapps", "libraryfolders.vdf"),
      pathApi.join(root, "config", "libraryfolders.vdf")
    ]) {
      if (!exists(vdfPath)) {
        continue;
      }
      try {
        for (const library of libraryFoldersFromVdf(parseVdf(fsImpl.readFileSync(vdfPath, "utf8")))) {
          libraries.push({ ...library, source: vdfPath });
        }
      } catch {
        // A broken libraryfolders.vdf must not stop the other candidates.
      }
    }
  }

  // Libraries that list app 570 first, then the rest.
  const ordered = [
    ...libraries.filter((library) => library.apps.includes(DOTA_APP_ID)),
    ...libraries.filter((library) => !library.apps.includes(DOTA_APP_ID))
  ];
  const candidates = uniqueDirs(
    [
      ...(options.extraDotaDirs || []),
      ...registryDotaDirs,
      ...ordered.map((library) => dotaDirForLibrary(library.path, platform))
    ],
    platform
  );
  const dotaDir = candidates.find((dir) => exists(pathApi.join(dir, "game", "dota"))) || "";
  return {
    steamRoots,
    libraries: uniqueDirs(libraries.map((library) => library.path), platform),
    dotaDir,
    gsiDir: dotaDir ? gsiDirForDotaDir(dotaDir, platform) : "",
    source: dotaDir ? "steam" : "not found"
  };
}

// Since 2023 Dota 2 sends game state only when started with this option.
const GSI_LAUNCH_OPTION = "-gamestateintegration";
// Steam starts Dota 2 from this link, as from the library's Play button.
const DOTA_STEAM_URL = `steam://rungameid/${DOTA_APP_ID}`;

// userdata/<account id>/config/localconfig.vdf ->
// UserLocalConfigStore > Software > Valve > Steam > apps > 570 > LaunchOptions.
// null when the file has no entry for Dota at all.
function dotaLaunchOptionsFromVdf(parsed) {
  let node = findKey(parsed, "UserLocalConfigStore");
  for (const key of ["Software", "Valve", "Steam", "apps", DOTA_APP_ID]) {
    node = findKey(node, key);
  }
  if (!node || typeof node !== "object") {
    return null;
  }
  const options = findKey(node, "LaunchOptions");
  return typeof options === "string" ? options : "";
}

// Same answer from the raw text without parsing the whole file (localconfig.vdf
// grows to several MB and this runs in the main process): only the "570"
// blocks are parsed, and the first one with LaunchOptions wins.
function dotaLaunchOptionsFromText(text) {
  const source = String(text || "");
  const pattern = new RegExp(`"${DOTA_APP_ID}"\\s*\\{`, "g");
  let found = false;
  let match;
  while ((match = pattern.exec(source))) {
    const start = match.index + match[0].length;
    let depth = 1;
    let inString = false;
    let i = start;
    for (; i < source.length && depth > 0; i += 1) {
      const char = source[i];
      if (inString) {
        if (char === "\\") {
          i += 1;
        } else if (char === '"') {
          inString = false;
        }
      } else if (char === '"') {
        inString = true;
      } else if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
      }
    }
    found = true;
    const options = findKey(parseVdf(source.slice(start, i - 1)), "LaunchOptions");
    if (typeof options === "string") {
      return options;
    }
  }
  return found ? "" : null;
}

function hasGsiLaunchOption(options) {
  return String(options || "")
    .split(/\s+/)
    .some((part) => part.toLowerCase() === GSI_LAUNCH_OPTION);
}

/**
 * Does Dota start with -gamestateintegration? Reads the launch options Steam
 * saved for `accountId` (or, without one, for the Steam user whose settings
 * changed last). Returns { state: "ok" | "missing" | "unknown", accountId }.
 * Steam saves the file lazily, so "missing" is a hint, never a hard error.
 */
function checkLaunchOptions({ steamRoots = [], accountId = null, platform = process.platform, fs: fsImpl = fs } = {}) {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  const configs = [];
  for (const root of steamRoots) {
    const userdata = pathApi.join(root, "userdata");
    let users;
    try {
      users = fsImpl.readdirSync(userdata).filter((name) => /^\d+$/.test(name) && name !== "0");
    } catch {
      continue;
    }
    if (accountId) {
      users = users.filter((name) => name === String(accountId));
    }
    for (const user of users) {
      const file = pathApi.join(userdata, user, "config", "localconfig.vdf");
      try {
        configs.push({ user, file, mtime: fsImpl.statSync(file).mtimeMs });
      } catch {
        // No saved settings for this user yet.
      }
    }
  }
  if (!configs.length) {
    return { state: "unknown", accountId: null };
  }
  configs.sort((a, b) => b.mtime - a.mtime);
  const latest = configs[0];
  let options;
  try {
    options = dotaLaunchOptionsFromText(fsImpl.readFileSync(latest.file, "utf8"));
  } catch {
    return { state: "unknown", accountId: latest.user };
  }
  return { state: hasGsiLaunchOption(options) ? "ok" : "missing", accountId: latest.user };
}

module.exports = {
  DOTA_STEAM_URL,
  DOTA_APP_ID,
  GSI_LAUNCH_OPTION,
  checkLaunchOptions,
  dotaLaunchOptionsFromText,
  dotaLaunchOptionsFromVdf,
  hasGsiLaunchOption,
  defaultSteamRoots,
  dotaDirFromExecutable,
  gsiDirForDotaDir,
  libraryFoldersFromVdf,
  locateDota,
  parseRegQueryValue,
  parseVdf
};
