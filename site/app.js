// Wardly website: language switch (the HTML is Ukrainian, English lives
// here), screenshots per language, the download button (latest GitHub release),
// where the visitor came from (below) and small scroll effects. No dependencies.
(() => {
  const REPO = "makquella/wardly";
  const LANG_KEY = "dac.lang";
  const API = "https://api.luhovyimvp.dev";
  // Bump with every reshoot of the pictures (scripts/site-shots) and in index.html.
  const SHOTS_VERSION = "22";

  const EN = Object.assign({}, window.WARDLY_EN || {}, {
    version: (v, mb) => `Version ${v} · Windows 10 and 11 · ${mb} MB`
  });
  const UK = {};

  let lang = "uk";
  let release = null;

  document.documentElement.classList.add("js");

  // --- language ------------------------------------------------------------------

  function remember(key, value) {
    if (!(key in UK)) {
      UK[key] = value;
    }
  }

  // Pages written in one language (<html data-static="uk|en">: every page now —
  // the English copies are built by scripts/build_site.py) switch by opening their
  // counterpart (data-alt-uk / data-alt-en); only a page without one translates in
  // place. The browser language is never used to switch a static page: search
  // engines render with an English browser and would index the wrong language.
  const PAGE = document.documentElement;
  const STATIC_LANG = PAGE.dataset.static === "en" ? "en" : PAGE.dataset.static === "uk" ? "uk" : "";
  const ALT = { uk: PAGE.dataset.altUk || "", en: PAGE.dataset.altEn || "" };

  function savedLanguage() {
    try {
      const saved = localStorage.getItem(LANG_KEY);
      if (saved === "ru") return "uk"; // the choice from before 0.54
      return saved === "uk" || saved === "en" ? saved : "";
    } catch {
      return "";
    }
  }

  function openCounterpart(next) {
    if (next !== STATIC_LANG && ALT[next]) {
      location.href = ALT[next] + location.search + location.hash;
      return true;
    }
    return false;
  }

  function applyLanguage(next) {
    if (STATIC_LANG) {
      lang = STATIC_LANG;
      document.querySelectorAll(".lang [data-lang]").forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.lang === lang));
      });
      renderRelease();
      return;
    }
    lang = next === "en" ? "en" : "uk";
    const table = lang === "en" ? EN : UK;
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.dataset.i18n;
      remember(key, el.textContent);
      if (typeof table[key] === "string") {
        el.textContent = table[key];
      }
    });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => {
      const key = el.dataset.i18nHtml;
      remember(key, el.innerHTML);
      if (typeof table[key] === "string") {
        el.innerHTML = table[key];
      }
    });
    for (const [attr, name] of [
      ["i18nAria", "aria-label"],
      ["i18nAlt", "alt"]
    ]) {
      document.querySelectorAll(`[data-${attr.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}]`).forEach((el) => {
        const key = el.dataset[attr];
        remember(key, el.getAttribute(name) || "");
        if (typeof table[key] === "string") {
          el.setAttribute(name, table[key]);
        }
      });
    }
    // Each page names its own title key (<body data-title>), the landing uses "title".
    const titleKey = document.body.dataset.title || "title";
    remember(titleKey, document.title);
    document.title = table[titleKey] || UK[titleKey];
    // Screenshots exist in both languages. SHOTS_VERSION (also in index.html) is
    // bumped with every reshoot, so browsers do not keep the old pictures.
    document.querySelectorAll("img[data-img]").forEach((img) => {
      img.src = `assets/app/${lang}/${img.dataset.img}.jpg?v=${SHOTS_VERSION}`;
    });
    document.querySelectorAll("img[data-ov]").forEach((img) => {
      img.src = `assets/overlay/${lang}/${img.dataset.ov}.webp?v=${SHOTS_VERSION}`;
    });
    document.querySelectorAll("img[data-game]").forEach((img) => {
      img.src = `assets/game/${img.dataset.game}-${lang}.jpg?v=${SHOTS_VERSION}`;
    });
    document.querySelectorAll("img[data-shot]").forEach((img) => {
      img.src = `assets/shots/${lang}/${img.dataset.shot}.jpg?v=${SHOTS_VERSION}`;
    });
    document.querySelectorAll(".lang [data-lang]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.lang === lang));
    });
    renderRelease();
  }

  function initialLanguage() {
    if (STATIC_LANG) {
      return STATIC_LANG;
    }
    const saved = savedLanguage();
    if (saved) {
      return saved;
    }
    const preferred = (navigator.languages || [navigator.language || "uk"]).map((l) => String(l).toLowerCase());
    return preferred.some((l) => /^(uk|ru|be|kk)/.test(l)) ? "uk" : "en";
  }

  document.querySelectorAll(".lang [data-lang]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = button.dataset.lang === "en" ? "en" : "uk";
      try {
        localStorage.setItem(LANG_KEY, next);
      } catch {
        // Not remembered; fine.
      }
      if (STATIC_LANG) {
        openCounterpart(next);
        return;
      }
      applyLanguage(next);
    });
  });

  // A language chosen earlier opens its version of this page (the ?ref= and the
  // anchor go along).
  const preferred = savedLanguage();
  if (STATIC_LANG && preferred && openCounterpart(preferred)) {
    return;
  }

  // --- where the visitor came from -------------------------------------------------
  // Posts link to the site with ?ref=<source>; without it the referrer's kind
  // (search, a known site, other, direct). Kept for this tab only (sessionStorage),
  // sent once as a count (POST /v1/hit) and passed to the download link
  // (/d/<source>), so the project sees visits and downloads per source. No cookies.

  const SOURCE_KEY = "wardly.src";
  const SITES = [
    [/(^|\.)(google|yandex|bing|duckduckgo|yahoo|ecosia)\.|(^|\.)(ya|go\.mail)\.ru$|(^|\.)search\./, "search"],
    [/(^|\.)reddit\.com$/, "reddit"],
    [/(^|\.)pikabu\.ru$/, "pikabu"],
    [/(^|\.)dtf\.ru$/, "dtf"],
    [/(^|\.)(vk\.com|vk\.ru)$/, "vk"],
    [/(^|\.)(t\.me|telegram\.org)$/, "tg"],
    [/(^|\.)(youtube\.com|youtu\.be)$/, "yt"],
    [/(^|\.)(steamcommunity|steampowered)\.com$/, "steam"],
    [/(^|\.)twitch\.tv$/, "twitch"],
    [/(^|\.)(discord\.com|discord\.gg|discordapp\.com)$/, "discord"],
    [/(^|\.)github\.com$/, "github"],
    [/(^|\.)cybersport\.ru$/, "cybersport"],
    [/(^|\.)dou\.ua$/, "dou"],
    [/(^|\.)(instagram\.com|threads\.net)$/, "social"],
    [/(^|\.)tiktok\.com$/, "tiktok"]
  ];

  function session(key, value) {
    try {
      if (value === undefined) {
        return sessionStorage.getItem(key);
      }
      sessionStorage.setItem(key, value);
    } catch {
      // Storage blocked: the source is worked out again on each page.
    }
    return null;
  }

  function trafficSource() {
    const ref = String(new URLSearchParams(location.search).get("ref") || "").trim().toLowerCase();
    if (/^[a-z0-9][a-z0-9_-]{0,23}$/.test(ref)) {
      session(SOURCE_KEY, ref);
      return ref;
    }
    const saved = session(SOURCE_KEY);
    if (saved) {
      return saved;
    }
    let host = "";
    try {
      host = document.referrer ? new URL(document.referrer).hostname.toLowerCase() : "";
    } catch {
      host = "";
    }
    let found = "direct";
    if (host && host !== location.hostname) {
      found = (SITES.find(([pattern]) => pattern.test(host)) || [null, "other"])[1];
    } else if (host) {
      found = "site";
    }
    session(SOURCE_KEY, found);
    return found;
  }

  // The developer's own browsers stay out of the numbers: luhovyimvp.dev/?count=off
  // once per browser (?count=on brings it back). Remembered on this device only.
  function uncounted() {
    const NO_COUNT = "wardly.nocount";
    try {
      const wish = new URLSearchParams(location.search).get("count");
      if (wish === "off") {
        localStorage.setItem(NO_COUNT, "1");
      } else if (wish === "on") {
        localStorage.removeItem(NO_COUNT);
      }
      return localStorage.getItem(NO_COUNT) === "1";
    } catch {
      return false;
    }
  }

  const source = trafficSource();
  // A driven browser (tests, screenshots, crawlers that say so) is not a visitor.
  const COUNTED = !uncounted() && !navigator.webdriver;
  const DOWNLOAD = `${API}/d/${encodeURIComponent(source)}${COUNTED ? "" : "?count=off"}`;

  function countVisit() {
    if (!COUNTED || session("wardly.hit") || !navigator.sendBeacon || !/^https?:$/.test(location.protocol) || location.hostname === "localhost") {
      return;
    }
    session("wardly.hit", "1");
    try {
      navigator.sendBeacon(`${API}/v1/hit`, new Blob([JSON.stringify({ src: source })], { type: "text/plain" }));
    } catch {
      // Not counted; nothing else depends on it.
    }
  }

  // --- download: the latest release's installer ---------------------------------
  // The buttons go through the API (/d/<source>: counts, then redirects to the
  // latest installer); GitHub's release data only fills the version line.

  function renderRelease() {
    const buttons = document.querySelectorAll(".js-download");
    buttons.forEach((a) => (a.href = DOWNLOAD));
    // Linux packages: the same counted redirect, asking for a package.
    document.querySelectorAll("[data-os]").forEach(
      (a) => (a.href = `${DOWNLOAD}${DOWNLOAD.includes("?") ? "&" : "?"}os=${encodeURIComponent(a.dataset.os)}`)
    );
    if (!release) {
      return;
    }
    const mb = Math.round(release.size / 1024 / 1024);
    const text = lang === "en" ? EN.version(release.version, mb) : `Версія ${release.version} · Windows 10 і 11 · ${mb} МБ`;
    document.querySelectorAll(".js-release-meta").forEach((el) => (el.textContent = text));
    // The installer's VirusTotal report: shown only when the release notes carry
    // the report link for this very installer (the SHA-256 GitHub keeps for the
    // asset) — the release workflow adds it after a successful upload.
    document.querySelectorAll(".js-vt").forEach((el) => {
      el.hidden = !release.report;
      if (release.report) {
        el.querySelector("a").href = release.report;
      }
    });
    // The SHA-256 GitHub keeps for the installer, to compare with Get-FileHash.
    document.querySelectorAll(".js-sha").forEach((el) => (el.hidden = !release.sha256));
    document.querySelectorAll(".js-sha-value").forEach((el) => (el.textContent = release.sha256 || ""));
  }

  // --- install help: opened by a download click or the «Windows warns» link ------

  const installHelp = document.getElementById("install");
  if (installHelp) {
    document.querySelectorAll(".js-download").forEach((a) =>
      a.addEventListener("click", () => {
        installHelp.open = true;
      })
    );
    document.querySelectorAll(".js-install-link").forEach((a) =>
      a.addEventListener("click", () => {
        installHelp.open = true;
      })
    );
    document.querySelectorAll(".js-sha-copy").forEach((button) =>
      button.addEventListener("click", async () => {
        const value = release && release.sha256;
        if (!value || !navigator.clipboard) {
          return;
        }
        try {
          await navigator.clipboard.writeText(value);
          const label = button.textContent;
          button.textContent = "✓";
          setTimeout(() => (button.textContent = label), 1500);
        } catch {
          // Clipboard refused: the hash stays visible to select by hand.
        }
      })
    );
  }

  async function loadRelease() {
    try {
      const response = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
        headers: { Accept: "application/vnd.github+json" }
      });
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      const asset = (data.assets || []).find((a) => /Setup-.*\.exe$/i.test(a.name));
      if (asset) {
        const digest = String(asset.digest || "").match(/^sha256:([0-9a-f]{64})$/);
        const report = digest ? `https://www.virustotal.com/gui/file/${digest[1]}` : null;
        release = {
          report: report && String(data.body || "").includes(report) ? report : null,
          sha256: digest ? digest[1] : null,
          size: asset.size,
          version: String(data.tag_name || "").replace(/^v/, "")
        };
        renderRelease();
      }
    } catch {
      // Offline or rate-limited: the buttons keep pointing at the releases page.
    }
  }

  // --- scroll effects -------------------------------------------------------------

  const nav = document.querySelector(".nav");
  const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // The menu button (phones and narrow windows): the section links as a panel
  // under the header; a link, Escape, a tap outside or a wide window closes it.
  const menuButton = document.querySelector(".nav-toggle");
  const menu = document.getElementById("site-menu");
  if (menuButton && menu) {
    const setMenu = (open) => {
      nav.classList.toggle("menu-open", open);
      menuButton.setAttribute("aria-expanded", String(open));
    };
    menuButton.addEventListener("click", () => setMenu(!nav.classList.contains("menu-open")));
    menu.addEventListener("click", (event) => {
      if (event.target.closest("a")) setMenu(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && nav.classList.contains("menu-open")) {
        setMenu(false);
        menuButton.focus();
      }
    });
    document.addEventListener("click", (event) => {
      if (nav.classList.contains("menu-open") && !nav.contains(event.target)) setMenu(false);
    });
    window.matchMedia("(min-width: 1081px)").addEventListener("change", (event) => {
      if (event.matches) setMenu(false);
    });
  }

  const revealed = document.querySelectorAll(".section-head, .tile, .step, .split-copy, .split-stage, .mode, .heroes, .final-inner");
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("shown");
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px" }
    );
    revealed.forEach((el) => {
      el.classList.add("reveal");
      observer.observe(el);
    });
  }

  // --- screenshots at full size ----------------------------------------------------
  // The app windows on the page are scaled down; a click opens the real
  // screenshot at full size (a <dialog>: Esc, a click or the button closes it).

  const zoomable = document.querySelectorAll(".win img, .step-shot img");
  if (zoomable.length && typeof HTMLDialogElement === "function") {
    const dialog = document.createElement("dialog");
    dialog.className = "lightbox";
    const picture = document.createElement("img");
    picture.alt = "";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "lightbox-close";
    close.textContent = "×";
    dialog.append(picture, close);
    document.body.append(dialog);
    dialog.addEventListener("click", () => dialog.close());
    for (const img of zoomable) {
      img.classList.add("zoomable");
      img.tabIndex = 0;
      const open = () => {
        picture.src = img.currentSrc || img.src;
        picture.alt = img.alt;
        close.setAttribute("aria-label", document.documentElement.lang === "uk" ? "Закрити" : "Close");
        dialog.showModal();
      };
      img.addEventListener("click", open);
      img.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    }
  }

  applyLanguage(initialLanguage());
  loadRelease();
  countVisit();
})();
