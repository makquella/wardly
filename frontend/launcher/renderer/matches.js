// Matches, match review and Progress views of the control panel.
//
// Data comes from the backend through the main process
// (window.launcherApi.player(op, args), see PLAYER_OPS in main.js):
//   status, link, linkDetected, unlink, sync, matches, match, refreshMatch, career.
// Review texts (titles, explanations, drills) are already localized by the
// backend; this file only holds the UI labels (uk/en). Everything is built
// with DOM nodes and textContent — backend strings are never parsed as HTML.
(function () {
  const TEXT = window.WardlyMatchTexts.create({ number, decimal, clock, plural });
  const { combatScore } = window.WardlyMatchContract;

  // Chart colours come from the design tokens (assets/ui/tokens.css).
  const cssVar = (name, fallback) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  const VIZ_1 = cssVar("--viz-1", "#3987e5");
  const VIZ_2 = cssVar("--viz-2", "#e5963a");
  const TAB_KEY = "dota-ai-coach.tab";
  const SORT_KEY = "dota-ai-coach.matches-sort";
  const SORT_KEYS = ["date", "score", "gpm", "lh_10", "duration", "kda"];
  const api = window.launcherApi;

  const state = {
    filter: { heroId: null, result: "all" },
    // «Open a match by its number»: the typed text, the line under it, a fetch going on.
    openNumber: { value: "", note: "", busy: false },
    // The match table's order: newest first until a column header is clicked
    // (remembered across restarts, SORT_KEY; the filters are not: a filter left
    // on would look like missing matches next time).
    sort: savedSort(),
    careerHero: null,
    heroes: [],
    matchesStats: null,
    matchesSkipped: null,
    locale: "en",
    view: "home",
    status: null,
    player: null,
    matches: [],
    matchesTotal: 0,
    matchesLoaded: false,
    matchId: null,
    match: null,
    chartMetric: "lh",
    career: null,
    profile: null,
    friends: null,
    linkError: "",
    lastPlayerRefresh: 0,
    // AI coach settings panel: null (closed) | "form" | "info"
    aiPanel: null,
    ai: null,
    aiMessage: null
  };

  function plural(n, one, few, many) {
    n = Math.abs(Number(n) || 0);
    if (n % 10 === 1 && n % 100 !== 11) {
      return one;
    }
    if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) {
      return few;
    }
    return many;
  }

  function t(key, ...args) {
    const table = TEXT[state.locale] || TEXT.en;
    const value = key.split(".").reduce((node, part) => (node ? node[part] : undefined), table) ??
      key.split(".").reduce((node, part) => (node ? node[part] : undefined), TEXT.en);
    return typeof value === "function" ? value(...args) : value ?? key;
  }

  // Like t() but empty for unknown keys (backend status codes).
  function tOptional(key) {
    const table = TEXT[state.locale] || TEXT.en;
    const value = key.split(".").reduce((node, part) => (node ? node[part] : undefined), table);
    return typeof value === "string" ? value : "";
  }

  function clock(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value)) {
      return "—";
    }
    const sign = value < 0 ? "-" : "";
    const abs = Math.abs(Math.round(value));
    return `${sign}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, "0")}`;
  }

  // `style` "short" («3 год тому») where a column is narrow (the match table).
  function relativeTime(unixSeconds, style = "long") {
    if (!unixSeconds) {
      return "—";
    }
    const diff = Math.round(unixSeconds - Date.now() / 1000);
    const rtf = new Intl.RelativeTimeFormat(state.locale, { numeric: "auto", style });
    const abs = Math.abs(diff);
    if (abs < 3600) {
      return rtf.format(Math.round(diff / 60), "minute");
    }
    if (abs < 86400) {
      return rtf.format(Math.round(diff / 3600), "hour");
    }
    // Short: «учора», then the date («2 жовт.»): «3 дн. тому» broke the column.
    if (style === "short" && abs >= 86400 * 1.5) {
      return new Date(unixSeconds * 1000).toLocaleDateString(state.locale, { day: "numeric", month: "short" });
    }
    if (abs < 86400 * 30) {
      return rtf.format(Math.round(diff / 86400), "day");
    }
    return new Date(unixSeconds * 1000).toLocaleDateString(state.locale);
  }

  function relativeIso(iso) {
    const ms = Date.parse(iso || "");
    return Number.isFinite(ms) ? relativeTime(ms / 1000) : "—";
  }

  function number(value) {
    return value === null || value === undefined ? "—" : Math.round(value).toLocaleString(state.locale);
  }

  // A fraction the way the player reads it: «7,5» in Ukrainian, «7.5» in English.
  function decimal(value, digits = 1) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      return "—";
    }
    return Number(value).toLocaleString(state.locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) {
        continue;
      }
      if (key === "class") {
        node.className = value;
      } else if (key === "text") {
        node.textContent = value;
      } else if (key.startsWith("on")) {
        node.addEventListener(key.slice(2), value);
      } else if (key === "dataset") {
        Object.assign(node.dataset, value);
      } else {
        node.setAttribute(key, value === true ? "" : String(value));
      }
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) {
        continue;
      }
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function icon(name) {
    return h("i", { "data-icon": name, "aria-hidden": "true" });
  }

  function hydrate(root) {
    window.LucideIcons?.hydrate(root);
    // A table cell with nothing to show («—») steps back from the numbers.
    root?.querySelectorAll?.("td").forEach((cell) => {
      if (cell.childElementCount === 0 && cell.textContent.trim() === "—") {
        cell.classList.add("is-empty");
      }
    });
  }

  // A hero portrait / item icon next to its name (dota-icons.js); plain text
  // when the icon module is missing.
  function heroLabel(value, name, size = "sm") {
    const text = name || window.DotaIcons?.hero(value)?.name || String(value ?? "—");
    if (!window.DotaIcons || value === null || value === undefined || value === "") {
      return h("span", { class: "hero-cell", text });
    }
    return h("span", { class: "hero-cell with-pic" }, window.DotaIcons.heroPicture(document, value, size), h("span", { text }));
  }

  function itemPic(value, size = "sm") {
    return window.DotaIcons ? window.DotaIcons.itemPicture(document, value, size) : null;
  }

  function itemLabel(value, name, size = "sm") {
    return h("span", { class: "item-label with-pic" }, itemPic(value, size), h("span", { text: name || String(value ?? "") }));
  }

  function card(title, iconName, body, extraHead) {
    return h(
      "section",
      { class: "card" },
      h("header", { class: "card-head" }, icon(iconName), h("h2", { text: title }), extraHead ? h("span", { class: "card-head-extra" }, extraHead) : null),
      h("div", { class: "card-body" }, body)
    );
  }

  // A long list shows its first `keep` items and a «show N more» button; the
  // rest is only hidden on screen, so a saved PDF keeps every item.
  function foldList(list, keep) {
    const items = Array.from(list.children);
    if (items.length <= keep + 1) {
      return list;
    }
    items.slice(keep).forEach((item) => item.classList.add("fold-extra"));
    const hidden = items.length - keep;
    const wrap = h("div", { class: "fold is-folded" }, list);
    const toggle = h("button", { class: "btn btn-ghost btn-sm fold-toggle no-print", type: "button", text: t("foldMore", hidden) });
    toggle.addEventListener("click", () => {
      const folded = wrap.classList.toggle("is-folded");
      toggle.textContent = folded ? t("foldMore", hidden) : t("foldLess");
    });
    wrap.appendChild(toggle);
    return wrap;
  }

  function emptyState(iconName, title, hint, action) {
    return h("div", { class: "empty" }, icon(iconName), h("p", { class: "empty-title", text: title }), h("p", { class: "empty-hint", text: hint }), action || null);
  }

  function skeletonRows(count) {
    return h(
      "div",
      { class: "skeleton-stack" },
      Array.from({ length: count }, () => h("span", { class: "skeleton skeleton-line" }))
    );
  }

  function resultBadge(win) {
    const tone = win === true ? "good" : win === false ? "bad" : "idle";
    return h("span", { class: "result", dataset: { tone } }, h("span", { class: "dot", "data-tone": tone }), h("span", { text: win === true ? t("win") : win === false ? t("loss") : t("unknownResult") }));
  }

  // «What does this mean?» under a card whose numbers are not obvious: a
  // folded explanation, so it costs one line until someone asks.
  function explain(key) {
    return h("details", { class: "explain no-print" }, h("summary", {}, icon("circle-help"), h("span", { text: t("explainTitle") })), h("p", { text: t(key) }));
  }

  // The letter next to the score ring: the ring already carries the colour, so
  // no third signal (a coloured dot) for the same value.
  function gradeLetter(score) {
    const letter = score >= 80 ? "A" : score >= 65 ? "B" : score >= 50 ? "C" : "D";
    return h("span", { class: "grade", text: letter });
  }

  // --- navigation -------------------------------------------------------------

  // Back / forward like a browser (the mouse's side buttons, Alt+←/→): the
  // places the player went through — a tab or a match review — newest last.
  // A review also keeps the tab it was opened from, which its «‹» returns to.
  const { samePlace } = window.WardlyMatchNavigation;
  const navigation = window.WardlyMatchNavigation.create({ current: currentPlace, visit: goTo });

  function currentPlace() {
    return state.view === "match" && state.matchId ? { view: "match", matchId: state.matchId } : { view: state.view || "home" };
  }

  // Where each tab was scrolled when the player left it: back there (the
  // review's «‹», Esc, the mouse's back button) the list is where it was.
  const scrollMemory = {};

  function notePlace(next) {
    const here = currentPlace();
    if (here.view !== "match" && !samePlace(here, next)) {
      scrollMemory[here.view] = window.scrollY;
    }
    if (next.view === "match" && here.view !== "match") {
      state.reviewFrom = here.view;
    }
    navigation.note(next, Boolean(state.view));
  }

  function goTo(place) {
    if (place.view === "match") {
      openMatch(place.matchId);
    } else {
      setView(place.view, { restore: true });
    }
  }

  function goBack() {
    return navigation.back();
  }

  function goForward() {
    return navigation.forward();
  }

  // «‹ Матчі» / «‹ Головна»: a review goes back to the tab it came from.
  function leaveReview() {
    const seen = state.matchId;
    setView(state.reviewFrom && state.reviewFrom !== "match" ? state.reviewFrom : "matches", { restore: true });
    // The row of the match just read keeps the keyboard focus (↑/↓ go on from it).
    document.querySelector(`#matches-root tr.row-link[data-match-id="${CSS.escape(String(seen || ""))}"]`)?.focus({ preventScroll: true });
  }

  function reviewBackButton() {
    const from = state.reviewFrom && state.reviewFrom !== "match" ? state.reviewFrom : "matches";
    return h("button", { class: "btn btn-ghost btn-sm back", type: "button", onclick: leaveReview }, icon("chevron-left"), h("span", { text: t(`backTo.${from}`) }));
  }

  function setView(view, { remember = true, restore = false } = {}) {
    if (view !== "matches") matchListRequests.cancel();
    if (view !== "profile") invalidateProfile();
    if (view !== "progress") {
      careerRequests.cancel();
      clearTimeout(careerRefreshTimer);
    }
    if (view !== "match") {
      matchRequests.cancel();
      clearTimeout(matchRefreshTimer);
      notePlace({ view });
    }
    state.view = view;
    state.aiPanel = null;
    state.aiMessage = null;
    const tabView = view === "match" ? "matches" : view;
    for (const tab of document.querySelectorAll(".tabs [data-view]")) {
      tab.setAttribute("aria-selected", String(tab.dataset.view === tabView));
    }
    for (const name of ["home", "matches", "match", "progress", "profile", "settings"]) {
      document.getElementById(`view-${name}`)?.classList.toggle("hidden", name !== view);
    }
    if (remember && view !== "match") {
      try {
        localStorage.setItem(TAB_KEY, view);
      } catch {
        // Per-viewer convenience only.
      }
    }
    if (view === "matches") {
      loadMatches();
    } else if (view === "progress") {
      loadCareer();
    } else if (view === "profile") {
      loadProfile();
    } else if (view === "settings") {
      renderAiSettings({ load: true });
    }
    // The tab keeps its last drawing while hidden, so its old place is there.
    window.scrollTo({ top: restore ? scrollMemory[view] || 0 : 0 });
  }

  async function call(op, args) {
    try {
      return await api.player(op, args);
    } catch (error) {
      return { ok: false, code: "request_failed", detail: error.message };
    }
  }

  const playerStatusRequests = window.WardlyPlayerStatusRequests.create({
    request: () => call("status"),
    apply: result => {
      if (result.ok) {
        state.player = result.data;
        state.lastPlayerRefresh = Date.now();
      }
    }
  });

  function refreshPlayer() {
    return playerStatusRequests.load();
  }

  // --- account ----------------------------------------------------------------

  // No answer from the coach process (stopped, crashed or still starting): say
  // so instead of a skeleton forever or a «link your account» form for an
  // account that is linked. onStatus reloads the tab once it runs.
  function offlinePage(view) {
    const titles = { matches: ["matchesTitle", "matchesSub"], progress: ["progressTitle", "progressSub"], profile: ["pfTitle", "pfSub"] };
    const [title, sub] = titles[view] || titles.matches;
    const starting = ["starting", "running"].includes(state.status?.backend);
    const button = starting
      ? null
      : h(
          "button",
          {
            class: "btn btn-primary btn-sm",
            type: "button",
            onclick: async (event) => {
              event.currentTarget.disabled = true;
              await api.startBackend?.();
            }
          },
          icon("play"),
          h("span", { text: t("offlineStart") })
        );
    const body = starting
      ? emptyState("hourglass", t("offlineStarting"), t("offlineStartingHint"))
      : emptyState("power", t("offlineTitle"), t("offlineHint"), button);
    return [pageHead(t(title), t(sub)), h("section", { class: "card" }, h("div", { class: "card-body" }, body))];
  }

  // The tab's title and the link form, with what the tab will show once linked.
  function linkPage(view) {
    const titles = { matches: ["matchesTitle", "matchesSub"], progress: ["progressTitle", "progressSub"], profile: ["pfTitle", "pfSub"] };
    const [title, sub] = titles[view] || titles.matches;
    return [pageHead(t(title), t(sub)), linkPanel(view)];
  }

  function linkPanel(view) {
    const input = h("input", { class: "input input-lg", type: "text", placeholder: t("linkPlaceholder"), "aria-label": t("linkPlaceholder"), autocomplete: "off", spellcheck: "false" });
    const error = h("p", { class: "form-error", role: "alert", text: state.linkError });
    const button = h("button", { class: "btn btn-primary", type: "submit" }, icon("link"), h("span", { text: t("linkButton") }));
    const form = h(
      "form",
      {
        class: "link-form",
        onsubmit: async (event) => {
          event.preventDefault();
          button.disabled = true;
          playerStatusRequests.cancel();
          invalidateProfile();
          const result = await call("link", { steam: input.value });
          button.disabled = false;
          if (result.ok) {
            state.linkError = "";
            playerStatusRequests.cancel();
            matchListRequests.cancel();
            careerRequests.cancel();
            clearTimeout(careerRefreshTimer);
            invalidateProfile({ clear: true });
            state.player = result.data;
            state.matchesLoaded = false;
            await afterLink();
          } else {
            state.linkError = tOptional(`linkErrors.${result.code}`) || result.detail || "";
            error.textContent = state.linkError;
          }
        }
      },
      input,
      button
    );
    const detected = state.player && state.player.detected;
    return h(
      "section",
      { class: "card link-card" },
      h(
        "div",
        { class: "card-body" },
        h("div", { class: "link-head" }, h("span", { class: "link-icon" }, icon("user")), h("div", {}, h("h2", { class: "link-title", text: t("linkTitle") }), h("p", { class: "link-hint", text: t("linkHint") }))),
        detected
          ? h(
              "div",
              { class: "detected" },
              h("span", { text: t("detected", detected.persona_name || detected.account_id) }),
              h("button", { class: "btn btn-primary btn-sm", type: "button", onclick: linkDetected }, h("span", { text: t("detectedLink") }))
            )
          : null,
        form,
        error,
        linkPerks(view)
      )
    );
  }

  function linkPerks(view, heading = "linkSoon") {
    const perks = t(`linkPerks.${view}`);
    if (!Array.isArray(perks)) {
      return null;
    }
    return h(
      "div",
      { class: "link-perks" },
      h("p", { class: "link-perks-title", text: t(heading) }),
      h("ul", {}, perks.map(([name, text]) => h("li", {}, icon(name), h("span", { text }))))
    );
  }

  async function linkDetected() {
    playerStatusRequests.cancel();
    invalidateProfile();
    const result = await call("linkDetected");
    if (result.ok) {
      playerStatusRequests.cancel();
      matchListRequests.cancel();
      careerRequests.cancel();
      clearTimeout(careerRefreshTimer);
      invalidateProfile({ clear: true });
      state.player = result.data;
      state.matchesLoaded = false;
      await afterLink();
    }
  }

  async function afterLink() {
    state.lastPlayerRefresh = 0;
    if (state.view === "matches") return loadMatches(true);
    if (state.view === "progress") return loadCareer();
    if (state.view === "profile") return loadProfile();
  }

  function playerBar() {
    const player = state.player || {};
    const info = player.player || {};
    const name = info.persona_name || t("friendId", player.account_id);
    const avatar = info.avatar_url
      ? h("img", { class: "avatar", src: info.avatar_url, alt: "", referrerpolicy: "no-referrer", onerror: (e) => e.target.replaceWith(avatarFallback(name)) })
      : avatarFallback(name);
    const sync = player.sync || {};
    let syncText = t("syncNever");
    let syncTone = "idle";
    if (!player.opendota) {
      syncText = t("syncOffline");
    } else if (sync.state === "running" || sync.state === "queued") {
      syncText = t("syncing");
      syncTone = "warn";
    } else if (sync.state === "error") {
      syncText = tOptional(`syncError.${sync.error_code}`) || sync.error || "";
      syncTone = "bad";
    } else if (sync.at) {
      syncText = t("syncedAt", relativeIso(sync.at));
      syncTone = "good";
    }
    const refreshButton = h(
      "button",
      {
        class: "btn btn-sm",
        type: "button",
        disabled: !player.opendota || sync.state === "running" || sync.state === "queued",
        onclick: async () => {
          await call("sync");
          await refreshPlayer();
          renderMatches();
          pollSync();
        }
      },
      icon("refresh-cw"),
      h("span", { text: t("refresh") })
    );
    const change = h(
      "button",
      {
        class: "btn btn-sm btn-ghost",
        type: "button",
        onclick: async () => {
          playerStatusRequests.cancel();
          invalidateProfile();
          const result = await call("unlink");
          if (result.ok) {
            playerStatusRequests.cancel();
            matchListRequests.cancel();
            careerRequests.cancel();
            clearTimeout(careerRefreshTimer);
            invalidateProfile({ clear: true });
            state.player = result.data;
            state.matches = [];
            state.matchesLoaded = false;
            renderMatches();
          }
        }
      },
      h("span", { text: t("change") })
    );
    const detected = player.detected;
    return h(
      "div",
      { class: "player-bar-wrap" },
      h(
        "section",
        { class: "player-bar" },
        avatar,
        h(
          "div",
          { class: "player-info" },
          h("p", { class: "player-name", text: name }),
          h("p", { class: "player-meta" }, h("span", { class: "dot", "data-tone": syncTone }), h("span", { text: syncText }))
        ),
        h("div", { class: "player-actions" }, refreshButton, change)
      ),
      detected
        ? h(
            "div",
            { class: "notice" },
            icon("info"),
            h("span", { text: t("detectedOther", detected.persona_name || detected.account_id) }),
            h("button", { class: "btn btn-sm", type: "button", onclick: linkDetected }, h("span", { text: t("switchAccount") }))
          )
        : null
    );
  }

  function avatarFallback(name) {
    return h("span", { class: "avatar avatar-fallback", "aria-hidden": "true", text: String(name || "?").trim().charAt(0).toUpperCase() || "?" });
  }

  let syncTimer = null;
  function pollSync() {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(async () => {
      await refreshPlayer();
      const running = ["queued", "running"].includes(state.player?.sync?.state) || (state.player?.pending_jobs || 0) > 0;
      if (state.view === "matches") {
        await loadMatches(true);
      }
      if (running) {
        pollSync();
      }
    }, 2500);
  }

  // --- matches table ------------------------------------------------------------

  const matchListRequests = window.WardlyMatchListRequests.create({
    current: () => ({
      view: state.view, accountId: state.player?.account_id ?? null,
      linked: Boolean(state.player?.linked), count: state.matches.length,
      heroId: state.filter.heroId, result: state.filter.result,
      sort: state.sort.key, asc: state.sort.asc
    }),
    prepare: async () => {
      if (!state.player || Date.now() - state.lastPlayerRefresh > 5000) {
        if (!state.matchesLoaded) {
          document.getElementById("matches-root").replaceChildren(card(t("matchesTitle"), "history", skeletonRows(5)));
        }
        await refreshPlayer();
      }
    },
    request: args => call("matches", args)
  });

  async function loadMatches(force = false) {
    if (force) state.lastPlayerRefresh = 0;
    return matchListRequests.replace(result => {
      if (result?.ok) {
        state.matches = result.data.items || [];
        state.matchesTotal = result.data.total || 0;
        state.matchesStats = result.data.stats || null;
        state.matchesSkipped = result.data.skipped || null;
        state.heroes = result.data.heroes || [];
        state.matchesLoaded = true;
      }
      renderMatches();
      const syncing = ["queued", "running"].includes(state.player?.sync?.state) || (state.player?.pending_jobs || 0) > 0;
      if (syncing) pollSync();
    });
  }

  function renderMatches() {
    const root = document.getElementById("matches-root");
    const focusedMatch = root.contains(document.activeElement)
      ? document.activeElement.closest("tr.row-link")?.dataset.matchId : null;
    if (!state.player) {
      root.replaceChildren(...offlinePage("matches"));
      hydrate(root);
      return;
    }
    if (!state.player.linked) {
      root.replaceChildren(...linkPage("matches"));
      hydrate(root);
      return;
    }
    const liveMatch = state.player.live_match;
    const liveNotice = liveMatch ? h("div", { class: "notice" }, h("span", { class: "dot dot-live", "data-tone": "good" }), h("span", { text: t("liveMatch", liveMatch.hero) })) : null;
    let body;
    const filtered = state.filter.heroId !== null || state.filter.result !== "all";
    if (!state.matchesLoaded) {
      body = skeletonRows(5);
    } else if (!state.matches.length && filtered) {
      body = emptyState("history", t("filterEmptyTitle"), t("filterEmptyHint"));
    } else if (!state.matches.length) {
      body = emptyState("history", t("noMatchesTitle"), t("noMatchesHint"));
    } else {
      body = h("div", { class: "table-wrap" }, matchesTable(state.matches));
      if (state.matchesTotal > state.matches.length) {
        body = h(
          "div",
          {},
          body,
          h(
            "button",
            {
              class: "btn btn-ghost btn-block",
              type: "button",
              onclick: async () => {
                return matchListRequests.more(result => {
                  if (result.ok) {
                    state.matches = state.matches.concat(result.data.items || []);
                    renderMatches();
                  }
                });
              }
            },
            h("span", { text: t("more") })
          )
        );
      }
    }
    const filters = state.matchesLoaded && (state.heroes.length > 1 || filtered) ? filterBar() : null;
    const skipped = state.matchesLoaded && state.matchesSkipped
      ? h("p", { class: "muted small skipped-note", text: t("skippedModes", state.matchesSkipped.count, state.matchesSkipped.turbo, state.matchesSkipped.of) })
      : null;
    root.replaceChildren(
      pageHead(t("matchesTitle"), t("matchesSub")),
      playerBar(),
      liveNotice || "",
      card(t("matchesTableTitle"), "history", [filters, body, skipped].filter(Boolean), state.matchesTotal ? h("span", { class: "num", text: String(state.matchesTotal) }) : null)
    );
    hydrate(root);
    // A return from the review focuses its row before loadMatches completes.
    // Keep that keyboard position when a later API response replaces the table.
    if (focusedMatch) {
      root.querySelector(`tr.row-link[data-match-id="${CSS.escape(focusedMatch)}"]`)?.focus({ preventScroll: true });
    }
  }

  function savedSort() {
    try {
      const saved = JSON.parse(localStorage.getItem(SORT_KEY) || "null");
      if (saved && SORT_KEYS.includes(saved.key)) {
        return { key: saved.key, asc: saved.asc === true };
      }
    } catch {
      // Storage unavailable or garbled: newest first.
    }
    return { key: "date", asc: false };
  }

  function sortedByDate() {
    return state.sort.key === "date" && !state.sort.asc;
  }

  // A header click: the same column flips the order, another one starts from
  // the biggest (the newest for «Played»).
  function setSort(key) {
    state.sort = state.sort.key === key ? { key, asc: !state.sort.asc } : { key, asc: false };
    try {
      localStorage.setItem(SORT_KEY, JSON.stringify(state.sort));
    } catch {
      // A convenience only.
    }
    state.matches = [];
    loadMatches();
  }

  function setFilter(patch) {
    state.filter = { ...state.filter, ...patch };
    state.matches = [];
    loadMatches();
  }

  // Result + hero filter and what the filtered games add up to.
  function filterBar() {
    const results = h(
      "div",
      { class: "segmented segmented-sm", role: "radiogroup", "aria-label": t("filterResult") },
      ["all", "win", "loss"].map((value) =>
        h("button", {
          type: "button",
          role: "radio",
          "aria-checked": String(state.filter.result === value),
          text: t(`filterResults.${value}`),
          onclick: () => setFilter({ result: value })
        })
      )
    );
    const select = h(
      "select",
      {
        class: "input select",
        "aria-label": t("filterHero"),
        onchange: (event) => setFilter({ heroId: event.target.value === "" ? null : Number(event.target.value) })
      },
      h("option", { value: "", text: t("filterAllHeroes") }),
      state.heroes.map((hero) => {
        const option = h("option", { value: String(hero.hero_id), text: `${hero.hero || "—"} · ${hero.games}` });
        option.selected = state.filter.heroId === hero.hero_id;
        return option;
      })
    );
    const stats = state.matchesStats;
    const summary = stats && stats.games
      ? h("p", { class: "muted small filter-summary num", text: t("filterSummary", stats.games, stats.winrate, stats.avg_score) })
      : null;
    return h("div", { class: "filter-bar" }, h("div", { class: "filter-controls" }, results, select, openByNumberForm()), summary);
  }

  // «Open a match by its number»: an older game than the synced history, or a
  // link from OpenDota, Dotabuff or STRATZ (0.51). The state lives in `state`,
  // since the table redraws every 15 s while a fetch may take a minute.
  function openByNumberForm() {
    const input = h("input", {
      class: "input open-number-input",
      type: "text",
      inputmode: "numeric",
      placeholder: t("openPlaceholder"),
      "aria-label": t("openPlaceholder"),
      value: state.openNumber.value || ""
    });
    input.addEventListener("input", () => {
      state.openNumber.value = input.value;
    });
    const button = h("button", { class: "btn btn-sm", type: "submit", disabled: state.openNumber.busy }, icon("search"), h("span", { text: t("openButton") }));
    const form = h("form", { class: "open-number no-print" }, input, button, h("span", { class: "muted small open-number-note", role: "status", "aria-live": "polite", text: state.openNumber.note || "" }));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      openByNumber(input.value);
    });
    return form;
  }

  function matchIdFrom(text) {
    const found = String(text || "").match(/(\d{6,19})/);
    return found ? found[1] : null;
  }

  function setOpenNote(note, busy = false) {
    state.openNumber = { ...state.openNumber, note, busy };
    for (const el of document.querySelectorAll(".open-number-note")) {
      el.textContent = note;
    }
    for (const el of document.querySelectorAll(".open-number button")) {
      el.disabled = busy;
    }
  }

  async function openByNumber(text) {
    const id = matchIdFrom(text);
    if (!id) {
      setOpenNote(t("openBad"));
      return;
    }
    if (state.matches.some((row) => String(row.match_id) === id)) {
      setOpenNote("");
      openMatch(id);
      return;
    }
    setOpenNote(t("openLoading"), true);
    let result = await call("addMatch", { matchId: id });
    // OpenDota answers a match in seconds, rarely in a minute.
    for (let tries = 0; tries < 45 && result.ok && result.data.state === "pending"; tries += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      result = await call("addMatchStatus", { matchId: id });
    }
    const outcome = result.ok ? result.data.state : "error";
    if (outcome === "ready") {
      state.openNumber.value = "";
      setOpenNote("");
      openMatch(id);
      return;
    }
    setOpenNote(tOptional(`openErrors.${outcome}`) || t("openErrors.error"));
  }

  // A column header that orders the table by its column.
  function sortHeader(key, label, className = "") {
    const active = state.sort.key === key;
    const direction = active ? (state.sort.asc ? "ascending" : "descending") : "none";
    return h(
      "th",
      { class: className, "aria-sort": direction },
      h(
        "button",
        {
          type: "button",
          class: `sort-btn${active ? " is-active" : ""}`,
          title: t("sortBy", label),
          onclick: () => setSort(key)
        },
        h("span", { text: label }),
        icon(active && state.sort.asc ? "chevron-up" : "chevron-down")
      )
    );
  }

  function matchesTable(rows) {
    const head = h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { text: t("colResult") }),
        h("th", { text: t("colHero") }),
        sortHeader("kda", t("colKda"), "num-col"),
        sortHeader("gpm", t("colGpm"), "num-col"),
        sortHeader("lh_10", t("colLh10"), "num-col hide-narrow"),
        sortHeader("duration", t("colDuration"), "num-col"),
        sortHeader("score", t("colScore")),
        h("th", { class: "items-col", text: t("colItems") }),
        sortHeader("date", t("colWhen"), "hide-narrow")
      )
    );
    const body = h("tbody", {});
    for (const row of rows) {
      const open = () => openMatch(row.match_id);
      body.append(
        h(
          "tr",
          {
            class: "row-link",
            tabindex: 0,
            role: "button",
            dataset: { result: row.win === true ? "win" : row.win === false ? "loss" : "unknown", matchId: String(row.match_id) },
            "aria-label": `${row.hero || ""} ${row.win === true ? t("win") : row.win === false ? t("loss") : ""}`,
            onclick: open,
            onkeydown: (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                open();
              } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                // ↑/↓ walk the rows, Enter opens one.
                const next = event.key === "ArrowDown" ? event.currentTarget.nextElementSibling : event.currentTarget.previousElementSibling;
                if (next) {
                  event.preventDefault();
                  next.focus();
                }
              }
            }
          },
          h("td", {}, resultBadge(row.win)),
          h(
            "td",
            {},
            h(
              "span",
              { class: "hero-note-cell" },
              heroLabel(row.hero_id || row.hero, row.hero || "—"),
              // «Нотатка»: the player's own line, read on hover.
              row.note ? h("span", { class: "row-note", title: row.note, "aria-label": `${t("noteLabel")}: ${row.note}` }, icon("sticky-note")) : null
            )
          ),
          h("td", { class: "num-col num", text: combatScore(row) }),
          h("td", { class: "num-col num", text: number(row.gpm) }),
          h("td", { class: "num-col num hide-narrow", text: number(row.lh_10) }),
          h("td", { class: "num-col num", text: clock(row.duration) }),
          h("td", {}, h("span", { class: "score-cell" }, scoreRing(row.score, "sm"), row.score == null ? null : gradeLetter(row.score))),
          itemsCell(row.items),
          h("td", { class: "muted hide-narrow when-col", text: relativeTime(row.start_time, "short") })
        )
      );
    }
    return h("table", { class: "table" }, head, body);
  }

  // The final inventory as six small icons (an empty slot keeps its place, so
  // the rows line up); a match never fetched in full has none: a dash.
  function itemsCell(items) {
    if (!Array.isArray(items) || !items.length || !window.DotaIcons) {
      return h("td", { class: "items-col", text: "—" });
    }
    const slots = [...items.slice(0, 6), ...Array(Math.max(0, 6 - items.length)).fill(null)];
    return h(
      "td",
      { class: "items-col" },
      h(
        "span",
        { class: "items-cell" },
        slots.map((key) => (key ? window.DotaIcons.itemPicture(document, key, "sm") : h("span", { class: "item-slot", "aria-hidden": "true" })))
      )
    );
  }

  // --- match review -------------------------------------------------------------

  const matchRequests = window.WardlyMatchRequests.create({
    current: () => ({view: state.view, matchId: state.matchId, locale: state.locale}),
    request: matchId => call("match", { matchId })
  });

  async function openMatch(matchId) {
    state.adviceLogOpen = false;
    notePlace({ view: "match", matchId: String(matchId) });
    state.matchId = String(matchId);
    state.match = null;
    setView("match", { remember: false });
    renderMatch();
    return matchRequests.load(state.matchId, result => {
      state.match = result.ok ? result.data : { error: result.code };
      renderMatch();
      scheduleMatchRefresh(String(matchId));
    });
  }

  // While the review is loading (queued OpenDota fetch) or OpenDota is still
  // parsing the replay, re-ask the backend; stops when the view changes.
  const PENDING_PARSE = new Set(["waiting_opendota", "parsing"]);
  let matchRefreshTimer = null;

  function scheduleMatchRefresh(matchId) {
    clearTimeout(matchRefreshTimer);
    const detail = state.match;
    if (!detail || detail.error || state.matchId !== matchId || state.view !== "match") {
      return;
    }
    const coachPending = detail.coach?.state === "pending";
    const waiting = detail.loading || coachPending || PENDING_PARSE.has(detail.parse_status);
    if (!waiting) {
      return;
    }
    const fast = detail.loading || coachPending;
    matchRefreshTimer = setTimeout(() => openMatchQuietly(matchId), fast ? 4000 : 30000);
  }

  async function openMatchQuietly(matchId) {
    if (state.matchId !== matchId || state.view !== "match") {
      return;
    }
    return matchRequests.load(matchId, result => {
      if (result.ok) {
        const changed = JSON.stringify(result.data) !== JSON.stringify(state.match);
        state.match = result.data;
        // Don't wipe a key or a question the player is typing, or a question on its way.
        const asking = state.askBusy || Boolean(document.querySelector(".ask-input")?.value.trim()) || Boolean(document.querySelector(".review-note-input"));
        if (changed && state.aiPanel !== "form" && !asking) {
          renderMatch();
        }
      }
      scheduleMatchRefresh(matchId);
    });
  }

  // Saves the current view as a PDF (light print theme, see @media print).
  // «Поділитися розбором»: a link to the public part of the review (main.js createShare).
  // `kind` "progress": the same panel for the Progress page (main.js keys it "progress").
  function shareButton(panel, detail, kind = "match") {
    // The title names it when the sticky bar shows the icon alone.
    const button = h("button", { class: "btn btn-ghost btn-sm", type: "button", "aria-expanded": "false", title: t("shareButton") }, icon("share-2"), h("span", { text: t("shareButton") }));
    button.addEventListener("click", async () => {
      const open = panel.hidden;
      panel.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      if (open) {
        panel.replaceChildren(skeletonRows(2));
        const status = await api.shareStatus(shareKey(detail, kind));
        renderSharePanel(panel, detail, status && status.ok ? status.share : null, "", kind);
      }
    });
    return button;
  }

  function shareKey(detail, kind) {
    return kind === "progress" ? "progress" : String(detail.match_id);
  }

  function renderSharePanel(panel, detail, share, message, kind = "match") {
    const matchId = shareKey(detail, kind);
    const text = (key, ...args) => t(kind === "progress" && TEXT.en[`${key}Progress`] ? `${key}Progress` : key, ...args);
    const coachReady = detail.coach && detail.coach.state === "ready";
    const note = h("p", { class: "muted small share-note", role: "status", text: message || "" });
    let body;
    if (share) {
      const expires = new Date(share.expiresAt).toLocaleDateString(state.locale === "uk" ? "uk-UA" : "en-GB");
      const link = h("input", { class: "input share-link", type: "text", readonly: true, value: share.url, "aria-label": text("shareLink") });
      link.addEventListener("focus", () => link.select());
      body = h(
        "div",
        { class: "share-body" },
        h("div", { class: "link-form" }, link, h("button", { class: "btn btn-primary", type: "button", onclick: async () => {
          const copied = await api.shareCopy(matchId);
          renderSharePanel(panel, detail, share, copied ? t("shareCopied") : "", kind);
        } }, icon("copy"), h("span", { text: t("shareCopy") }))),
        h("p", { class: "muted small", text: t("shareExpires", expires) + (share.withCoach ? ` ${t("shareWithCoach")}` : "") }),
        h(
          "div",
          { class: "toolbar-actions" },
          h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => api.shareOpen(matchId) }, icon("external-link"), h("span", { text: t("shareOpen") })),
          h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: async (event) => {
            event.currentTarget.disabled = true;
            const result = await api.shareDelete(matchId);
            renderSharePanel(panel, detail, result && result.ok ? null : share, result && result.ok ? t("shareDeleted") : t("shareFailed", result?.code || ""), kind);
          } }, icon("trash-2"), h("span", { text: t("shareDelete") }))
        )
      );
    } else {
      const coach = coachReady ? h("input", { type: "checkbox", class: "checkbox", id: "share-coach", checked: true }) : null;
      const create = h("button", { class: "btn btn-primary", type: "button" }, icon("share-2"), h("span", { text: t("shareCreate") }));
      create.addEventListener("click", async () => {
        create.disabled = true;
        note.textContent = t("shareCreating");
        const result = await api.shareCreate(matchId, Boolean(coach && coach.checked));
        renderSharePanel(panel, detail, result && result.ok ? result.share : null, result && result.ok ? "" : t("shareFailed", result?.code || ""), kind);
      });
      body = h(
        "div",
        { class: "share-body" },
        h("p", { text: text("shareWhat") }),
        h("p", { class: "muted small", text: text("shareNot") }),
        coach ? h("label", { class: "share-check" }, coach, h("span", { text: t("shareCoach") })) : null,
        h("div", { class: "toolbar-actions" }, create)
      );
    }
    panel.replaceChildren(
      h("header", { class: "card-head" }, icon("share-2"), h("h2", { text: text("shareTitle") })),
      h("div", { class: "card-body" }, body, note)
    );
    hydrate(panel);
  }

  // Portraits and item icons load lazily, so the ones never scrolled to would
  // print as initials: load them all first (each waits at most 3 s).
  function loadAllPictures() {
    const pending = Array.from(document.querySelectorAll('img[loading="lazy"]')).map((img) => {
      img.loading = "eager";
      if (img.complete) {
        return null;
      }
      return new Promise((resolve) => {
        const done = () => resolve();
        img.addEventListener("load", done, { once: true });
        img.addEventListener("error", done, { once: true });
        setTimeout(done, 3000);
      });
    });
    return Promise.all(pending);
  }

  function pdfButton(kind) {
    const note = h("span", { class: "muted small pdf-note" });
    const button = h(
      "button",
      {
        class: "btn btn-ghost btn-sm",
        type: "button",
        title: t("pdfSave"),
        onclick: async () => {
          button.disabled = true;
          note.textContent = "";
          const printDate = document.getElementById("print-date");
          if (printDate) {
            printDate.textContent = new Date().toLocaleDateString(state.locale === "uk" ? "uk-UA" : "en-GB");
          }
          try {
            await loadAllPictures();
            const result = await api.exportPdf(kind, kind === "match" ? String(state.matchId) : "");
            if (result && result.ok) {
              note.textContent = t("pdfSaved", result.path.split(/[\\/]/).pop());
            } else if (result && !result.canceled) {
              note.textContent = t("pdfFailed");
            }
          } finally {
            button.disabled = false;
          }
        }
      },
      icon("printer"),
      h("span", { text: t("pdfSave") })
    );
    return h("span", { class: "pdf-action" }, note, button);
  }

  // A review that fails to draw must say so: before, the loading skeleton
  // stayed on screen forever.
  function renderMatch() {
    try {
      drawMatch();
    } catch (error) {
      console.error("review render failed", error);
      const root = document.getElementById("match-root");
      const back = h("div", { class: "review-toolbar no-print" }, reviewBackButton());
      root.replaceChildren(back, card(t("reviewError"), "circle-alert", emptyState("circle-alert", t("reviewRenderFailed"), String(error && error.message ? error.message : error))));
      hydrate(root);
    }
  }

  // The match next to the open one in the list the player came from (newest
  // first): step -1 = newer, +1 = older. Null when the review was opened from
  // elsewhere and the match is not in the loaded list, or at its end.
  function neighbourMatch(step) {
    const index = state.matches.findIndex((row) => String(row.match_id) === state.matchId);
    return index < 0 ? null : state.matches[index + step] || null;
  }

  // «‹ Newer · Older ›» next to «Back»: several reviews in a row without the list.
  function neighbourButtons() {
    if (!state.matches.some((row) => String(row.match_id) === state.matchId)) {
      return null;
    }
    const button = (step, iconName, label, hint) => {
      const row = neighbourMatch(step);
      const parts = [h("span", { text: label })];
      parts[step < 0 ? "unshift" : "push"](icon(iconName));
      return h(
        "button",
        {
          class: "btn btn-ghost btn-sm",
          type: "button",
          disabled: !row,
          title: row ? hint(row.hero || "") : "",
          onclick: () => row && openMatch(row.match_id)
        },
        parts
      );
    };
    return h(
      "span",
      { class: "neighbour-nav" },
      // Ordered by a column, the neighbours are the rows above and below.
      sortedByDate()
        ? button(-1, "chevron-left", t("newerMatch"), (hero) => t("newerMatchHint", hero))
        : button(-1, "chevron-left", t("prevRowMatch"), (hero) => t("prevRowMatchHint", hero)),
      sortedByDate()
        ? button(1, "chevron-right", t("olderMatch"), (hero) => t("olderMatchHint", hero))
        : button(1, "chevron-right", t("nextRowMatch"), (hero) => t("nextRowMatchHint", hero))
    );
  }

  const matchDetail = window.WardlyMatchDetail.create({
    reviewBackButton, h, neighbourButtons, shareButton, pdfButton, card, t,
    skeletonRows, hydrate, tOptional, emptyState, openMatch, icon, reviewHeader,
    toolbarMatch, zone, coachCard, focusCard, findingsCard, askCard, chartCard,
    laneCard, deathsCard, adviceLogCard, sectionsCard, rankCard, draftCard, mapCard,
    buildCard, skillsCard, momentsCard, twoColumns, scoreboardCard, sectionNav,
    stickToolbar, watchSections, drawMatchCharts,
    getMatchId: () => state.matchId
  });

  function drawMatch() {
    matchDetail.draw({root: document.getElementById("match-root"), detail: state.match});
  }

  // The review's toolbar stays at the top of the window; once the header has
  // scrolled away it names the match (hero, result, score), so a long review
  // never loses which game it is about, and ‹ Newer · Older › stay at hand.
  function toolbarMatch(detail, analysis, summary) {
    const headline = (analysis && analysis.headline) || {};
    const win = headline.win ?? summary.win;
    const score = headline.score ?? summary.score;
    const hero = summary.hero_id || headline.hero_id || headline.hero || summary.hero;
    return h(
      "span",
      { class: "toolbar-match", "aria-hidden": "true" },
      window.DotaIcons ? window.DotaIcons.heroPicture(document, hero, "sm") : null,
      h("span", { class: "toolbar-hero", text: headline.hero || summary.hero || "—" }),
      resultBadge(win),
      Number.isFinite(score) ? scoreRing(score, "md") : null
    );
  }

  function stickToolbar(bar, header) {
    state.toolbarObserver?.disconnect();
    state.toolbarObserver = null;
    if (!header || typeof IntersectionObserver !== "function") {
      return;
    }
    const observer = new IntersectionObserver(([entry]) => bar.classList.toggle("is-stuck", !entry.isIntersecting), { rootMargin: "-64px 0px 0px 0px" });
    observer.observe(header);
    state.toolbarObserver = observer;
  }

  // A page title (Matches, Progress) with its one-line summary and actions.
  function pageHead(title, sub, actions) {
    return h(
      "header",
      { class: "page-head" },
      h("div", { class: "page-head-text" }, h("h1", { class: "page-title", text: title }), sub ? h("p", { class: "page-sub", text: sub }) : null),
      actions ? h("div", { class: "page-actions no-print" }, actions) : null
    );
  }

  // A zone counts as being read once its top passes this line (px from the top
  // of the window: under the sticky bar of the review and of Progress).
  const SECTION_LINE = 120;

  // Cards grouped under a small heading (styles.css .zone); null without cards.
  // `nav` ({id, label}) lists the zone in the page's section links (sectionNav).
  function zone(title, hint, cards, nav) {
    const items = cards.filter(Boolean);
    if (!items.length) {
      return null;
    }
    return h(
      "section",
      { class: "zone", id: nav ? `zone-${nav.id}` : null, dataset: nav ? { nav: nav.label } : null },
      h("header", { class: "zone-head" }, h("h2", { class: "zone-title", text: title }), hint ? h("p", { class: "zone-hint", text: hint }) : null),
      items
    );
  }

  // «Fix · The match · Scores · Map · Teams»: one link per zone of a long page
  // (the zones made with a `nav`), in the page's order; three zones or more.
  function sectionNav(root) {
    const zones = Array.from(root.querySelectorAll("section.zone[data-nav]"));
    if (zones.length < 3) {
      return null;
    }
    const nav = h("nav", { class: "section-nav no-print", "aria-label": t("sectionNav") });
    nav.append(
      ...zones.map((zoneEl) =>
        h("button", {
          type: "button",
          class: "section-link",
          dataset: { target: zoneEl.id },
          text: zoneEl.dataset.nav,
          onclick: () => {
            // Two columns start zones side by side: the one clicked wins the tie.
            nav.dataset.picked = zoneEl.id;
            goToZone(zoneEl);
          }
        })
      )
    );
    return nav;
  }

  function goToZone(zoneEl) {
    const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    zoneEl.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
    // Keyboard users go on from the zone, not from the top of the page.
    const heading = zoneEl.querySelector(".zone-title");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
  }

  // The zone being read is marked in the links: the last one whose top has
  // passed under the sticky bar (at the very bottom, the last zone).
  function watchSections(nav) {
    if (state.sectionSpy) {
      window.removeEventListener("scroll", state.sectionSpy, true);
      state.sectionSpy = null;
    }
    if (!nav) {
      return;
    }
    const links = Array.from(nav.querySelectorAll(".section-link"));
    let frame = 0;
    let shown = null;
    const update = () => {
      frame = 0;
      if (!nav.isConnected) {
        window.removeEventListener("scroll", spy, true);
        return;
      }
      const scroller = document.scrollingElement || document.documentElement;
      const atBottom = scroller.scrollTop > 0 && scroller.scrollTop + window.innerHeight >= scroller.scrollHeight - 4;
      let current = atBottom ? links[links.length - 1] : null;
      let best = -Infinity;
      if (!current) {
        for (const link of links) {
          const top = document.getElementById(link.dataset.target)?.getBoundingClientRect().top;
          if (top === undefined || top > SECTION_LINE) {
            continue;
          }
          const tie = Math.abs(top - best) <= 2;
          if ((!tie && top > best) || (tie && link.dataset.target === nav.dataset.picked)) {
            best = top;
            current = link;
          }
        }
      }
      links.forEach((link) => {
        link.classList.toggle("is-current", link === current);
        if (link === current) {
          link.setAttribute("aria-current", "true");
        } else {
          link.removeAttribute("aria-current");
        }
      });
      // In a narrow window the links scroll sideways: keep the current one in
      // view, and back at the top of the page start from the first link.
      if (!current && shown) {
        shown = null;
        nav.scrollLeft = 0;
      }
      if (current && current !== shown) {
        shown = current;
        const box = current.getBoundingClientRect();
        const area = nav.getBoundingClientRect();
        if (box.left < area.left || box.right > area.right) {
          nav.scrollLeft += box.left - area.left - (area.width - box.width) / 2;
        }
      }
      const hidden = nav.scrollWidth - nav.clientWidth;
      nav.classList.toggle("fade-start", hidden > 1 && nav.scrollLeft > 1);
      nav.classList.toggle("fade-end", hidden > 1 && nav.scrollLeft < hidden - 1);
    };
    const spy = () => {
      if (!frame) {
        frame = requestAnimationFrame(update);
      }
    };
    window.addEventListener("scroll", spy, { capture: true, passive: true });
    state.sectionSpy = spy;
    update();
  }

  // Main and side cards as two columns (styles.css .layout-2).
  function twoColumns(main, side) {
    return h("div", { class: "layout-2" }, h("div", { class: "col col-main" }, main), h("div", { class: "col col-side" }, side));
  }

  // Each chart host by its kind (also on window resize).
  function drawMatchCharts(root, analysis) {
    if (!root || !analysis) {
      return;
    }
    root.querySelectorAll("[data-chart='match']").forEach((host) => drawChart(host, analysis));
    root.querySelectorAll("[data-chart='timing']").forEach((host) => drawTimingChart(host, analysis));
    root.querySelectorAll("[data-chart='map']").forEach((host) => drawMap(host, analysis.map));
    root.querySelectorAll("[data-chart='map-empty']").forEach((host) => drawMap(host, {}));
  }

  // «OpenDota · Dotabuff · STRATZ»: the same match on the sites players use.
  function matchSiteLinks(matchId) {
    if (!/^\d{1,20}$/.test(String(matchId ?? "")) || typeof api.openMatchSite !== "function") {
      return null;
    }
    const sites = [["opendota", "OpenDota"], ["dotabuff", "Dotabuff"], ["stratz", "STRATZ"]];
    return h(
      "span",
      { class: "site-links no-print" },
      sites.map(([site, name]) =>
        h("button", { class: "site-link", type: "button", title: t("openOnSite", name), onclick: () => api.openMatchSite(site, String(matchId)) }, h("span", { text: name }), icon("external-link"))
      )
    );
  }

  // «На чому ґрунтується розбір?» (backend review_basis.py): the rules version, the
  // data it read and why it was built; a review from before 0.53.57 says so.
  function reviewBasis(analysis, sources) {
    if (!analysis) {
      return null;
    }
    const basis = analysis.basis || null;
    const data = [];
    if (basis ? basis.sources.includes("opendota") : sources.includes("opendota")) {
      data.push(t(analysis.parsed ? "basisDataParsed" : "basisDataOpenDota"));
    }
    if (basis ? basis.recorded : sources.includes("gsi")) {
      data.push(t("basisDataRecorded"));
    }
    const lines = [
      t("basisRules", basis ? basis.rules : analysis.version),
      t("basisData", data.length ? data.join(", ") : "—"),
      basis
        ? t(
            `basisReason.${basis.reason}`,
            new Date(basis.built_at).toLocaleString(state.locale === "uk" ? "uk-UA" : "en-GB", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }),
            basis.previous_rules
          )
        : t("basisOld")
    ];
    return h(
      "details",
      { class: "review-basis no-print" },
      h("summary", { text: t("basisTitle") }),
      h("ul", { class: "muted small" }, lines.map((line) => h("li", { text: line }))),
      h("p", { class: "muted small", text: t("basisHint") })
    );
  }

  // Progress: whether the averages compare like with like (backend career_basis).
  function careerBasisNote(basis) {
    if (!basis || !basis.matches) {
      return null;
    }
    const notes = [t("basisCareerRules", basis.matches, basis.rules)];
    if (basis.mixed_patches) {
      notes.push(t("basisCareerPatches", Object.keys(basis.patches).length));
    }
    if (basis.mixed_data) {
      notes.push(t("basisCareerParsed", basis.parsed, basis.matches));
    }
    return h("p", { class: "muted small career-basis", text: notes.join(" ") });
  }

  function reviewHeader(detail, analysis, summary) {
    const headline = (analysis && analysis.headline) || {};
    const win = headline.win ?? summary.win;
    const score = headline.score ?? summary.score;
    const sources = detail.sources || [];
    let sourceText = t("sourcesGsi");
    if (analysis && analysis.parsed) {
      sourceText = t("sourcesParsed");
    } else if (sources.includes("opendota")) {
      sourceText = t("sourcesBasic");
    }
    const statusText = detail.parse_status && detail.parse_status !== "parsed" ? tOptional(`parseStatus.${detail.parse_status}`) : "";
    const canRequest = !(analysis && analysis.parsed) && state.player?.opendota;
    const requestButton = canRequest
      ? h(
          "button",
          {
            class: "btn btn-sm",
            type: "button",
            onclick: async (event) => {
              event.currentTarget.disabled = true;
              await call("refreshMatch", { matchId: state.matchId });
              requestNote.textContent = t("parseRequested");
            }
          },
          icon("refresh-cw"),
          h("span", { text: t("requestParse") })
        )
      : null;
    const requestNote = h("span", { class: "muted" });
    const stats = [
      [t("stats.kda"), combatScore(headline)],
      [t("stats.gpm"), `${number(headline.gpm)} / ${number(headline.xpm)}`],
      [t("stats.lh"), `${number(headline.last_hits)} / ${number(headline.denies)}`],
      [t("stats.duration"), clock(headline.duration ?? summary.duration)]
    ];
    if (headline.net_worth) {
      stats.push([t("stats.nw"), number(headline.net_worth)]);
    }
    if (headline.hero_damage) {
      stats.push([t("stats.dmg"), number(headline.hero_damage)]);
    }
    const heroValue = summary.hero_id || headline.hero_id || headline.hero || summary.hero;
    const art = window.DotaIcons?.heroArt ? window.DotaIcons.heroArt(document, heroValue) : null;
    if (art) {
      art.classList.add("no-print");
    }
    const scoreBlock =
      score !== null && score !== undefined
        ? h("div", { class: "score-block", title: `${score} ${t("scoreOf")}` }, scoreRing(score, "lg"), gradeLetter(score))
        : null;
    return h(
      "section",
      { class: "review-head card art-card", dataset: { result: win === true ? "win" : win === false ? "loss" : "" } },
      art,
      h(
        "div",
        { class: "card-body review-head-body" },
        // Without the hero art (offline, unknown hero, print) the small portrait stays.
        window.DotaIcons ? h("div", { class: art ? "review-portrait print-only-flex" : "review-portrait" }, window.DotaIcons.heroPicture(document, heroValue, "lg")) : null,
        scoreBlock,
        h(
          "div",
          { class: "review-title" },
          h("h2", { class: "review-hero", text: headline.hero || summary.hero || "—" }),
          h("p", { class: "review-meta" }, resultBadge(win), h("span", { class: "muted", text: `· ${relativeTime(summary.start_time)} · #${detail.match_id}` }), matchSiteLinks(detail.match_id)),
          h("p", { class: "review-source" }, icon(analysis && analysis.parsed ? "circle-check" : "info"), h("span", { text: sourceText })),
          reviewBasis(analysis, sources),
          window.WardlyFindingEvidence.renderCoverage(analysis?.recording_coverage, state.locale),
          statusText ? h("p", { class: "muted small", text: statusText }) : null,
          baselineLine(detail.baseline),
          detail.focus
            ? h(
                "p",
                { class: "review-goal", dataset: { met: String(detail.focus.met) } },
                h("span", { class: "dot", "data-tone": detail.focus.met ? "good" : "bad" }),
                h("span", { text: t("goalMatch", detail.focus.title, detail.focus.met) })
              )
            : null,
          requestButton ? h("div", { class: "row" }, requestButton, requestNote) : null,
          noteLine(detail, summary)
        )
      ),
      h(
        "dl",
        { class: "review-stats" },
        stats.map(([label, value]) => h("div", {}, h("dt", { text: label }), h("dd", { class: "num", text: value }))),
        // The final inventory (0.50), as the match table shows it.
        Array.isArray(summary.items) && summary.items.length && window.DotaIcons
          ? h(
              "div",
              { class: "review-items" },
              h("dt", { text: t("stats.items") }),
              h(
                "dd",
                { class: "items-cell" },
                summary.items.slice(0, 6).map((key) => window.DotaIcons.itemPicture(document, key, "sm"))
              )
            )
          : null
      )
    );
  }

  // «Нотатка» (0.52): the player's own line on the match (lag, a new build,
  // played with a friend…), also marked in the match table. Kept on this
  // computer only: never sent to the AI coach or in a shared review.
  function noteLine(detail, summary) {
    const wrap = h("div", { class: "review-note" });
    const show = () => {
      const note = summary.note || "";
      // replaceChildren would print a null as the text «null».
      wrap.replaceChildren(
        ...(note ? [h("p", { class: "review-note-text" }, icon("sticky-note"), h("span", { text: note }))] : []),
        h(
          "button",
          { class: "btn btn-ghost btn-sm no-print review-note-edit", type: "button", title: note ? t("noteEdit") : t("noteAddHint"), onclick: edit },
          icon(note ? "pencil" : "sticky-note"),
          h("span", { text: note ? t("noteEdit") : t("noteAdd") })
        )
      );
      hydrate(wrap);
    };
    const edit = () => {
      const input = h("input", { class: "input review-note-input", type: "text", maxlength: 200, placeholder: t("notePlaceholder"), "aria-label": t("noteLabel") });
      input.value = summary.note || "";
      const status = h("span", { class: "muted small", role: "status" });
      const save = async () => {
        input.disabled = true;
        const result = await call("setNote", { matchId: detail.match_id, note: input.value });
        if (result.ok) {
          summary.note = result.data.note || null;
          const row = state.matches.find((item) => String(item.match_id) === String(detail.match_id));
          if (row) {
            row.note = summary.note;
          }
          show();
        } else {
          input.disabled = false;
          status.textContent = t("noteFailed");
        }
      };
      input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          show();
        }
      });
      wrap.replaceChildren(
        h(
          "form",
          {
            class: "review-note-form no-print",
            onsubmit: (event) => {
              event.preventDefault();
              save();
            }
          },
          input,
          h("button", { class: "btn btn-sm", type: "submit" }, h("span", { text: t("noteSave") })),
          h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: show }, h("span", { text: t("noteCancel") })),
          status
        )
      );
      input.focus();
    };
    show();
    return wrap;
  }

  // "Against your 8 other matches on Juggernaut: score +17 · GPM +94 · deaths −2".
  function baselineLine(baseline) {
    if (!baseline || !baseline.metrics || !baseline.metrics.length) {
      return null;
    }
    const format = (key, value) => {
      const rounded = key === "deaths" ? Math.round(value * 10) / 10 : Math.round(value);
      const text = Math.abs(rounded).toLocaleString(state.locale);
      return `${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${text}`;
    };
    return h(
      "p",
      { class: "review-baseline" },
      h("span", { class: "muted", text: t("baselineIntro", baseline.games, baseline.hero || "—") }),
      baseline.metrics.map((metric) =>
        h(
          "span",
          {
            class: "baseline-chip num",
            dataset: { tone: metric.tone },
            title: t("baselineTitle", metric.key === "deaths" ? metric.average.toLocaleString(state.locale) : Math.round(metric.average).toLocaleString(state.locale))
          },
          metric.tone === "same" ? null : h("span", { class: "dot", "data-tone": metric.tone }),
          h("span", { text: `${t(`baselineLabels.${metric.key}`)} ${metric.tone === "same" ? t("baselineSame") : format(metric.key, metric.delta)}` })
        )
      )
    );
  }

  // finding_history: the same problem in the player's earlier matches.
  function repeatNote(repeat) {
    if (!repeat) {
      return null;
    }
    const text = repeat.in_a_row >= 3 ? t("repeatInARow", repeat.in_a_row) : t("repeatInLast", repeat.in_last, repeat.of);
    return h("p", { class: "finding-repeat" }, icon("repeat"), h("span", { text }));
  }

  function findingItem(finding, index, repeats) {
    return h(
      "li",
      { class: `finding finding-${finding.kind}` },
      index !== undefined ? h("span", { class: "finding-index num", text: String(index + 1) }) : h("span", { class: "dot", "data-tone": finding.kind === "strength" ? "good" : finding.severity >= 3 ? "bad" : "warn" }),
      h(
        "div",
        { class: "finding-body" },
        h("p", { class: "finding-title" }, h("span", { text: finding.title }), finding.section_label ? h("span", { class: "tag", text: finding.section_label }) : null),
        h("p", { class: "finding-text", text: finding.text }),
        window.WardlyFindingEvidence.render(finding, state.locale),
        repeatNote(repeats && repeats[finding.id]),
        finding.drill ? h("p", { class: "finding-drill" }, icon("lightbulb"), h("span", {}, h("strong", { text: `${t("drill")}: ` }), finding.drill)) : null
      )
    );
  }

  function focusCard(analysis, detail) {
    const focus = (analysis.improvements || []).filter((f) => (analysis.focus || []).includes(f.id));
    if (!focus.length) {
      return card(t("focusTitle"), "target", emptyState("circle-check", t("nothingToImprove"), ""));
    }
    const list = h("ol", { class: "findings" });
    const render = () =>
      list.replaceChildren(
        ...focus.map((finding, index) => {
          const item = findingItem(finding, index, detail && detail.repeats);
          const body = item.querySelector(".finding-body");
          if (detail && detail.focus_id === finding.id) {
            item.querySelector(".finding-title").append(h("span", { class: "tag tag-accent", text: t("goalCurrent") }));
          } else if (detail && (detail.focusable || []).includes(finding.id)) {
            // Work on it from the next game (the Progress page tracks it).
            body.append(
              h(
                "button",
                {
                  class: "btn btn-ghost btn-sm goal-set no-print",
                  type: "button",
                  onclick: async (event) => {
                    event.currentTarget.disabled = true;
                    const button = event.currentTarget;
                    const result = await call("focusSet", { findingId: finding.id });
                    if (!result.ok) {
                      button.disabled = false;
                      button.replaceChildren(icon("circle-alert"), h("span", { text: t("goalSetFailed") }));
                      hydrate(button);
                      return;
                    }
                    detail.focus_id = finding.id;
                    state.career = null;
                    render();
                    hydrate(list);
                  }
                },
                icon("target"),
                h("span", { text: t("goalSet") })
              )
            );
          }
          return item;
        })
      );
    render();
    return card(t("focusTitle"), "target", list);
  }

  function findingsCard(title, iconName, findings, emptyText, improve, repeats, fold) {
    if (!findings || !findings.length) {
      return card(title, iconName, h("p", { class: "muted", text: emptyText }));
    }
    const list = h("ul", { class: `findings ${improve ? "" : "findings-compact"}` }, findings.map((f) => findingItem(f, undefined, repeats)));
    return card(title, iconName, fold ? foldList(list, fold) : list);
  }

  function sectionsCard(analysis) {
    const order = ["laning", "farm", "survival", "fights", "items", "vision"];
    const rows = order
      .filter((name) => analysis.sections && analysis.sections[name])
      .map((name) => {
        const section = analysis.sections[name];
        const factsFn = (TEXT[state.locale] || TEXT.en).sectionFacts[name];
        const facts = factsFn ? factsFn(section).filter(Boolean).join(" · ") : "";
        return h(
          "div",
          { class: "section-row" },
          h("span", { class: "section-name", text: section.label || name }),
          window.LauncherCharts.meter(section.score),
          h("span", { class: "section-score num", text: String(section.score) }),
          h("span", { class: "section-facts", text: facts })
        );
      });
    return card(t("sectionsTitle"), "gauge", h("div", {}, h("div", { class: "sections" }, rows), explain("explainScore")));
  }

  // Schematic map: path and deaths from the app's own recording, laning
  // position and wards from the parsed replay (either may be missing).
  function mapCard(analysis) {
    const data = analysis.map;
    const hasData = Boolean(
      data && ((data.deaths || []).length || (data.wards || []).length || (data.path || []).length > 1 || (data.lane || []).length)
    );
    if (!hasData) {
      // No positions (an unparsed replay, no app during the game): the map
      // itself and how to get the positions.
      const body = h(
        "div",
        {},
        h("p", { class: "muted small chart-note", text: t("mapEmpty") }),
        h("div", { class: "map-layout" }, h("div", { class: "chart-host", dataset: { chart: "map-empty" } }))
      );
      return card(t("mapTitle"), "map", body);
    }
    const hasPath = (data.path || []).length > 1;
    const hasReplay = (data.wards || []).length > 0 || (data.lane || []).length > 0;
    const hintKey = hasPath && hasReplay ? "both" : hasPath ? "path" : "replay";
    const facts = [];
    const deaths = data.deaths || [];
    if (deaths.length) {
      const bySide = data.deaths_by_side || {};
      facts.push(h("p", { class: "fact-line" }, h("strong", { text: t("mapDeaths") }), h("span", { class: "num", text: String(deaths.length) })));
      for (const side of ["own", "river", "enemy"]) {
        if (bySide[side]) {
          facts.push(h("p", { class: "fact-line muted small" }, h("span", { text: t(`mapSide.${side}`) }), h("span", { class: "num", text: String(bySide[side]) })));
        }
      }
      const spot = (data.spots || [])[0];
      if (spot && spot.label) {
        facts.push(h("p", { class: "fact-line map-spot-line" }, h("span", { text: t("mapSpotLine", spot.label, spot.count) })));
      }
    }
    const wards = data.wards || [];
    if (wards.length) {
      const obs = wards.filter((w) => w.kind === "obs").length;
      facts.push(h("p", { class: "fact-line" }, h("strong", { text: t("mapWards") }), h("span", { class: "num", text: String(wards.length) })));
      facts.push(h("p", { class: "muted small", text: t("mapWardsLine", obs, wards.length - obs) }));
    }
    const body = h(
      "div",
      {},
      h("p", { class: "muted small chart-note", text: t(`mapHint.${hintKey}`) }),
      h("div", { class: "map-layout" }, h("div", { class: "chart-host", dataset: { chart: "map" } }), facts.length ? h("div", { class: "map-facts" }, facts) : null)
    );
    return card(t("mapTitle"), "map", body);
  }

  // The game's minimap (patch 7.40 art, as OpenDota publishes it): positions in
  // replay units 8192..24576 on both axes cover the whole picture.
  const MAP_BACKGROUND = { href: "dota-asset://map/detailed_740", bounds: [8192, 24576] };

  function drawMap(host, data) {
    window.LauncherCharts.map(host, {
      background: MAP_BACKGROUND,
      bounds: data.bounds,
      path: data.path,
      lane: data.lane,
      wards: data.wards,
      // Places where the deaths repeat (map_analysis.death_spots), with their times.
      spots: (data.spots || []).map((spot) => ({
        ...spot,
        title: t("mapSpotTitle", spot.count, spot.label || ""),
        detail: (spot.times || []).map(clock).join(", ")
      })),
      deaths: (data.deaths || []).map((death) => ({ ...death, killer: death.killer ? t("killedBy", death.killer) : "" })),
      labels: t("mapLabels"),
      clock,
      ariaLabel: t("mapTitle")
    });
  }

  function chartCard(analysis) {
    const series = analysis.series || {};
    const metrics = [
      ["lh", t("chartLh"), series.last_hits],
      ["gold", t("chartGold"), series.gold],
      ["xp", t("chartXp"), series.xp]
    ].filter(([, , values]) => Array.isArray(values) && values.length > 2);
    if (!metrics.length) {
      return null;
    }
    if (!metrics.some(([key]) => key === state.chartMetric)) {
      state.chartMetric = metrics[0][0];
    }
    const host = h("div", { class: "chart-host", dataset: { chart: "match" } });
    const toggle = h(
      "div",
      { class: "segmented segmented-sm", role: "radiogroup", "aria-label": t("chartTitle") },
      metrics.map(([key, label]) =>
        h("button", {
          type: "button",
          role: "radio",
          "aria-checked": String(key === state.chartMetric),
          text: label,
          onclick: (event) => {
            state.chartMetric = key;
            for (const button of event.currentTarget.parentElement.children) {
              button.setAttribute("aria-checked", String(button === event.currentTarget));
            }
            drawChart(host, analysis);
          }
        })
      )
    );
    const best = state.match && state.match.best_on_hero;
    let note = null;
    if (best && best.self_best) {
      note = h("p", { class: "muted small chart-note", text: t("bestOnHeroSelf", best.of) });
    } else if (best && best.score) {
      note = h("p", { class: "muted small chart-note", text: t("bestOnHeroNote", best.score, relativeTime(best.start_time)) });
    }
    return card(t("chartTitle"), "chart-line", note ? h("div", {}, host, note) : host, toggle);
  }

  function drawChart(host, analysis) {
    const series = analysis.series || {};
    const values = { lh: series.last_hits, gold: series.gold, xp: series.xp }[state.chartMetric] || [];
    const label = { lh: t("chartLh"), gold: t("chartGold"), xp: t("chartXp") }[state.chartMetric];
    const markers = (series.deaths || []).map((seconds) => ({ x: seconds / 60, label: `${t("deathsMarker")} ${clock(seconds)}` }));
    // The player's best match on this hero, dashed (PlayerService._best_on_hero).
    const best = state.match && state.match.best_on_hero;
    const bestSeries = best && best.series ? { lh: best.series.last_hits, gold: best.series.gold, xp: best.series.xp }[state.chartMetric] : null;
    const lines = [{ label: `${t("you")} · ${label}`, values, color: VIZ_1, area: true }];
    if (Array.isArray(bestSeries) && bestSeries.length > 2) {
      lines.push({ label: t("bestOnHeroLine", best.score), values: bestSeries, color: VIZ_2, dashed: true });
    }
    window.LauncherCharts.line(host, {
      series: lines,
      reference: (() => {
        const target = { lh: series.last_hits_target, gold: series.gold_target, xp: series.xp_target }[state.chartMetric];
        return Array.isArray(target) && target.length ? { label: t("target"), values: target } : null;
      })(),
      markers,
      markerLabel: t("deathsMarker"),
      // Each finished item at the minute it came (0.50, series.items).
      icons: (series.items || []).map((item) => {
        const name = window.DotaIcons?.itemName(item.key) || item.key;
        return { x: item.t / 60, src: `dota-asset://item/${item.key}`, label: `${name} · ${clock(item.t)}` };
      }),
      xLabel: (i) => t("minuteLabel", i),
      ariaLabel: label,
      height: 210
    });
  }

  // --- build + rank (match) ---------------------------------------------------------

  function buildCard(analysis) {
    const build = analysis.build;
    if (!build || !(build.items || []).length) {
      return null;
    }
    const rows = build.items.map((item, index) => {
      const timing = item.timing;
      return h(
        "div",
        { class: "build-item" },
        h(
          "div",
          { class: "build-item-head" },
          h("span", { class: "build-item-name with-pic" }, itemPic(item.key || item.name, "md"), h("span", { text: item.name })),
          h("span", { class: "muted num", text: t("buildBy", clock(item.t)) })
        ),
        timing
          ? h(
              "div",
              {},
              h("p", { class: "small build-item-line", text: timingLine(timing) }),
              h("div", { class: "chart-host chart-mini", dataset: { chart: "timing", index: String(index) } })
            )
          : null
      );
    });
    const popular = build.popular || {};
    const phases = ["mid", "late", "early"].filter((phase) => (popular[phase] || []).length);
    const popularBlock = phases.length
      ? h(
          "div",
          { class: "build-popular" },
          h("p", { class: "section-name", text: t("buildPopular") }),
          phases.map((phase) =>
            h(
              "div",
              { class: "build-phase" },
              h("span", { class: "muted small build-phase-label", text: t(`buildPhase.${phase}`) }),
              h(
                "div",
                { class: "chips" },
                popular[phase].map((row) =>
                  h(
                    "span",
                    { class: `chip ${row.bought ? "chip-on" : ""}`, title: row.bought ? t("buildBought") : "" },
                    itemPic(row.key || row.name, "sm"),
                    h("span", { text: row.name }),
                    row.bought ? icon("circle-check") : null
                  )
                )
              )
            )
          )
        )
      : null;
    return card(
      t("buildTitle"),
      "coins",
      h(
        "div",
        { class: "build" },
        build.has_timings ? h("p", { class: "muted small", text: t("buildTimingNote") }) : h("p", { class: "muted small", text: t("buildNoTimings") }),
        rows,
        popularBlock
      )
    );
  }

  // The first skill maxed against the pro order on the hero (backend skill_build.py).
  // «Лінія»: the lane minute by minute against its enemy core (lane_duel.py,
  // parsed replays only).
  function laneCard(analysis) {
    const lane = analysis.lane;
    if (!lane || !(lane.points || []).length) {
      return null;
    }
    const signed = (value) => (value === null || value === undefined ? "—" : value > 0 ? `+${value}` : `${value}`);
    const tone = (value) => (value === null || value === undefined || value === 0 ? "" : value > 0 ? "good" : "bad");
    const pair = (mine, theirs) => (mine === null || mine === undefined ? "—" : `${mine} : ${theirs ?? "—"}`);
    const rows = lane.points.map((point) =>
      h(
        "tr",
        {},
        h("td", { class: "num", text: t("laneMinute", point.minute) }),
        h("td", { class: "num-col num", text: pair(point.lh, point.enemy_lh) }),
        h("td", { class: "num-col num", text: pair(point.dn, point.enemy_dn) }),
        h("td", { class: "num-col num", "data-state": tone(point.gold_diff), text: signed(point.gold_diff) }),
        h("td", { class: "num-col num", "data-state": tone(point.xp_diff), text: signed(point.xp_diff) })
      )
    );
    const others = (lane.enemies || []).filter((hero) => hero !== lane.enemy);
    // How the pair usually goes in public games (backend lane_matchup.py); a row
    // without a clear call says nothing.
    const pub = lane.matchup;
    const publicLaneLine = pub && (pub.kind === "hard" || pub.kind === "easy")
      ? h("p", {
          class: "muted small lane-public",
          text: pub.kind === "hard"
            ? t("laneMatchupHard", lane.hero, pub.enemy || lane.enemy, pub.lost, pub.lanes)
            : t("laneMatchupEasy", lane.hero, pub.enemy || lane.enemy, pub.won, pub.lanes)
        })
      : null;
    return card(
      t("laneTitle"),
      "swords",
      h(
        "div",
        { class: "lane-duel" },
        h(
          "div",
          { class: "lane-head" },
          heroLabel(lane.hero_id, lane.hero),
          h("span", { class: "muted", text: t("laneVs") }),
          heroLabel(lane.enemy_id, lane.enemy),
          h("span", { class: `lane-result lane-${lane.result}`, text: t(`laneResult.${lane.result}`) })
        ),
        publicLaneLine,
        h(
          "div",
          { class: "table-wrap table-wrap-tight" },
          h(
            "table",
            { class: "table lane-table" },
            h(
              "thead",
              {},
              h(
                "tr",
                {},
                h("th", { text: t("laneColMinute") }),
                h("th", { class: "num-col", text: t("laneColLh") }),
                h("th", { class: "num-col", text: t("laneColDn") }),
                h("th", { class: "num-col", text: t("laneColGold") }),
                h("th", { class: "num-col", text: t("laneColXp") })
              )
            ),
            h("tbody", {}, rows)
          )
        ),
        h("p", { class: "muted small", text: [lane.turn ? t("laneTurn", lane.turn) : null, others.length ? t("laneOthers", others.join(", "), signed(lane.total_diff)) : null, t("laneNote")].filter(Boolean).join(" ") })
      )
    );
  }

  function skillsCard(analysis) {
    const skills = analysis.skills;
    if (!skills || !(skills.order || []).length) {
      return null;
    }
    return card(
      t("skillsTitle"),
      "list-checks",
      h(
        "div",
        { class: "skills" },
        h("p", { text: skills.same ? t("skillsSame", skills.yours) : t("skillsDiff", skills.yours, skills.pro) }),
        h("p", { class: "section-name", text: t("skillsPro") }),
        h(
          "div",
          { class: "chips" },
          skills.order.map((name, index) =>
            h(
              "span",
              { class: `chip chip-skill ${name === skills.yours ? "chip-on" : ""}` },
              h("span", { class: "num", text: `${index + 1}` }),
              abilityIcon((skills.keys || [])[index], name),
              h("span", { text: name })
            )
          )
        ),
        // The player's first skill when the pros rarely max it: shown apart, marked.
        skills.in_order === false || !skills.order.includes(skills.yours)
          ? h(
              "div",
              { class: "chips" },
              h("span", { class: "muted small", text: t("skillsYours") }),
              h("span", { class: "chip chip-skill chip-on" }, abilityIcon(skills.yours_key, skills.yours), h("span", { text: skills.yours }))
            )
          : null,
        h("p", { class: "muted small", text: t("skillsNote", skills.agree, skills.games) })
      )
    );
  }

  // An ability's icon in a chip; nothing when the review has no game name for
  // it (stored before 0.49) or the icons are not loaded.
  function abilityIcon(key, name) {
    return key && window.DotaIcons?.abilityPicture ? window.DotaIcons.abilityPicture(document, key, "xs", name) : null;
  }

  function timingLine(timing) {
    if (timing.bucket === timing.typical_bucket) {
      return t("buildItemTypical", timing.winrate, clock(timing.bucket));
    }
    return t("buildItemLine", timing.winrate, clock(timing.bucket), clock(timing.typical_bucket), timing.typical_winrate);
  }

  function drawTimingChart(host, analysis) {
    const item = (analysis.build?.items || [])[Number(host.dataset.index)];
    const timing = item && item.timing;
    if (!timing) {
      return;
    }
    window.LauncherCharts.columns(host, {
      items: timing.buckets.map((bucket) => ({
        label: clock(bucket.time),
        value: bucket.winrate,
        title: t("buildTimingTip", clock(bucket.time)),
        detail: `${number(bucket.games)} ${state.locale === "uk" ? "ігор" : "games"}`,
        muted: bucket.time !== timing.bucket
      })),
      // 0-based columns, but no taller than needed so a 10-point gap is visible.
      yMax: Math.min(100, Math.ceil((Math.max(...timing.buckets.map((b) => b.winrate)) + 10) / 20) * 20),
      valueLabels: true,
      valueSuffix: "%",
      color: VIZ_1,
      valueLabel: t("winrateLabel"),
      ariaLabel: `${item.name}: ${t("winrateLabel")}`,
      height: 130,
      xLabels: true
    });
  }

  const RANK_METRICS = ["gpm", "lh_10", "deaths", "kda", "damage_per_min", "net_worth"];
  const LOWER_BETTER = new Set(["deaths"]);

  function formatMetric(key, value) {
    if (value === null || value === undefined) {
      return "—";
    }
    if (key === "kda" || key === "lh_per_min") {
      return decimal(value);
    }
    if (key === "deaths") {
      return Number.isInteger(value) ? number(value) : decimal(value);
    }
    return number(value);
  }

  function diffCell(key, you, other, betterOverride) {
    if (you === null || you === undefined || other === null || other === undefined) {
      return h("td", { class: "num-col num muted", text: "—" });
    }
    const diff = you - other;
    const threshold = Math.max(0.01, Math.abs(other) * 0.03);
    const better = betterOverride !== undefined ? betterOverride : Math.abs(diff) <= threshold ? null : LOWER_BETTER.has(key) ? diff < 0 : diff > 0;
    const tone = better === true ? "good" : better === false ? "bad" : "idle";
    const sign = diff > 0 ? "+" : diff < 0 ? "−" : "";
    return h("td", { class: `num-col num delta-${tone}`, text: `${sign}${formatMetric(key, Math.abs(diff))}` });
  }

  function percent1(value) {
    return `${decimal(value)}%`;
  }

  function signedPercent(value) {
    return `${value > 0 ? "+" : value < 0 ? "−" : ""}${percent1(Math.abs(value))}`;
  }

  function winrateTone(winrate) {
    return winrate >= 52 ? "good" : winrate <= 48 ? "bad" : "idle";
  }

  function selfValue(key, value, item) {
    if (key === "first_item_t") {
      return item ? `${item} · ${clock(value)}` : clock(value);
    }
    if (key === "kill_participation") {
      return `${Math.round(value)}%`;
    }
    if (key === "deaths" || key === "lane_deaths") {
      return percent1(value).replace("%", "").replace(/[.,]0$/, "");
    }
    return number(value);
  }

  // --- compare with a friend (backend friend_compare.py) ---------------------------

  const friendState = { group: "all", data: null, error: "", timer: null, host: null };

  function friendCard() {
    const host = h("section", { class: "card friend-card", dataset: { card: "friend" } });
    friendState.host = host;
    if (friendState.data) {
      renderFriend();
    } else {
      host.replaceChildren(...friendShell(skeletonRows(3)));
    }
    loadFriend();
    return host;
  }

  // The card's header and body (the same markup as card()), for host.replaceChildren.
  function friendShell(body, extraHead) {
    return [
      h("header", { class: "card-head" }, icon("users"), h("h2", { text: t("friendTitle") }), extraHead ? h("span", { class: "card-head-extra" }, extraHead) : null),
      h("div", { class: "card-body" }, body)
    ];
  }

  async function loadFriend(op = "friend", args = {}) {
    clearTimeout(friendState.timer);
    const result = await call(op, { group: friendState.group, ...args });
    if (!friendState.host || !friendState.host.isConnected) {
      return;
    }
    if (result.ok) {
      friendState.data = result.data;
      friendState.error = result.data.state === "self" ? t("friendSelf") : "";
    } else {
      friendState.error = tOptional(`linkErrors.${result.code}`) || result.detail || t("friendFailed");
    }
    renderFriend();
    const data = friendState.data;
    if (data && (data.state === "loading" || data.refreshing) && state.view === "progress") {
      friendState.timer = setTimeout(() => loadFriend(), 3000);
    }
  }

  function friendForm(value = "") {
    const input = h("input", { class: "input", type: "text", value, placeholder: t("friendPlaceholder"), "aria-label": t("friendPlaceholder"), autocomplete: "off", spellcheck: "false" });
    const button = h("button", { class: "btn btn-primary", type: "submit" }, icon("users"), h("span", { text: t("friendCompare") }));
    return h(
      "div",
      {},
      h("p", { class: "muted small", text: t("friendHint") }),
      h(
        "form",
        {
          class: "link-form friend-form no-print",
          onsubmit: async (event) => {
            event.preventDefault();
            button.disabled = true;
            await loadFriend("friendSet", { steam: input.value });
          }
        },
        input,
        button
      ),
      friendState.error ? h("p", { class: "form-error", role: "alert", text: friendState.error }) : null
    );
  }

  function friendActions(data) {
    const busy = data.refreshing || data.state === "loading";
    return h(
      "span",
      { class: "toolbar-actions no-print" },
      // Icon buttons with their names as tooltips: two worded buttons squeezed
      // the card's title («Порівняння з другом») onto two lines.
      data.state !== "loading"
        ? h("button", {
            class: "btn btn-ghost btn-sm btn-icon",
            type: "button",
            disabled: busy,
            title: busy ? t("friendUpdating") : t("friendRefresh"),
            "aria-label": busy ? t("friendUpdating") : t("friendRefresh"),
            onclick: () => loadFriend("friendRefresh")
          }, icon("refresh-cw"))
        : null,
      h("button", {
        class: "btn btn-ghost btn-sm btn-icon",
        type: "button",
        title: t("friendChange"),
        "aria-label": t("friendChange"),
        onclick: () => loadFriend("friendRemove").then(() => loadFriend())
      }, icon("x"))
    );
  }

  function friendValue(key, value) {
    if (value === null || value === undefined) {
      return "—";
    }
    if (key === "win_rate") {
      return `${value}%`;
    }
    return ["kills", "deaths", "assists", "lh_per_min"].includes(key) ? decimal(value) : number(value);
  }

  function renderFriend() {
    const host = friendState.host;
    const data = friendState.data;
    if (!host) {
      return;
    }
    if (!data || data.state === "none" || data.state === "self" || data.state === "unlinked") {
      host.replaceChildren(...friendShell(friendForm()));
      hydrate(host);
      return;
    }
    const friend = data.friend || {};
    const who = friend.name || String(friend.account_id || "");
    if (data.state !== "ready") {
      const text = {
        loading: t("friendLoading", who),
        private: t("friendPrivate", who),
        offline: t("friendOffline"),
        error: t("friendError", data.code || "")
      }[data.state] || "";
      host.replaceChildren(
        ...friendShell(
          h("div", {}, data.state === "loading" ? skeletonRows(3) : null, h("p", { class: "muted", text }), data.state === "private" ? h("p", { class: "muted small", text: t("friendPrivateHint") }) : null),
          friendActions(data)
        )
      );
      hydrate(host);
      return;
    }
    const groups = h(
      "div",
      { class: "segmented segmented-sm no-print", role: "radiogroup", "aria-label": t("friendGroup") },
      ["all", "core", "support"].map((group) =>
        h("button", {
          type: "button",
          role: "radio",
          "aria-checked": String(data.group === group),
          disabled: group !== "all" && !(data.groups?.[group]?.me && data.groups?.[group]?.friend),
          text: t(`friendGroups.${group}`),
          onclick: () => {
            friendState.group = group;
            loadFriend();
          }
        })
      )
    );
    const cell = (row, side) =>
      h("td", { class: `num-col num${row.better === side ? " friend-better" : ""}`, text: friendValue(row.key, row[side]) });
    const table = h(
      "div",
      { class: "table-wrap table-wrap-tight" },
      h(
        "table",
        { class: "table" },
        h("thead", {}, h("tr", {}, h("th", { text: t("colMetric") }), h("th", { class: "num-col", text: t("friendYou") }), h("th", { class: "num-col", text: who }))),
        h("tbody", {}, data.rows.map((row) => h("tr", {}, h("td", { text: t(`friendMetrics.${row.key}`) }), cell(row, "me"), cell(row, "friend"))))
      )
    );
    const heroLine = (hero) =>
      h(
        "li",
        { class: "friend-hero" },
        heroLabel(hero.hero_id, hero.hero),
        h("span", { class: "muted num", text: t("friendHeroGames", hero.me.games, hero.me.win_rate, hero.friend.games, hero.friend.win_rate) })
      );
    const theirHeroes = (data.friend_heroes || []).map((hero) => h("span", { class: "chip with-pic" }, heroLabel(hero.hero_id, hero.hero), h("span", { class: "num muted", text: ` · ${hero.games}` })));
    host.replaceChildren(
      ...friendShell(
        h(
          "div",
          { class: "friend" },
          h(
            "div",
            { class: "friend-head" },
            h("div", {}, h("p", { class: "friend-name", text: who }), h("p", { class: "muted small", text: [friend.rank, t("friendGames", data.games.me, data.games.friend)].filter(Boolean).join(" · ") })),
            groups
          ),
          data.enough ? null : h("p", { class: "muted small", text: t("friendFew", data.min_games) }),
          table,
          data.common_heroes?.length ? h("div", {}, h("p", { class: "friend-sub", text: t("friendCommon") }), h("ul", { class: "friend-heroes" }, data.common_heroes.map(heroLine))) : null,
          theirHeroes.length ? h("div", {}, h("p", { class: "friend-sub", text: t("friendTheirHeroes", who) }), h("div", { class: "chips" }, theirHeroes)) : null,
          h("p", { class: "muted small", text: t("friendNote") })
        ),
        friendActions(data)
      )
    );
    hydrate(host);
  }

  // Every death of the last 20 matches with a map, as if always Radiant
  // (app/career_deaths.py); the map itself is drawn once the card is in the page.
  function deathMapCard(data) {
    if (!data || !(data.deaths || []).length) {
      return null;
    }
    const facts = [h("p", { class: "fact-line" }, h("strong", { text: t("mapDeaths") }), h("span", { class: "num", text: String(data.total) }))];
    for (const side of ["own", "river", "enemy"]) {
      if (data.by_side && data.by_side[side]) {
        facts.push(h("p", { class: "fact-line muted small" }, h("span", { text: t(`mapSide.${side}`) }), h("span", { class: "num", text: String(data.by_side[side]) })));
      }
    }
    const spots = (data.spots || []).filter((spot) => spot.label);
    if (spots.length) {
      facts.push(h("p", { class: "friend-sub", text: t("deathMapSpots") }));
      for (const spot of spots) {
        facts.push(h("p", { class: "fact-line map-spot-line small" }, h("span", { text: t("deathMapSpot", spot.label, spot.count, spot.matches) })));
      }
    }
    if (data.enemy_share_late != null) {
      facts.push(h("p", { class: "muted small", text: t("deathMapLate", data.enemy_share_late) }));
    }
    const body = h(
      "div",
      {},
      h("p", { class: "muted small chart-note", text: `${t("deathMapNote", data.matches, data.total, data.per_match)} ${t("deathMapTurned")}` }),
      h("div", { class: "map-layout" }, h("div", { class: "chart-host", dataset: { chart: "career-map" } }), h("div", { class: "map-facts" }, facts))
    );
    return card(t("deathMapTitle"), "skull", body);
  }

  function drawCareerMap(host, data) {
    window.LauncherCharts.map(host, {
      background: MAP_BACKGROUND,
      bounds: data.bounds,
      spots: (data.spots || []).map((spot) => ({ ...spot, title: t("mapSpotTitle", spot.count, spot.label || "") })),
      deaths: (data.deaths || []).map((death) => ({
        ...death,
        killer: [death.hero, death.killer ? t("killedBy", death.killer) : null].filter(Boolean).join(" · ")
      })),
      labels: t("mapLabels"),
      clock,
      ariaLabel: t("deathMapTitle")
    });
  }

  // The record against enemy heroes met 3+ times (career_analysis.opponents).
  function opponentsCard(record) {
    if (!record || !(record.hard?.length || record.easy?.length)) {
      return null;
    }
    const row = (hero) =>
      h(
        "li",
        { class: "friend-hero" },
        heroLabel(hero.hero_id, hero.hero),
        h("span", { class: "muted num", text: t("opponentRecord", hero.wins, hero.losses, hero.winrate) })
      );
    return card(
      t("opponentsTitle"),
      "swords",
      h(
        "div",
        { class: "friend" },
        h("p", { class: "muted small", text: t("opponentsNote", record.matches, record.min_games) }),
        record.hard?.length ? h("div", {}, h("p", { class: "friend-sub", text: t("opponentsHard") }), h("ul", { class: "friend-heroes" }, record.hard.map(row))) : null,
        record.easy?.length ? h("div", {}, h("p", { class: "friend-sub", text: t("opponentsEasy") }), h("ul", { class: "friend-heroes" }, record.easy.map(row))) : null
      )
    );
  }

  // Heroes to play more and to park (career_analysis.hero_pool), all heroes only.
  // «Ваші лінії»: the judged lanes of the last 20 reviewed matches (lane_duel.career_lanes).
  function lanesCard(lanes) {
    if (!lanes || !lanes.games) {
      return null;
    }
    const signed = (value) => (value === null || value === undefined ? "—" : value > 0 ? `+${value}` : `${value}`);
    const dots = (lanes.games_list || []).map((game) =>
      h("button", {
        type: "button",
        class: `lane-dot lane-${game.result}`,
        title: t("lanesDot", game.hero || "—", game.enemy || "—", t(`laneResult.${game.result}`), signed(game.gold_diff)),
        "aria-label": t("lanesDot", game.hero || "—", game.enemy || "—", t(`laneResult.${game.result}`), signed(game.gold_diff)),
        onclick: () => (game.match_id ? openMatch(game.match_id) : null)
      })
    );
    return card(
      t("lanesTitle"),
      "swords",
      h(
        "div",
        { class: "lanes" },
        h("p", { text: t("lanesLine", lanes.won, lanes.even, lanes.lost, lanes.games) }),
        h("div", { class: "lane-dots" }, dots),
        lanes.gold_diff === null ? null : h("p", { class: "muted small", text: t("lanesGold", signed(lanes.gold_diff)) }),
        (lanes.hard || []).length ? h("p", { class: "muted small", text: t("lanesHard", lanes.hard.map((row) => `${row.hero} (${row.lost})`).join(", ")) }) : null
      )
    );
  }

  function heroPoolCard(pool) {
    if (!pool || !(pool.play_more?.length || pool.park?.length)) {
      return null;
    }
    const row = (hero) =>
      h(
        "li",
        { class: "friend-hero" },
        heroLabel(hero.hero_id, hero.hero),
        h("span", { class: "muted num", text: t("poolRecord", hero.wins, hero.matches, hero.winrate, hero.bracket_winrate == null ? null : Math.round(hero.bracket_winrate)) })
      );
    return card(
      t("poolTitle"),
      "users",
      h(
        "div",
        { class: "friend" },
        h("p", { class: "muted small", text: t("poolNote") }),
        pool.play_more?.length ? h("div", {}, h("p", { class: "friend-sub", text: t("poolMore") }), h("ul", { class: "friend-heroes" }, pool.play_more.map(row))) : null,
        pool.park?.length ? h("div", {}, h("p", { class: "friend-sub", text: t("poolPark") }), h("ul", { class: "friend-heroes" }, pool.park.map(row))) : null
      )
    );
  }

  // The rank medal over time (app/rank_history.py): shown once it has changed.
  function rankHistoryCard(history) {
    if (!history || !(history.steps || []).length || history.steps.length < 2) {
      return null;
    }
    const day = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString(state.locale === "uk" ? "uk-UA" : "en-GB");
    const line = history.change >= 0
      ? t("rankUp", history.first, history.current, day(history.since))
      : t("rankDown", history.first, history.current, day(history.since));
    return card(
      t("rankHistoryTitle"),
      "trending-up",
      h(
        "div",
        { class: "draft" },
        h("p", { text: line }),
        h(
          "div",
          { class: "death-summary" },
          history.steps.map((step) => h("span", { class: "chip" }, h("span", { text: step.label || "—" }), h("span", { class: "muted num", text: ` · ${day(step.date)}` })))
        ),
        h("p", { class: "muted small", text: t("rankNote") })
      )
    );
  }

  // The player's own build on the hero (app/hero_build.py).
  function heroBuildCard(build) {
    if (!build || !(build.items || []).length) {
      return null;
    }
    const pct = (value) => (value == null ? "—" : `${value}%`);
    const time = (value) => (value == null ? "—" : clock(value));
    return card(
      t("heroBuildTitle", build.hero),
      "coins",
      h(
        "div",
        { class: "draft" },
        h("p", { class: "muted small", text: t("buildNote", build.matches, build.wins) }),
        build.highlights.length ? coachList(build.highlights, "idle") : null,
        h(
          "div",
          { class: "table-wrap table-wrap-tight" },
          h(
            "table",
            { class: "table table-wrapping" },
            h(
              "thead",
              {},
              h(
                "tr",
                {},
                h("th", { text: t("buildItem") }),
                h("th", { class: "num-col", text: t("buildGames") }),
                h("th", { class: "num-col", text: t("buildWinrate") }),
                h("th", { class: "num-col hide-narrow", text: t("buildWithout") }),
                h("th", { class: "num-col", text: t("buildWinTime") }),
                h("th", { class: "num-col", text: t("buildLossTime") })
              )
            ),
            h(
              "tbody",
              {},
              build.items.map((row) =>
                h(
                  "tr",
                  {},
                  h("td", {}, itemLabel(row.item, row.item)),
                  h("td", { class: "num-col num", text: String(row.games) }),
                  h("td", { class: "num-col num", text: pct(row.winrate) }),
                  h("td", { class: "num-col num muted hide-narrow", text: pct(row.winrate_without) }),
                  h("td", { class: "num-col num", text: time(row.t_win) }),
                  h("td", { class: "num-col num muted", text: time(row.t_loss) })
                )
              )
            )
          )
        ),
        itemTrendBlock(build.timing_trend)
      )
    );
  }

  // The key item's timing game by game (hero_build.timing_trend): drawn by drawItemTrend.
  function itemTrendBlock(trend) {
    if (!trend || !(trend.points || []).length) {
      return null;
    }
    let line;
    if (Number.isFinite(trend.change)) {
      const tone = trend.change < -30 ? "good" : trend.change > 30 ? "bad" : "idle";
      const word = trend.change < -30 ? t("trendSooner", clock(-trend.change)) : trend.change > 30 ? t("trendLater", clock(trend.change)) : t("trendSame");
      line = h(
        "p",
        { class: "small" },
        h("span", { text: t("trendLine", clock(trend.recent), trend.recent_games, clock(trend.before), trend.before_games) }),
        " ",
        h("span", { class: `delta delta-${tone}`, text: word })
      );
    } else {
      line = h("p", { class: "small", text: t("trendRecentOnly", clock(trend.recent), trend.recent_games) });
    }
    return h(
      "div",
      { class: "item-trend" },
      h("p", { class: "friend-sub" }, itemLabel(trend.item, t("trendTitle", trend.item))),
      line,
      h("div", { class: "chart-host", dataset: { chart: "item-trend" } })
    );
  }

  function drawItemTrend(host, trend) {
    window.LauncherCharts.columns(host, {
      items: trend.points.map((point, index) => ({
        label: String(point.match_id ?? index),
        value: Math.round(point.t / 6) / 10,
        title: `${trend.item} · ${clock(point.t)}`,
        detail: point.win ? t("win") : t("loss"),
        key: point.win ? "win" : "loss",
        matchId: point.match_id
      })),
      height: 120,
      color: VIZ_1,
      valueLabel: t("trendMinute"),
      ariaLabel: t("trendTitle", trend.item),
      onSelect: (item) => (item.matchId ? openMatch(item.matchId) : null)
    });
  }

  function selfCompareCard(compare) {
    if (!compare) {
      return null;
    }
    const groupHead = (label, group) => h("th", { class: "num-col" }, h("span", { text: label }), h("span", { class: "self-group muted", text: t("selfGroup", group.count, group.winrate ?? "—") }));
    return card(
      t("selfTitle", compare.hero),
      "trophy",
      h(
        "div",
        { class: "draft" },
        h("p", { class: "muted small", text: t("selfNote", compare.matches) }),
        compare.highlights.length ? coachList(compare.highlights, "idle") : null,
        h(
          "div",
          { class: "table-wrap table-wrap-tight" },
          h(
            "table",
            { class: "table table-wrapping" },
            h("thead", {}, h("tr", {}, h("th", { text: t("colMetric") }), groupHead(t("selfBest"), compare.best), groupHead(t("selfWorst"), compare.worst))),
            h(
              "tbody",
              {},
              compare.rows.map((row) =>
                h(
                  "tr",
                  {},
                  h("td", { text: t(`selfMetrics.${row.key}`) }),
                  h("td", { class: "num-col num", text: selfValue(row.key, row.best, compare.first_items?.best) }),
                  h("td", { class: "num-col num muted", text: selfValue(row.key, row.worst, compare.first_items?.worst) })
                )
              )
            )
          )
        )
      )
    );
  }

  function draftCard(analysis) {
    const draft = analysis.draft;
    if (!draft) {
      return null;
    }
    const parts = [];
    if (draft.has_matchups) {
      parts.push(h("p", { class: "muted small", text: t("draftNote", draft.hero) }));
      parts.push(
        h(
          "div",
          { class: "table-wrap table-wrap-tight" },
          h(
            "table",
            { class: "table" },
            h("thead", {}, h("tr", {}, h("th", { text: t("draftEnemy") }), h("th", { class: "num-col", text: t("draftWinrate") }), h("th", { class: "num-col hide-narrow", text: t("draftGames") }))),
            h(
              "tbody",
              {},
              draft.enemies.map((row) =>
                h(
                  "tr",
                  {},
                  h("td", {}, heroLabel(row.hero_id || row.hero, row.hero)),
                  row.winrate == null
                    ? h("td", { class: "num-col num muted", text: "—" })
                    : h("td", { class: "num-col num" }, h("span", { class: "dot", "data-tone": winrateTone(row.winrate) }), percent1(row.winrate)),
                  h("td", { class: "num-col num muted hide-narrow", text: row.games ? number(row.games) : "" })
                )
              )
            )
          )
        )
      );
    } else {
      parts.push(h("p", { class: "muted", text: t("draftNoData") }));
    }
    if ((draft.pool || []).length > 1) {
      parts.push(
        h(
          "div",
          { class: "draft-block" },
          h("h3", { class: "coach-section-title", text: t("draftPool") }),
          h("p", { class: "muted small", text: t("draftPoolNote") }),
          h(
            "ul",
            { class: "draft-pool" },
            draft.pool.map((row) =>
              h(
                "li",
                { class: row.hero === draft.better_pick ? "is-best" : "" },
                h("span", { class: "draft-pool-hero" }, heroLabel(row.hero_id || row.hero, row.hero), row.picked ? h("span", { class: "tag", text: t("draftPicked") }) : null),
                h("span", { class: "num draft-edge" }, h("span", { class: "dot", "data-tone": row.edge >= 2 ? "good" : row.edge <= -2 ? "bad" : "idle" }), signedPercent(row.edge))
              )
            )
          ),
          draft.better_pick ? h("p", { class: "small", text: t("draftBetter", draft.better_pick) }) : null
        )
      );
    }
    if ((draft.counters || []).length) {
      parts.push(
        h(
          "div",
          { class: "draft-block" },
          h("h3", { class: "coach-section-title", text: t("draftCounters") }),
          h(
            "ul",
            { class: "draft-counters" },
            draft.counters.map((counter) =>
              h(
                "li",
                {},
                h(
                  "p",
                  { class: "draft-counter-head" },
                  h("span", { class: "draft-counter-heroes" }, counter.heroes.map((heroName) => heroLabel(heroName, heroName))),
                  h("span", { class: "tag", text: t(`draftReasons.${counter.reason}`) }),
                  counter.for_role ? null : h("span", { class: "muted small", text: t("draftForSupports") })
                ),
                h(
                  "div",
                  { class: "chips" },
                  counter.items.map((item) => {
                    const bought = counter.bought.includes(item);
                    return h("span", { class: `chip ${bought ? "chip-on" : ""}`, title: bought ? t("draftBought") : "" }, itemPic(item, "sm"), h("span", { text: item }), bought ? icon("circle-check") : null);
                  })
                )
              )
            )
          )
        )
      );
    }
    return card(t("draftTitle"), "shield", h("div", { class: "draft" }, parts));
  }

  function rankCard(analysis) {
    const peers = analysis.peers;
    if (!peers) {
      return null;
    }
    const heroes = (peers.peers || []).map((p) => p.hero).filter(Boolean).slice(0, 2).join(", ");
    const note = h("p", { class: "muted small", text: t("rankMatchNote", peers.lobby_rank_label, peers.role_label || "", heroes) });
    if (!(peers.peers || []).length) {
      return card(t("rankTitle"), "swords", h("div", {}, note, h("p", { class: "muted", text: t("rankNoPeers") })));
    }
    const rows = RANK_METRICS.filter((key) => peers.me[key] !== null && peers.me[key] !== undefined).map((key) =>
      h(
        "tr",
        {},
        h("td", { text: t(`metrics.${key}`) }),
        h("td", { class: "num-col num", text: formatMetric(key, peers.me[key]) }),
        h("td", { class: "num-col num", text: formatMetric(key, peers.avg[key]) }),
        diffCell(key, peers.me[key], peers.avg[key])
      )
    );
    return card(
      t("rankTitle"),
      "swords",
      h(
        "div",
        {},
        note,
        h(
          "div",
          { class: "table-wrap table-wrap-tight" },
          h(
            "table",
            { class: "table" },
            h("thead", {}, h("tr", {}, h("th", { text: t("colMetric") }), h("th", { class: "num-col", text: t("colYou") }), h("th", { class: "num-col", text: t("colOpponent") }), h("th", { class: "num-col", text: t("colDiff") }))),
            h("tbody", {}, rows)
          )
        ),
        explain("explainRank")
      )
    );
  }

  function careerRankCard(career) {
    const rank = career.rank;
    if (!rank || !(rank.metrics || []).length) {
      return card(t("rankCareerTitle"), "swords", h("p", { class: "muted", text: t("rankCareerEmpty") }));
    }
    const rows = rank.metrics.map((row) =>
      h(
        "tr",
        {},
        h("td", { text: t(`metrics.${row.key}`) }),
        h("td", { class: "num-col num", text: formatMetric(row.key, row.you) }),
        h("td", { class: "num-col num", text: formatMetric(row.key, row.peers) }),
        diffCell(row.key, row.you, row.peers, row.better)
      )
    );
    return card(
      t("rankCareerTitle"),
      "swords",
      h(
        "div",
        {},
        h("p", { class: "muted small", text: t("rankCareerNote", rank.rank_label, rank.role_label || "", rank.matches) }),
        h(
          "div",
          { class: "table-wrap table-wrap-tight" },
          h(
            "table",
            { class: "table" },
            h("thead", {}, h("tr", {}, h("th", { text: t("colMetric") }), h("th", { class: "num-col", text: t("colYou") }), h("th", { class: "num-col", text: t("colPeers") }), h("th", { class: "num-col", text: t("colDiff") }))),
            h("tbody", {}, rows)
          )
        )
      )
    );
  }

  // Every death with what is known around it (app/death_review.py).
  function deathsCard(analysis) {
    const block = analysis.death_review;
    const deaths = (block && block.deaths) || [];
    if (!deaths.length) {
      return null;
    }
    const notes = Object.entries(block.notes || {}).filter(([, count]) => count > 0);
    const summary = notes.length
      ? h(
          "div",
          { class: "death-summary" },
          notes.map(([note, count]) => h("span", { class: "chip" }, h("span", { text: t(`deathNote.${note}`) }), h("span", { class: "num", text: ` · ${count}` })))
        )
      : h("p", { class: "muted small", text: t("deathsNoPattern") });
    const rows = deaths.map((death) => {
      const where = [
        death.zone ? t(`deathZone.${death.zone}`) : null,
        death.side ? t(`mapSide.${death.side}`) : null
      ].filter(Boolean).join(" · ");
      const facts = [
        death.killer ? t("killedBy", death.killer) : null,
        where || null,
        Number.isFinite(death.gold) ? t("deathGold", number(death.gold)) : null,
        Number.isFinite(death.after_respawn) ? t("deathAfterRespawn", death.after_respawn) : null
      ].filter(Boolean);
      return h(
        "li",
        { class: "moment death-row" },
        h("span", { class: "moment-time num", text: clock(death.t) }),
        h("span", { class: "moment-icon" }, icon("skull")),
        h(
          "span",
          { class: "death-body" },
          h("span", { text: facts.join(" · ") || t("deathNoFacts") }),
          death.warning
            ? h("span", { class: "muted small death-warning", text: t("deathWarned", clock(death.warning.t), death.warning.action || "") })
            : null,
          deathLast(death)
        ),
        watchButton(analysis, death.t)
      );
    });
    const body = h("div", {}, summary, foldList(h("ol", { class: "moments deaths-list" }, rows), 3));
    return card(t("deathsTitle", deaths.length), "skull", body);
  }

  // «Watch this moment»: copies the Dota console command that jumps the replay
  // to REPLAY_LEAD seconds before it (analysis.replay: the recording's offset
  // between game time and the match clock; live-recorded matches only).
  const REPLAY_LEAD = 10;

  function replayTick(analysis, at) {
    const replay = analysis && analysis.replay;
    if (!replay || !Number.isFinite(replay.clock_offset) || !Number.isFinite(at)) {
      return null;
    }
    return Math.max(0, Math.round((at + replay.clock_offset - REPLAY_LEAD) * (replay.tick_rate || 30)));
  }

  function watchButton(analysis, at) {
    const tick = replayTick(analysis, at);
    if (tick === null || !api.copyReplayTick) {
      return null;
    }
    const label = h("span", { text: t("watchMoment") });
    return h(
      "button",
      {
        type: "button",
        class: "btn btn-ghost btn-sm watch-moment no-print",
        title: t("watchMomentHint"),
        onclick: async (event) => {
          const button = event.currentTarget;
          const result = await api.copyReplayTick(tick);
          label.textContent = result && result.ok ? t("watchCopied") : t("watchFailed");
          button.classList.toggle("is-done", Boolean(result && result.ok));
        }
      },
      icon("play"),
      label
    );
  }

  // The last 20 s before a death (live GSI, app/last_moments.py): an HP line,
  // a burst kill and the saving items that were ready.
  function deathLast(death) {
    const last = death.last;
    if (!last || !Array.isArray(last.hp) || !last.hp.length) {
      return null;
    }
    const W = 160;
    const H = 32;
    const x = (s) => ((20 + Math.max(-20, Math.min(0, s))) / 20) * W;
    const y = (hp) => H - 2 - (Math.max(0, Math.min(100, hp)) / 100) * (H - 4);
    const curve = [...last.hp, [0, 0]];
    const points = curve.map(([s, hp]) => `${x(s).toFixed(1)},${y(hp).toFixed(1)}`).join(" ");
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("class", "death-hp");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${t("deathLastTitle")}: ${last.hp.map(([, hp]) => `${hp}%`).join(", ")}`);
    // Half HP as a faint guide, the HP as a filled line, the death as a cross.
    const half = document.createElementNS(NS, "line");
    Object.entries({ x1: 0, x2: W, y1: y(50), y2: y(50), class: "death-hp-half" }).forEach(([key, value]) => half.setAttribute(key, value));
    const area = document.createElementNS(NS, "polygon");
    area.setAttribute("points", `${x(curve[0][0]).toFixed(1)},${H} ${points} ${W},${H}`);
    area.setAttribute("class", "death-hp-area");
    const line = document.createElementNS(NS, "polyline");
    line.setAttribute("points", points);
    const cross = document.createElementNS(NS, "path");
    cross.setAttribute("d", `M${W - 7},${H - 9} l5,5 m0,-5 l-5,5`);
    cross.setAttribute("class", "death-hp-end");
    svg.append(half, area, line, cross);
    // What the line is, in words: a bare falling line meant nothing to a new player.
    const lines = [h("span", { class: "muted small", text: t("deathLastTitle") })];
    if (last.burst_s) {
      lines.push(h("span", { class: "muted small", text: t("deathBurst", last.burst_s) }));
    }
    // Ready while the hero could act (the same second): "not pressed"; ready only
    // while disabled: said as such.
    const unpressed = (death.notes || []).includes("saver_ready");
    const keys = unpressed ? last.usable || [] : last.ready || [];
    const names = (unpressed ? last.usable_names : last.ready_names) || [];
    if (keys.length) {
      lines.push(
        h(
          "span",
          { class: "muted small death-ready" },
          h("span", { text: t(unpressed ? "deathReady" : "deathReadyStunned") }),
          keys.map((key, index) =>
            h(
              "span",
              { class: "death-item" },
              // A bottled rune ("rune:Haste") shows the Bottle's icon.
              window.DotaIcons
                ? window.DotaIcons.itemPicture(document, String(key).startsWith("rune:") ? "item_bottle" : key, "sm", names[index])
                : null,
              h("span", { text: names[index] || key })
            )
          )
        )
      );
    }
    return h("span", { class: "death-last", title: t("deathLastTitle") }, svg, h("span", { class: "death-last-text" }, lines));
  }

  function momentsCard(analysis) {
    // Deaths have their own card when the review has one.
    const moments = (analysis.moments || []).filter(
      (moment) => moment.type !== "death" || !(analysis.death_review && analysis.death_review.deaths || []).length
    );
    if (!moments.length) {
      return null;
    }
    const items = moments.slice(0, 16).map((moment) => {
      let iconName = "info";
      let text = "";
      let sub = "";
      if (moment.type === "death") {
        iconName = "skull";
        text = t("momentDeath", moment.killer);
        sub = moment.gold ? t("momentGold", number(moment.gold)) : "";
      } else if (moment.type === "item") {
        iconName = "coins";
        text = t("momentItem", moment.item);
      } else if (moment.type === "buyback") {
        iconName = "rotate-cw";
        text = t("momentBuyback");
      } else if (moment.type === "farm_stall") {
        iconName = "hourglass";
        text = t("momentStall", clock(moment.to));
      }
      return h(
        "li",
        { class: `moment moment-${moment.type}` },
        h("span", { class: "moment-time num", text: clock(moment.t) }),
        h("span", { class: "moment-icon" }, icon(iconName)),
        h("span", { class: "moment-text" }, h("span", { text }), sub ? h("span", { class: "muted", text: ` · ${sub}` }) : null),
        watchButton(analysis, moment.t)
      );
    });
    return card(t("momentsTitle"), "clock", h("ol", { class: "moments" }, items));
  }

  // What the coach said during this match (the app's own recording).
  function adviceLogCard(analysis) {
    const advice = analysis.advice || [];
    if (!advice.length) {
      return null;
    }
    const shown = state.adviceLogOpen ? advice : advice.slice(0, 8);
    const follow = analysis.advice_follow || { ignored: [] };
    const deathAfter = new Map((follow.ignored || []).map((item) => [item.t, item.death_t]));
    const list = h(
      "ol",
      { class: "moments advice-log" },
      shown.map((item) =>
        h(
          "li",
          { class: "moment" },
          h("span", { class: "moment-time num", text: clock(item.t) }),
          h("span", { class: "moment-icon" }, h("span", { class: "dot", "data-tone": item.mode === "urgent" ? "bad" : "warn" })),
          h(
            "span",
            { class: "moment-text" },
            h("span", { text: item.action }),
            item.reason ? h("span", { class: "muted advice-log-reason", text: item.reason }) : null,
            item.why ? h("details", { class: "advice-why" }, h("summary", { text: t("adviceWhy") }), h("p", { text: item.why })) : null,
            deathAfter.has(item.t)
              ? h("span", { class: "advice-log-death" }, icon("skull"), h("span", { text: t("adviceLogDeath", clock(deathAfter.get(item.t))) }))
              : null,
            item.key ? adviceVerdicts(item) : null
          )
        )
      )
    );
    const more = advice.length > shown.length
      ? h(
          "button",
          {
            class: "btn btn-ghost btn-sm no-print",
            type: "button",
            onclick: () => {
              state.adviceLogOpen = true;
              renderMatch();
            }
          },
          h("span", { text: t("adviceLogMore", advice.length) })
        )
      : null;
    const urgent = advice.filter((item) => item.mode === "urgent").length;
    return card(
      t("adviceLogTitle"),
      "lightbulb",
      [
        h("p", { class: "muted small chart-note", text: t("adviceLogHint", advice.length, urgent) }),
        h("p", { class: "muted small no-print", text: t("adviceRateHint") }),
        list,
        more
      ].filter(Boolean)
    );
  }

  // What the player's marks say per kind of advice (backend advice_feedback.summary),
  // the most unwanted first; «quieter» ones now wait twice as long in a game.
  function adviceMarksCard(feedback) {
    const byKind = feedback && feedback.by_decision_point ? Object.entries(feedback.by_decision_point) : [];
    if (!feedback || !feedback.matches || !byKind.length) {
      return null;
    }
    const quieter = new Set(feedback.quieter || []);
    const unwanted = (counts) => (counts.irrelevant || 0) + (counts.repeated || 0);
    const total = (counts) => unwanted(counts) + (counts.useful || 0);
    byKind.sort(([, a], [, b]) => unwanted(b) / total(b) - unwanted(a) / total(a) || total(b) - total(a));
    const rows = byKind.map(([kind, counts]) =>
      h(
        "tr",
        {},
        h("td", {}, h("span", { text: tOptional(`adviceKinds.${kind}`) || kind }), quieter.has(kind) ? h("span", { class: "chip advice-quieter", text: t("adviceMarksQuieter") }) : null),
        ...["useful", "irrelevant", "repeated"].map((verdict) => h("td", { class: "num-col num", text: String(counts[verdict] || 0) }))
      )
    );
    return card(
      t("adviceMarksTitle"),
      "lightbulb",
      h(
        "div",
        {},
        h("p", { class: "muted small", text: t("adviceMarksHint", feedback.matches) }),
        h(
          "div",
          { class: "table-wrap table-wrap-tight" },
          h(
            "table",
            { class: "table" },
            h("thead", {}, h("tr", {}, h("th", { text: t("adviceMarksKind") }), ...["useful", "irrelevant", "repeated"].map((verdict) => h("th", { class: "num-col", text: t(`adviceVerdicts.${verdict}`) })))),
            h("tbody", {}, rows)
          )
        )
      )
    );
  }

  // «Корисно / не до речі / повторювалося» under a card (backend advice_feedback.py);
  // pressing the chosen one again clears it. Local only, never during a game.
  function adviceVerdicts(item) {
    const matchId = state.matchId;
    const group = h("span", { class: "advice-verdicts no-print", role: "group", "aria-label": t("adviceRate") });
    const draw = () =>
      group.replaceChildren(
        ...["useful", "irrelevant", "repeated"].map((verdict) =>
          h("button", {
            class: "chip advice-verdict",
            type: "button",
            "aria-pressed": String(item.feedback === verdict),
            text: t(`adviceVerdicts.${verdict}`),
            onclick: async () => {
              const next = item.feedback === verdict ? null : verdict;
              const previous = item.feedback;
              item.feedback = next;
              draw();
              const result = await call("adviceFeedback", { matchId, key: item.key, verdict: next });
              if (!result.ok || state.matchId !== matchId) {
                item.feedback = result.ok ? next : previous;
                draw();
              }
            }
          })
        )
      );
    draw();
    return group;
  }

  function scoreboardCard(rows) {
    const teams = [true, false].map((radiant) => {
      const players = rows.filter((row) => row.is_radiant === radiant);
      return h(
        "div",
        { class: "team" },
        h("p", { class: "team-name", text: radiant ? t("radiant") : t("dire") }),
        h(
          "table",
          { class: "table table-compact" },
          h(
            "thead",
            {},
            h("tr", {}, h("th", { text: t("colHero") }), h("th", { class: "num-col", text: t("colKda") }), h("th", { class: "num-col", text: t("colNw") }), h("th", { class: "num-col hide-narrow", text: t("colGpm") }), h("th", { class: "num-col hide-narrow", text: t("colDmg") }))
          ),
          h(
            "tbody",
            {},
            players.map((row) =>
              h(
                "tr",
                { class: row.me ? "is-me" : "" },
                h(
                  "td",
                  {},
                  heroLabel(row.hero_id || row.hero, row.hero || "—"),
                  row.name ? h("span", { class: "muted small player-sub", text: row.name }) : null,
                  // Each player's items at the end, small, under the name.
                  Array.isArray(row.items) && row.items.length && window.DotaIcons
                    ? h("span", { class: "player-items", "aria-label": t("stats.items") }, row.items.slice(0, 6).map((key) => window.DotaIcons.itemPicture(document, key, "sm")))
                    : null
                ),
                h("td", { class: "num-col num", text: combatScore(row) }),
                h("td", { class: "num-col num", text: number(row.net_worth) }),
                h("td", { class: "num-col num hide-narrow", text: number(row.gpm) }),
                h("td", { class: "num-col num hide-narrow", text: number(row.hero_damage) })
              )
            )
          )
        )
      );
    });
    return card(t("scoreboardTitle"), "swords", h("div", { class: "teams" }, teams));
  }

  // --- AI coach -------------------------------------------------------------------

  function coachCard(coach, kind) {
    if (!coach || coach.state === "none") {
      return null;
    }
    const title = t(kind === "career" ? "coachCareerTitle" : "coachTitle");
    if (coach.state === "not_enough") {
      return card(title, "graduation-cap", h("p", { class: "muted", text: t("coachNotEnough", coach.need) }));
    }
    if (coach.state === "off" && !coach.review) {
      return aiOffCard(title);
    }
    const body = [];
    const review = coach.review;
    if (review) {
      body.push(kind === "career" ? careerReview(review) : matchReview(review));
    } else if (coach.state === "pending") {
      body.push(h("p", { class: "muted small", text: t(kind === "career" ? "coachCareerPending" : "coachPending") }), skeletonRows(4));
    } else if (coach.state === "waiting") {
      body.push(h("p", { class: "muted", text: t("coachWaiting") }));
    }
    const status = coachStatusLine(coach, kind);
    if (status) {
      body.push(status);
    }
    if (review) {
      body.push(h("p", { class: "coach-footer muted small", text: t("coachFooter", coach.provider_label || "AI", coach.model || "") }));
    }
    const panel = aiPanel(kind);
    if (panel) {
      body.push(panel);
    }
    const settingsButton =
      coach.state !== "off"
        ? h(
            "button",
            {
              class: "btn btn-ghost btn-sm",
              type: "button",
              "aria-expanded": String(Boolean(state.aiPanel)),
              onclick: () => toggleAiPanel(kind, state.aiPanel ? null : "info")
            },
            icon("settings"),
            h("span", { text: t("aiSettings") })
          )
        : null;
    const head = h("span", { class: "coach-head" }, h("span", { class: "tag", text: t("coachTag") }), settingsButton);
    return h("div", { class: "coach-card" }, card(title, "graduation-cap", body, head));
  }

  // An id per question (backend ask_runs.py): a lost answer is read by it later.
  const ASK_STATUS_TRIES = 30;
  const ASK_STATUS_EVERY_MS = 3000;

  function askRequestId() {
    const random = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    return `ask-${random}`.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64);
  }

  // Still worth waiting for: the launcher gave up (timeout) or the backend says
  // the same question is being answered.
  function askStillRunning(result) {
    if (result.ok) {
      return Boolean(result.data && result.data.code === "pending");
    }
    return result.code === "request_failed" && /time/i.test(result.detail || "");
  }

  // "Ask the coach": a free question about this match, answered from its facts.
  // «Запитати тренера» about one match (op "ask") or, with `career`, the recent matches.
  function askCard(detail, career = false) {
    const coach = detail.coach;
    if (!coach || coach.state === "off" || coach.state === "none") {
      return null;
    }
    const history = h("div", { class: "ask-history" });
    const renderHistory = () =>
      history.replaceChildren(
        ...(detail.questions || []).map((qa) =>
          h("div", { class: "ask-item" }, h("p", { class: "ask-q", text: qa.question }), h("p", { class: "ask-a", text: qa.answer }), window.WardlyCoachEvidence.render(qa, state.locale))
        )
      );
    renderHistory();
    const input = h("input", { class: "input ask-input", type: "text", maxlength: "300", placeholder: t(career ? "askCareerPlaceholder" : "askPlaceholder"), "aria-label": t("askTitle") });
    const button = h("button", { class: "btn btn-primary btn-sm", type: "submit" }, icon("send"), h("span", { text: t("askButton") }));
    const note = h("p", { class: "muted small ask-note", role: "status" });
    const pending = h("div", { class: "ask-pending hidden" }, h("p", { class: "muted small", text: t("askThinking") }), skeletonRows(2));
    const chips = h(
      "div",
      { class: "ask-chips" },
      t(career ? "askCareerSuggestions" : "askSuggestions").map((question) =>
        h("button", { class: "chip ask-chip", type: "button", text: question, onclick: () => submit(question) })
      )
    );
    async function submit(question) {
      const text = String(question || "").trim();
      if (!text) {
        note.textContent = t("askErrors.empty_question");
        return;
      }
      input.value = text;
      button.disabled = true;
      input.disabled = true;
      chips.querySelectorAll("button").forEach((chip) => {
        chip.disabled = true;
      });
      note.textContent = "";
      pending.classList.remove("hidden");
      state.askBusy = true;
      const requestId = askRequestId();
      let result = career
        ? await call("askCareer", { question: text, requestId })
        : await call("ask", { matchId: detail.match_id, question: text, requestId });
      // The answer may still come after the launcher stopped waiting (or another
      // request is already asking the same): read it by the request id while this
      // card is on screen, without asking the model again.
      for (let tries = 0; tries < ASK_STATUS_TRIES && section.isConnected && askStillRunning(result); tries += 1) {
        await new Promise((resolve) => setTimeout(resolve, ASK_STATUS_EVERY_MS));
        const status = await call("askStatus", { requestId });
        if (status.ok && status.data && status.data.state === "done") {
          result = { ok: true, data: status.data.result };
        } else if (!status.ok || !status.data || status.data.state !== "running") {
          break;
        }
      }
      state.askBusy = false;
      pending.classList.add("hidden");
      button.disabled = false;
      input.disabled = false;
      chips.querySelectorAll("button").forEach((chip) => {
        chip.disabled = false;
      });
      if (result.ok && result.data && result.data.ok) {
        input.value = "";
        detail.questions = result.data.history || [];
        renderHistory();
        return;
      }
      const code = (result.data && result.data.code) || (/time/i.test(result.detail || "") ? "timeout" : "bad_response");
      note.textContent = tOptional(`askErrors.${code}`) || tOptional(`coachErrors.${code}`) || t("coachErrors.bad_response");
    }
    const form = h(
      "form",
      {
        class: "ask-form no-print",
        onsubmit: (event) => {
          event.preventDefault();
          submit(input.value);
        }
      },
      input,
      button
    );
    const section = card(t("askTitle"), "message-circle", [
      h("p", { class: "muted small no-print", text: t(career ? "askCareerHint" : "askHint") }),
      form,
      h("div", { class: "no-print" }, chips),
      pending,
      note,
      history
    ]);
    // A PDF has no form: without questions asked the card would print empty.
    section.classList.add("ask-card");
    return section;
  }

  function coachStatusLine(coach, kind) {
    const request = async (event) => {
      event.currentTarget.disabled = true;
      await requestCoach(kind);
    };
    if (coach.state === "pending" && coach.review) {
      return h("p", { class: "coach-status muted small" }, h("span", { class: "skeleton skeleton-dot" }), h("span", { text: t("coachUpdating") }));
    }
    if (coach.state === "waiting") {
      return h("div", { class: "coach-actions" }, h("button", { class: "btn btn-sm", type: "button", onclick: request }, icon("graduation-cap"), h("span", { text: t("coachNow") })));
    }
    if (coach.state === "error") {
      return h(
        "div",
        { class: "coach-status coach-error", role: "status" },
        icon("circle-alert"),
        h("span", { text: tOptional(`coachErrors.${coach.error}`) || t("coachErrors.bad_response") }),
        h("button", { class: "btn btn-sm", type: "button", onclick: request }, icon("refresh-cw"), h("span", { text: t("coachRetry") }))
      );
    }
    if (coach.state === "ready" && coach.review) {
      return h("div", { class: "coach-actions" }, h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: request }, icon("rotate-cw"), h("span", { text: t("coachRewrite") })));
    }
    return null;
  }

  function matchReview(review) {
    const parts = [h("p", { class: "coach-summary", text: review.summary })];
    if (review.turning_points?.length) {
      parts.push(
        coachSection(
          t("coachTurning"),
          h(
            "ul",
            { class: "coach-moments" },
            review.turning_points.map((point) => h("li", {}, h("span", { class: "coach-time num", text: point.time }), h("span", { text: point.text })))
          )
        )
      );
    }
    if (review.mistakes?.length) {
      parts.push(coachSection(t("coachMistakes"), coachBlocks(review.mistakes, t("coachFix"))));
    }
    if (review.strengths?.length) {
      parts.push(coachSection(t("coachStrengths"), coachList(review.strengths, "good")));
    }
    if (review.next_game?.length) {
      parts.push(coachSection(t("coachNextGame"), coachGoals(review.next_game)));
    }
    const evidence = window.WardlyCoachEvidence.render(review, state.locale);
    if (evidence) parts.push(evidence);
    return h("div", { class: "coach-review" }, parts);
  }

  function careerReview(review) {
    const parts = [h("p", { class: "coach-summary", text: review.summary })];
    if (review.patterns?.length) {
      parts.push(coachSection(t("coachPatterns"), coachBlocks(review.patterns, t("coachTrain"))));
    }
    if (review.strengths?.length) {
      parts.push(coachSection(t("coachStrengths"), coachList(review.strengths, "good")));
    }
    if (review.plan?.length) {
      parts.push(coachSection(t("coachPlan"), coachGoals(review.plan)));
    }
    return h("div", { class: "coach-review" }, parts);
  }

  function coachSection(title, content) {
    return h("div", { class: "coach-section" }, h("h3", { class: "coach-section-title", text: title }), content);
  }

  function coachBlocks(blocks, fixLabel) {
    return h(
      "ol",
      { class: "findings" },
      blocks.map((block, index) =>
        h(
          "li",
          { class: "finding" },
          h("span", { class: "finding-index num", text: String(index + 1) }),
          h(
            "div",
            { class: "finding-body" },
            h("p", { class: "finding-title", text: block.title }),
            h("p", { class: "finding-text", text: block.detail }),
            block.fix ? h("p", { class: "finding-drill" }, icon("lightbulb"), h("span", {}, h("strong", { text: `${fixLabel}: ` }), block.fix)) : null
          )
        )
      )
    );
  }

  function coachList(lines, tone) {
    return h("ul", { class: "coach-list" }, lines.map((line) => h("li", {}, h("span", { class: "dot", "data-tone": tone }), h("span", { text: line }))));
  }

  function coachGoals(lines) {
    return h("ol", { class: "coach-goals" }, lines.map((line, index) => h("li", {}, h("span", { class: "coach-goal-index num", text: String(index + 1) }), h("span", { text: line }))));
  }

  async function requestCoach(kind) {
    if (kind === "career") {
      await call("coachCareer");
      await loadCareer();
      return;
    }
    const matchId = state.matchId;
    await call("coachMatch", { matchId });
    await openMatchQuietly(matchId);
  }

  // Off: one compact row; the form opens in place.
  function aiOffCard(title) {
    const open = state.aiPanel === "form";
    const row = h(
      "div",
      { class: "ai-off" },
      h("div", { class: "ai-off-text" }, h("p", { class: "ai-off-title", text: t("aiOffTitle") }), h("p", { class: "muted small", text: t("aiOffHint") })),
      open ? null : h("button", { class: "btn btn-primary btn-sm", type: "button", onclick: () => toggleAiPanel(currentKind(), "form") }, h("span", { text: t("aiTurnOn") }))
    );
    return h("div", { class: "coach-card no-print" }, card(title, "graduation-cap", [row, aiPanel(currentKind())].filter(Boolean), h("span", { class: "tag", text: t("coachTag") })));
  }

  function currentKind() {
    return state.view === "progress" ? "career" : state.view === "settings" ? "settings" : "match";
  }

  // Settings → AI coach: the same key form as in the reviews, in one place.
  async function renderAiSettings({ load = false } = {}) {
    const root = document.getElementById("ai-settings-root");
    if (!root) {
      return;
    }
    if (load || !state.ai) {
      const result = await call("aiStatus");
      state.ai = result.ok ? result.data : state.ai;
    }
    const ai = state.ai || {};
    let body;
    if (state.aiPanel && state.view === "settings") {
      body = aiPanel("settings");
    } else if (ai.configured) {
      const note = h("p", { class: "ai-message", role: "status" });
      body = h(
        "div",
        { class: "ai-off" },
        h(
          "div",
          { class: "ai-off-text" },
          h("p", { class: "ai-off-title", text: t("aiOnTitle") }),
          h("p", { class: "muted small", text: t("aiCurrent", ai.provider_label || "", ai.model || "", ai.key_hint || "") }),
          ai.source === "env" ? h("p", { class: "muted small", text: t("aiEnvKey") }) : null,
          note
        ),
        h(
          "div",
          { class: "ai-panel-actions" },
          h(
            "button",
            {
              class: "btn btn-sm",
              type: "button",
              onclick: async (event) => {
                event.currentTarget.disabled = true;
                note.className = "ai-message muted";
                note.textContent = t("aiChecking");
                const check = await call("aiCheck");
                const code = check.ok ? (check.data.ok ? null : check.data.code) : "offline";
                note.className = `ai-message ${code ? "ai-message-bad" : "ai-message-ok"}`;
                note.textContent = code ? tOptional(`coachErrors.${code}`) || code : t("aiCheckOk");
                event.currentTarget.disabled = false;
              }
            },
            h("span", { text: t("aiCheckNow") })
          ),
          h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => toggleAiPanel("settings", "info") }, icon("settings"), h("span", { text: t("aiChangeKey") }))
        )
      );
    } else {
      body = h(
        "div",
        { class: "ai-off" },
        h("div", { class: "ai-off-text" }, h("p", { class: "ai-off-title", text: t("aiOffTitle") }), h("p", { class: "muted small", text: t("aiOffHint") })),
        h("button", { class: "btn btn-primary btn-sm", type: "button", onclick: () => toggleAiPanel("settings", "form") }, h("span", { text: t("aiTurnOn") }))
      );
    }
    const aiCard = card(t("aiSettingsTitle"), "graduation-cap", body);
    // Words the settings search finds it by (settings-search.js).
    aiCard.dataset.search = "ші ai тренер розбір ключ gemini groq openrouter key coach review";
    root.replaceChildren(aiCard);
    hydrate(root);
  }

  async function toggleAiPanel(kind, panel) {
    state.aiPanel = panel;
    state.aiMessage = null;
    if (panel && !state.ai) {
      const result = await call("aiStatus");
      state.ai = result.ok ? result.data : null;
    }
    rerender(kind);
  }

  function rerender(kind) {
    if (kind === "career") {
      renderCareer();
    } else if (kind === "settings") {
      renderAiSettings();
    } else {
      renderMatch();
    }
    const input = document.querySelector(".ai-form input[type='password']");
    if (state.aiPanel === "form" && input && !input.value) {
      input.focus();
    }
  }

  function aiPanel(kind) {
    if (!state.aiPanel) {
      return null;
    }
    const ai = state.ai || {};
    const message = state.aiMessage ? h("p", { class: `ai-message ai-message-${state.aiMessage.tone}`, role: "status", text: state.aiMessage.text }) : null;
    if (state.aiPanel === "info" && ai.configured) {
      return h(
        "div",
        { class: "ai-panel" },
        h("p", { class: "small", text: t("aiCurrent", ai.provider_label || "", ai.model || "", ai.key_hint || "") }),
        ai.source === "env" ? h("p", { class: "muted small", text: t("aiEnvKey") }) : null,
        message,
        h(
          "div",
          { class: "ai-panel-actions" },
          h("button", { class: "btn btn-sm", type: "button", onclick: () => toggleAiPanel(kind, "form") }, h("span", { text: t("aiChangeKey") })),
          ai.source === "app"
            ? h(
                "button",
                {
                  class: "btn btn-ghost btn-sm",
                  type: "button",
                  onclick: async () => {
                    const result = await call("aiClear");
                    state.ai = result.ok ? result.data : state.ai;
                    state.aiPanel = null;
                    await reloadAfterAi(kind);
                  }
                },
                h("span", { text: t("aiDisable") })
              )
            : null
        )
      );
    }
    return aiForm(kind, message);
  }

  function aiForm(kind, message) {
    const providers = state.ai?.providers || [
      { id: "gemini", label: "Gemini" },
      { id: "groq", label: "Groq" },
      { id: "openrouter", label: "OpenRouter" }
    ];
    let provider = state.ai?.provider && providers.some((p) => p.id === state.ai.provider) ? state.ai.provider : providers[0].id;
    const choice = h(
      "div",
      { class: "segmented segmented-sm", role: "radiogroup", "aria-label": t("aiService") },
      providers.map((item) =>
        h("button", {
          type: "button",
          role: "radio",
          "aria-checked": String(item.id === provider),
          text: item.label,
          onclick: (event) => {
            provider = item.id;
            modelInput.placeholder = `${defaultModel(provider)} (${t("aiModelHint")})`;
            for (const button of choice.querySelectorAll("button")) {
              button.setAttribute("aria-checked", String(button === event.currentTarget));
            }
          }
        })
      )
    );
    const input = h("input", { class: "input", type: "password", placeholder: t("aiKeyPlaceholder"), "aria-label": t("aiKey"), autocomplete: "off", spellcheck: "false" });
    const defaultModel = (id) => providers.find((p) => p.id === id)?.model || "";
    const modelInput = h("input", { class: "input", type: "text", placeholder: `${defaultModel(provider)} (${t("aiModelHint")})`, "aria-label": t("aiModel"), autocomplete: "off", spellcheck: "false" });
    const save = h("button", { class: "btn btn-primary btn-sm", type: "submit" }, h("span", { text: t("aiSave") }));
    const status = h("p", { class: "ai-message", role: "status" });
    const form = h(
      "form",
      {
        class: "ai-form",
        onsubmit: async (event) => {
          event.preventDefault();
          if (!input.value.trim()) {
            input.focus();
            return;
          }
          save.disabled = true;
          input.disabled = true;
          modelInput.disabled = true;
          status.className = "ai-message muted";
          status.textContent = t("aiChecking");
          const saved = await call("aiSave", { provider, apiKey: input.value, model: modelInput.value.trim() });
          if (!saved.ok) {
            save.disabled = false;
            input.disabled = false;
            modelInput.disabled = false;
            status.className = "ai-message ai-message-bad";
            status.textContent = saved.detail || t("coachErrors.bad_response");
            return;
          }
          state.ai = saved.data;
          const check = await call("aiCheck");
          const code = check.ok ? (check.data.ok ? null : check.data.code) : "offline";
          if (code === "invalid_key") {
            // A wrong key is not kept.
            const cleared = await call("aiClear");
            state.ai = cleared.ok ? cleared.data : state.ai;
            save.disabled = false;
            input.disabled = false;
            modelInput.disabled = false;
            status.className = "ai-message ai-message-bad";
            status.textContent = t("coachErrors.invalid_key");
            return;
          }
          state.aiPanel = code ? "info" : null;
          state.aiMessage = code ? { tone: "warn", text: t("aiSavedWarn", tOptional(`coachErrors.${code}`) || code) } : null;
          await reloadAfterAi(kind);
        }
      },
      h("div", { class: "ai-form-row" }, h("span", { class: "ai-label", text: t("aiService") }), choice),
      h("div", { class: "ai-form-row" }, input, save),
      h(
        "button",
        { class: "btn btn-ghost btn-sm ai-key-link", type: "button", onclick: () => api.openAiKeyPage?.(provider) },
        icon("external-link"),
        h("span", { text: t("aiGetKey") })
      ),
      // The model id is for people who know which one they want: folded away.
      h("details", { class: "ai-advanced" }, h("summary", { text: t("aiAdvanced") }), h("div", { class: "ai-form-row" }, h("span", { class: "ai-label", text: t("aiModel") }), modelInput)),
      status
    );
    if (message) {
      form.append(message);
    }
    return h(
      "div",
      { class: "ai-panel" },
      h("p", { class: "muted small", text: t("aiSetupHint") }),
      form,
      h("div", { class: "ai-panel-actions" }, h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => toggleAiPanel(kind, null) }, h("span", { text: t("aiCancel") })))
    );
  }

  async function reloadAfterAi(kind) {
    await refreshPlayer();
    if (kind === "settings") {
      await renderAiSettings({ load: true });
    } else if (kind === "career") {
      await loadCareer();
    } else if (state.matchId) {
      await openMatchQuietly(state.matchId);
      renderMatch();
    }
  }

  // --- progress -------------------------------------------------------------------

  // --- profile ----------------------------------------------------------------

  function profileContext() {
    return { view: state.view, locale: state.locale, accountId: state.player?.account_id ?? null, linked: Boolean(state.player?.linked) };
  }

  const profileRequests = window.WardlyProfileRequests.create({
    current: profileContext,
    prepare: async () => { if (!state.player) await refreshPlayer(); },
    request: ({ op = "profile", args } = {}) => call(op, args)
  });
  const friendsRequests = window.WardlyProfileRequests.create({
    current: profileContext,
    request: async request => {
      try { return await api.friends?.(request); }
      catch { return { ok: false, code: "offline" }; }
    }
  });

  function invalidateProfile({ clear = false } = {}) {
    profileRequests.cancel();
    friendsRequests.cancel();
    if (clear) {
      state.profile = null;
      state.friends = null;
    }
  }

  async function loadProfile() {
    const root = document.getElementById("profile-root");
    if (!state.profile && state.view === "profile") {
      root.replaceChildren(card(t("pfTitle"), "user", skeletonRows(4)));
    }
    return profileRequests.load(result => {
      if (!state.player || !state.player.linked) {
        root.replaceChildren(...(!state.player ? offlinePage("profile") : linkPage("profile")));
        hydrate(root);
        return;
      }
      if (result?.ok) state.profile = result.data.profile;
      renderProfile();
      loadFriends();
    });
  }

  // Friends arrive independently; an older response cannot replace this visit.
  function loadFriends(request = { op: "status" }) {
    return friendsRequests.load(result => {
      if (result) state.friends = result;
      const host = document.getElementById("pf-friends");
      if (host) {
        host.replaceWith(friendsCard());
        hydrate(document.getElementById("profile-root"));
      }
    }, request);
  }

  function renderProfile() {
    const root = document.getElementById("profile-root");
    const profile = state.profile;
    if (!root || state.view !== "profile") {
      return;
    }
    if (!profile) {
      root.replaceChildren(pageHead(t("pfTitle"), t("pfSub")), card(t("pfTitle"), "user", emptyState("user", t("pfTitle"), t("pfEmpty"))));
      hydrate(root);
      return;
    }
    root.replaceChildren(
      pageHead(t("pfTitle"), t("pfSub")),
      profileHeader(profile),
      twoColumns([ratingCard(profile.rating)], [statsCard(profile)]),
      zone(t("pfAchievements"), t("pfAchievementsHint"), [achievementsCard(profile.achievements || [])]),
      zone(t("pfFriends"), t("pfFriendsHint"), [friendsCard()]),
      zone(t("pfShop"), t("pfShopHint"), [shopCard(profile)])
    );
    hydrate(root);
    root.querySelectorAll("[data-chart='rating']").forEach((host) => drawRating(host, profile.rating));
  }

  function profileHeader(profile) {
    const player = profile.player || {};
    const level = profile.level || { level: 1, into: 0, need: 300 };
    // No Steam name yet (the account was linked by hand and OpenDota has not
    // answered): a plain «Player» and the person icon, never the app's name.
    const name = player.name || t("pfNoName");
    const initials = player.name ? h("span", { class: "pf-initials", text: name.trim().slice(0, 2).toUpperCase() }) : h("span", { class: "pf-initials" }, h("i", { "data-icon": "user", "data-size": "28", "aria-hidden": "true" }));
    const worn = profile.equipped || {};
    const shopItem = (id) => (profile.shop || []).find((item) => item.id === id);
    const avatar = h("div", { class: "pf-avatar" }, initials);
    if (player.avatar_url && /^https:\/\//.test(player.avatar_url)) {
      const img = h("img", { src: player.avatar_url, alt: "", referrerpolicy: "no-referrer" });
      img.addEventListener("error", () => img.remove());
      avatar.append(img);
    }
    const percent = Math.max(0, Math.min(100, Math.round((100 * level.into) / Math.max(1, level.need))));
    const title = worn.title && worn.title !== "title_none" ? shopItem(worn.title)?.name : null;
    return h(
      "section",
      { class: "card pf-header" },
      h("div", { class: `pf-banner cos-${worn.banner || "banner_plain"}`, "aria-hidden": "true" }),
      h(
        "div",
        { class: "pf-identity" },
        h("div", { class: `pf-avatar-wrap cos-${worn.frame || "frame_plain"}` }, avatar),
        h(
          "div",
          { class: "pf-name-block" },
          h("p", { class: `pf-name cos-${worn.name || "name_plain"}`, text: name }),
          title ? h("p", { class: `pf-title cos-${worn.title}`, text: title }) : null,
          h(
            "p",
            { class: "pf-meta" },
            h("span", { class: "pf-level", text: t("pfLevel", level.level) }),
            player.rank_label ? h("span", { class: "pf-rank", text: player.rank_label }) : null
          ),
          h(
            "div",
            { class: "pf-xp", title: t("pfXp", level.into, level.need) },
            h("div", { class: "pf-xp-bar" }, h("span", { style: `width: ${percent}%` })),
            h("span", { class: "pf-xp-text muted", text: t("pfXp", level.into, level.need) })
          )
        ),
        h(
          "div",
          { class: "pf-sparks", title: t("pfSparksHint") },
          icon("sparkles"),
          h("span", { class: "pf-sparks-value", text: String(profile.sparks?.balance ?? 0) }),
          h("span", { class: "pf-sparks-label", text: t("pfSparks") })
        )
      )
    );
  }

  function statsCard(profile) {
    const stats = profile.stats || {};
    return card(
      t("pfWithApp"),
      "trophy",
      [
        h(
          "div",
          { class: "tiles tiles-compact" },
          tile(t("pfGames"), String(stats.app_games ?? 0)),
          tile(t("pfWinrate"), stats.app_winrate === null || stats.app_winrate === undefined ? "—" : `${stats.app_winrate}%`),
          tile(t("pfHours"), hoursText(stats.app_hours))
        ),
        nextBadge(profile.achievements || [])
      ]
    );
  }

  // The unfinished award closest to its next tier, so the side column says
  // what to play for next.
  function nextBadge(list) {
    const open = list.filter((badge) => !badge.done && badge.target > 0);
    if (!open.length) {
      return null;
    }
    const share = (badge) => badge.value / badge.target;
    const next = open.reduce((best, badge) => (share(badge) > share(best) ? badge : best));
    return h("div", { class: "pf-next" }, h("p", { class: "pf-next-label", text: t("pfNextBadge") }), h("ul", { class: "pf-badges pf-badges-one" }, badgeItem(next)));
  }

  // 0 → «0», 2.5 → «2,5», 37.4 → «37».
  function hoursText(value) {
    const hours = Number(value) || 0;
    if (hours <= 0) {
      return "0";
    }
    return hours >= 10 ? number(Math.round(hours)) : decimal(hours);
  }

  function ratingCard(rating) {
    const form = h(
      "form",
      { class: "pf-mmr-form no-print" },
      h("label", { class: "pf-mmr-label", for: "pf-mmr", text: t("pfMmrLabel") }),
      h("input", { id: "pf-mmr", class: "input", type: "number", min: "0", max: "15000", step: "1", inputmode: "numeric", placeholder: t("pfMmrPlaceholder") }),
      h("button", { class: "btn", type: "submit", text: t("pfMmrSave") }),
      rating && rating.source === "manual" ? h("button", { class: "btn btn-ghost", type: "button", "data-mmr-clear": "1", text: t("pfMmrClear") }) : null,
      h("p", { class: "pf-mmr-error muted", role: "status", "aria-live": "polite" })
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = form.querySelector("input");
      const value = Number.parseInt(input.value, 10);
      const error = form.querySelector(".pf-mmr-error");
      if (!Number.isFinite(value) || value < 0 || value > 15000) {
        error.textContent = t("pfMmrBad");
        return;
      }
      await profileRequests.load(result => {
        if (result?.ok) {
          state.profile = result.data.profile;
          renderProfile();
        } else {
          error.textContent = t("pfMmrBad");
        }
      }, { op: "profileMmr", args: { mmr: value } });
    });
    form.querySelector("[data-mmr-clear]")?.addEventListener("click", async () => {
      await profileRequests.load(result => {
        if (result?.ok) {
          state.profile = result.data.profile;
          renderProfile();
        }
      }, { op: "profileMmrClear" });
    });
    if (!rating) {
      return card(t("pfRating"), "chart-line", [h("p", { class: "muted", text: t("pfRatingNone") }), form]);
    }
    const change = rating.change_20 || 0;
    const sign = change > 0 ? "+" : "";
    const head = h(
      "div",
      { class: "pf-rating-head" },
      h("div", { class: "pf-rating-now" }, h("span", { class: "pf-rating-label muted", text: t("pfNow") }), h("span", { class: "pf-rating-value", text: `≈ ${number(rating.current)}` })),
      h(
        "div",
        { class: "pf-rating-side" },
        h("span", { class: `pf-rating-change ${change > 0 ? "up" : change < 0 ? "down" : ""}`, text: `${sign}${change}` }),
        h("span", { class: "muted", text: `${t("pfLast20")} · ${t("pfRecord", rating.wins_20, rating.losses_20)}` }),
        h("span", { class: "muted", text: `${t("pfPeak")} ${number(rating.peak)}` })
      )
    );
    const note = rating.source === "medal" ? t("pfRatingMedal") : t("pfRatingManual", rating.step);
    return card(t("pfRating"), "chart-line", [head, h("div", { class: "chart-host pf-rating-chart", "data-chart": "rating" }), h("p", { class: "muted small", text: note }), form]);
  }

  function drawRating(host, rating) {
    if (!rating || !window.LauncherCharts?.rating) {
      return;
    }
    const dateFormat = { day: "numeric", month: "short" };
    const points = rating.points.map((point) => {
      const date = point.t ? new Date(point.t * 1000).toLocaleDateString(state.locale === "uk" ? "uk-UA" : "en-GB", dateFormat) : "";
      const hero = point.hero_id ? window.DotaIcons?.hero(point.hero_id)?.name : null;
      const what = point.anchor ? t("pfAnchor") : point.win ? t("pfWin") : t("pfLoss");
      return { ...point, title: date, detail: [what, hero].filter(Boolean).join(" · ") };
    });
    window.LauncherCharts.rating(host, { points, ariaLabel: t("pfRating") });
  }

  // «Друзі»: the own code (or the button that shows the profile), the add form
  // and the leaderboard of the player and the friends.
  function friendsCard() {
    const data = state.friends;
    const note = h("p", { class: "pf-friends-note muted", role: "status", "aria-live": "polite" });
    const errorText = (code) => tOptional(`pfFriendsErrors.${code}`) || code;
    if (data?.addError) {
      note.textContent = errorText(data.addError);
    } else if (data?.error) {
      note.textContent = errorText(data.error);
    }
    const parts = [];
    if (!data) {
      parts.push(skeletonRows(2));
    } else if (!data.enabled) {
      parts.push(
        h("p", { class: "muted", text: t("pfFriendsOff") }),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => loadFriends({ op: "enable" }) }, icon("users"), h("span", { text: t("pfFriendsShow") }))
      );
    } else {
      const copied = (what) => async () => {
        await api.friends({ op: "copy", what });
        note.textContent = t("pfFriendsCopied");
      };
      parts.push(
        h(
          "div",
          { class: "pf-code-row" },
          h("div", {}, h("p", { class: "muted small", text: t("pfFriendsCode") }), h("p", { class: "pf-code", text: data.code || "—" })),
          h(
            "div",
            { class: "pf-code-actions" },
            h("button", { class: "btn", type: "button", onclick: copied("code") }, icon("copy"), h("span", { text: t("pfFriendsCopy") })),
            data.url ? h("button", { class: "btn btn-ghost", type: "button", onclick: copied("link") }, icon("link"), h("span", { text: t("pfFriendsCopyLink") })) : null,
            data.url ? h("button", { class: "btn btn-ghost", type: "button", onclick: () => api.friends({ op: "open" }) }, icon("external-link"), h("span", { text: t("pfFriendsOpen") })) : null
          )
        ),
        h(
          "label",
          { class: "pf-check" },
          h("input", { type: "checkbox", class: "switch", role: "switch", checked: data.showMmr ? true : null, onchange: (event) => loadFriends({ op: "showMmr", value: event.target.checked }) }),
          h("span", { text: t("pfFriendsShowMmr") })
        )
      );
    }
    const input = h("input", { class: "input", type: "text", maxlength: "20", spellcheck: "false", autocomplete: "off", placeholder: t("pfFriendsAddPlaceholder"), "aria-label": t("pfFriendsAddPlaceholder") });
    const form = h("form", { class: "pf-add-form" }, input, h("button", { class: "btn", type: "submit", text: t("pfFriendsAdd") }));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (input.value.trim()) {
        loadFriends({ op: "add", code: input.value.trim() });
      }
    });
    parts.push(form);
    const rows = data?.rows || [];
    if (data && rows.filter((row) => !row.me).length === 0) {
      parts.push(h("p", { class: "muted", text: t("pfFriendsEmpty") }));
    }
    if (rows.length) {
      parts.push(h("ol", { class: "pf-board" }, rows.map((row) => boardRow(row))));
    }
    if (data?.missing?.length) {
      parts.push(h("p", { class: "muted small", text: t("pfFriendsMissing", data.missing.join(", ")) }));
    }
    parts.push(note);
    if (data?.enabled) {
      parts.push(h("button", { class: "btn btn-ghost btn-sm pf-hide", type: "button", text: t("pfFriendsHide"), onclick: () => loadFriends({ op: "disable" }) }));
    }
    return h("section", { class: "card", id: "pf-friends" }, h("div", { class: "card-body pf-friends" }, parts));
  }

  // A friend's Steam avatar from its image hash (the card keeps nothing else of it).
  function friendAvatar(hash, initials) {
    const avatar = h("div", { class: "pf-avatar" }, h("span", { class: "pf-initials small", text: initials }));
    if (/^[0-9a-f]{40}$/.test(String(hash || ""))) {
      const img = h("img", { src: `https://avatars.steamstatic.com/${hash}_full.jpg`, alt: "", referrerpolicy: "no-referrer" });
      img.addEventListener("error", () => img.remove());
      avatar.append(img);
    }
    return avatar;
  }

  function boardRow(row) {
    const card = row.card || {};
    const worn = card.equipped || {};
    const initials = String(card.name || "?").trim().slice(0, 2).toUpperCase();
    const meta = [t("pfLevel", card.level || 1), card.rank_label, Number.isFinite(card.mmr) ? `≈ ${number(card.mmr)}` : null, t("pfFriendsWeek", card.stats?.week_games || 0)].filter(Boolean).join(" · ");
    return h(
      "li",
      { class: `pf-board-row${row.me ? " me" : ""}` },
      h("span", { class: "pf-place", text: String(row.place) }),
      h("div", { class: `pf-avatar-wrap mini cos-${worn.frame || "frame_plain"}` }, friendAvatar(card.avatar, initials)),
      h(
        "div",
        { class: "pf-board-who" },
        h("p", {}, h("span", { class: `pf-name mini cos-${worn.name || "name_plain"}`, text: card.name || "—" }), row.me ? h("span", { class: "pf-you", text: t("pfFriendsYou") }) : null),
        card.title ? h("p", { class: `pf-title cos-${worn.title || ""}`, text: card.title }) : null,
        h("p", { class: "muted small", text: meta })
      ),
      row.me
        ? null
        : h("button", { class: "btn btn-ghost btn-sm", type: "button", text: t("pfFriendsRemove"), onclick: () => loadFriends({ op: "remove", code: row.id }) })
    );
  }

  // The shop: every look by kind with a preview, its price or condition and
  // one button (buy, wear, or worn).
  function shopCard(profile) {
    const badges = Object.fromEntries((profile.achievements || []).map((badge) => [badge.id, badge.title]));
    const message = h("p", { class: "pf-shop-message muted", role: "status", "aria-live": "polite" });
    const act = async (op, id) => {
      await profileRequests.load(result => {
        if (result?.ok) {
          state.profile = result.data.profile;
          renderProfile();
        } else {
          message.textContent = tOptional(`pfShopErrors.${result?.code}`) || "";
        }
      }, { op, args: { id } });
    };
    const groups = ["frame", "banner", "name", "title"].map((kind) => {
      const items = (profile.shop || []).filter((item) => item.kind === kind);
      return h(
        "section",
        { class: "pf-shop-group" },
        h("h3", { class: "pf-shop-kind", text: t(`pfKinds.${kind}`) }),
        h(
          "ul",
          { class: "pf-shop-items" },
          items.map((item) => {
            let condition = null;
            if (!item.owned && item.locked === "level") {
              condition = t("pfNeedLevel", item.level);
            } else if (!item.owned && item.locked === "achievement" && item.achievement) {
              condition = t("pfNeedAchievement", badges[item.achievement.id] || item.achievement.id, item.achievement.tier);
            }
            let button;
            if (item.equipped) {
              button = h("button", { class: "btn btn-sm", type: "button", disabled: true, text: t("pfWorn") });
            } else if (item.owned) {
              button = h("button", { class: "btn btn-sm", type: "button", text: t("pfWear"), onclick: () => act("shopEquip", item.id) });
            } else if (item.locked) {
              // Closed by a level or an achievement: a lock with the price, not a «Buy» that does nothing.
              button = h(
                "button",
                { class: "btn btn-sm pf-shop-closed", type: "button", disabled: true, title: t("pfLockedHint") },
                icon("lock"),
                h("span", { text: item.price ? String(item.price) : t("pfFree") })
              );
            } else if (!item.affordable) {
              // How many sparks are missing, instead of a dimmed «Buy».
              const missing = Math.max(1, (item.price || 0) - (profile.sparks?.balance ?? 0));
              button = h("button", { class: "btn btn-sm pf-shop-closed", type: "button", disabled: true, text: t("pfNeedSparks", missing) });
            } else {
              button = h("button", {
                class: "btn btn-sm btn-primary",
                type: "button",
                text: item.price ? t("pfBuy", item.price) : t("pfFree"),
                onclick: () => act("shopBuy", item.id)
              });
            }
            return h(
              "li",
              { class: `pf-shop-item${item.equipped ? " worn" : ""}${item.locked && !item.owned ? " locked" : ""}` },
              shopPreview(item, profile),
              h("p", { class: "pf-shop-name", text: item.name }),
              condition ? h("p", { class: "pf-shop-condition muted", text: condition }) : null,
              button
            );
          })
        )
      );
    });
    return h("section", { class: "card" }, h("div", { class: "card-body pf-shop" }, groups, message));
  }

  function shopPreview(item, profile) {
    const cls = `cos-${item.id}`;
    if (item.kind === "frame") {
      return h("div", { class: "pf-preview" }, h("div", { class: `pf-avatar-wrap mini ${cls}` }, h("div", { class: "pf-avatar" })));
    }
    if (item.kind === "banner") {
      return h("div", { class: `pf-preview pf-banner mini ${cls}` });
    }
    if (item.kind === "name") {
      return h("div", { class: "pf-preview" }, h("span", { class: `pf-name mini ${cls}`, text: profile.player?.name || t("pfNoName") }));
    }
    return h("div", { class: "pf-preview" }, h("span", { class: `pf-title ${cls}`, text: item.id === "title_none" ? "—" : item.name }));
  }

  function achievementsCard(list) {
    // Alone under the «Нагороди» zone heading: no second title on the card.
    return h(
      "section",
      { class: "card" },
      h("div", { class: "card-body" }, h(
        "ul",
        { class: "pf-badges" },
        list.map(badgeItem)
      )
      )
    );
  }

  function badgeItem(badge) {
    const percent = badge.done ? 100 : Math.max(0, Math.min(100, Math.round((100 * badge.value) / Math.max(1, badge.target))));
    return h(
      "li",
      { class: `pf-badge tier-${badge.tier}${badge.done ? " done" : ""}` },
      // No tier yet: an empty medal slot with a dim cup, not a stray dot.
      h("div", { class: "pf-badge-medal", "aria-hidden": "true" }, badge.tier ? h("span", { text: String(badge.tier) }) : icon("trophy")),
      h(
        "div",
        { class: "pf-badge-body" },
        h("p", { class: "pf-badge-title", text: badge.title }),
        h("p", { class: "pf-badge-tier muted", text: badge.tier ? t("pfTier", badge.tier_name, badge.tier, badge.tiers) : t("pfTierNone") }),
        h("p", { class: "pf-badge-text", text: badge.done ? t("pfDone") : badge.text }),
        badge.done
          ? null
          : h(
              "div",
              { class: "pf-badge-progress" },
              h("div", { class: "pf-xp-bar" }, h("span", { style: `width: ${percent}%` })),
              h("span", { class: "muted", text: t("pfProgress", badge.value, badge.target) }),
              badge.reward ? h("span", { class: "pf-badge-reward", text: t("pfReward", badge.reward) }) : null
            )
      )
    );
  }

  const careerRequests = window.WardlyCareerRequests.create({
    current: () => ({
      view: state.view, heroId: state.careerHero, locale: state.locale,
      accountId: state.player?.account_id ?? null, linked: Boolean(state.player?.linked)
    }),
    prepare: async () => { if (!state.player) await refreshPlayer(); },
    request: args => call("career", args)
  });

  async function loadCareer() {
    if (state.view !== "progress") return false;
    clearTimeout(careerRefreshTimer);
    const root = document.getElementById("progress-root");
    if (!state.career) {
      root.replaceChildren(card(t("tiles.winrate"), "chart-line", skeletonRows(4)));
    }
    return careerRequests.load(result => {
      if (!state.player) {
        root.replaceChildren(...offlinePage("progress"));
        hydrate(root);
      } else if (!state.player.linked) {
        root.replaceChildren(...linkPage("progress"));
        hydrate(root);
      } else {
        if (result?.ok) state.career = result.data;
        renderCareer();
        scheduleCareerRefresh();
      }
    });
  }

  let careerRefreshTimer = null;

  // While the coach writes the career review, ask again every few seconds.
  function scheduleCareerRefresh() {
    clearTimeout(careerRefreshTimer);
    if (state.career?.coach?.state !== "pending" || state.view !== "progress") {
      return;
    }
    careerRefreshTimer = setTimeout(async () => {
      if (state.view !== "progress") {
        return;
      }
      await careerRequests.load(result => {
        if (result?.ok) {
          const changed = JSON.stringify(result.data) !== JSON.stringify(state.career);
          state.career = result.data;
          if (changed && state.aiPanel !== "form") renderCareer();
        }
        scheduleCareerRefresh();
      });
    }, 4000);
  }

  function trendDelta(trend, key, format = (v) => v) {
    const item = trend && trend[key];
    if (!item || item.delta === null || item.delta === undefined || !trend.enough) {
      return null;
    }
    const tone = item.better === true ? "good" : item.better === false ? "bad" : "idle";
    const iconName = item.direction === "up" ? "trending-up" : item.direction === "down" ? "trending-down" : "minus";
    const sign = item.delta > 0 ? "+" : "";
    return h("span", { class: `delta delta-${tone}` }, icon(iconName), h("span", { class: "num", text: `${sign}${format(item.delta)}` }), h("span", { class: "muted", text: ` ${t("vsPrevious", trend.window)}` }));
  }

  function tile(label, value, delta, sub, extra) {
    return h("div", { class: "tile" }, h("p", { class: "tile-label", text: label }), h("p", { class: "tile-value", text: value }), delta || null, sub ? h("p", { class: "tile-sub muted", text: sub }) : null, extra || null);
  }

  // A tile's last matches at a glance (oldest left): a thin line of the values
  // the series has, the newest as a dot; decoration, the numbers stay above.
  function sparkline(values) {
    const points = values.map((value, index) => [index, value]).filter(([, value]) => Number.isFinite(value));
    if (points.length < 3) {
      return null;
    }
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "spark");
    svg.setAttribute("viewBox", "0 0 100 24");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    const low = Math.min(...points.map(([, v]) => v));
    const high = Math.max(...points.map(([, v]) => v));
    const span = high - low || 1;
    // Spread over the whole tile: games without the number are skipped, so
    // every tile's line has the same width.
    const xy = points.map(([, v], k) => [(k / (points.length - 1)) * 100, 21 - ((v - low) / span) * 18]);
    const coords = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const area = document.createElementNS(NS, "polygon");
    area.setAttribute("points", `${xy[0][0].toFixed(1)},24 ${coords} ${xy[xy.length - 1][0].toFixed(1)},24`);
    area.setAttribute("class", "spark-area");
    const line = document.createElementNS(NS, "polyline");
    line.setAttribute("points", coords);
    line.setAttribute("class", "spark-line");
    svg.append(area, line);
    return h("div", { class: "spark-wrap" }, svg);
  }

  // Wins and losses of the last matches as small marks, oldest left.
  function resultStrip(series) {
    const known = series.filter((match) => match.win === true || match.win === false);
    if (known.length < 3) {
      return null;
    }
    return h("div", { class: "result-strip", "aria-hidden": "true" }, known.map((match) => h("span", { dataset: { win: String(match.win) } })));
  }

  // "All heroes" or one hero for the whole Progress page.
  function careerHeroSelect(career) {
    const heroes = career.hero_choices || [];
    if (heroes.length < 2 && state.careerHero === null) {
      return null;
    }
    const select = h(
      "select",
      {
        class: "input select",
        "aria-label": t("filterHero"),
        onchange: async (event) => {
          state.careerHero = event.target.value === "" ? null : Number(event.target.value);
          await loadCareer();
        }
      },
      h("option", { value: "", text: t("filterAllHeroes") }),
      heroes.map((hero) => {
        const option = h("option", { value: String(hero.hero_id), text: `${hero.hero || "—"} · ${hero.games}` });
        option.selected = state.careerHero === hero.hero_id;
        return option;
      })
    );
    return select;
  }

  async function setGoal(findingId, button) {
    if (button) {
      button.disabled = true;
    }
    const result = await call("focusSet", { findingId });
    if (result.ok && state.career) {
      state.career = { ...state.career, focus: result.data };
      renderCareer();
    } else if (button) {
      button.disabled = false;
    }
  }

  async function clearGoal() {
    const result = await call("focusClear");
    if (result.ok && state.career) {
      state.career = { ...state.career, focus: null };
      renderCareer();
    }
  }

  // «Goals» at the top of Progress: the focus (or the most repeated problem to
  // make one) and the streak goals of the status (app/player_goals.py).
  function goalsCard(career) {
    const left = career.focus ? goalBody(career.focus) : noFocusBody(career);
    const goals = ((state.status && state.status.player && state.status.player.goals) || []).filter((goal) => GOAL_TEXT[goal.id]);
    const streaks = goals.length
      ? h(
          "div",
          { class: "streaks" },
          h("p", { class: "friend-sub", text: t("streaksTitle") }),
          goals.map((goal) =>
            h(
              "div",
              { class: "streak", dataset: { met: String(Boolean(goal.met)) } },
              h("p", { class: "streak-head" }, h("span", { text: t(GOAL_TEXT[goal.id], goal.target) }), h("span", { class: "num muted", text: goal.met ? t("streakMet", goal.current) : t("streakProgress", goal.current, goal.target) })),
              h("span", { class: "streak-bar", role: "img", "aria-label": t("streakProgress", goal.current, goal.target) }, h("span", { style: `width: ${Math.min(100, Math.round((100 * goal.current) / goal.target))}%` })),
              h("p", { class: "muted small", text: t("streakBest", goal.best) })
            )
          )
        )
      : null;
    return card(t("goalsTitle"), "target", h("div", { class: "goals-grid" }, left, streaks));
  }

  function noFocusBody(career) {
    // The most repeated problem with a drill: one click makes it the focus.
    const top = (career.recurring || []).find((item) => item.id && item.drill);
    return h(
      "div",
      { class: "goal" },
      h("p", { class: "friend-sub", text: t("goalTitle") }),
      h("p", { class: "muted small", text: t("summaryNoFocus") }),
      top
        ? h(
            "button",
            { type: "button", class: "btn btn-sm goal-make no-print", onclick: (event) => setGoal(top.id, event.currentTarget) },
            icon("target"),
            h("span", { text: t("goalMakeTop", top.title) })
          )
        : null,
      explain("explainFocus")
    );
  }

  // The problem the player chose to work on and how the matches since went.
  function goalBody(focus) {
    const since = focus.since ? new Date(focus.since).toLocaleDateString(state.locale === "uk" ? "uk-UA" : "en-GB", { day: "numeric", month: "long" }) : "";
    const marks = (focus.results || []).map((result) =>
      h("button", {
        class: "goal-mark",
        type: "button",
        dataset: { met: String(result.met) },
        title: `${result.hero || "—"}: ${result.met ? t("goalMet") : t("goalMissed")}`,
        "aria-label": `${result.hero || "—"}: ${result.met ? t("goalMet") : t("goalMissed")}`,
        onclick: () => openMatch(result.match_id)
      })
    );
    const progress = focus.total
      ? [t("goalProgress", focus.met, focus.total), focus.streak >= 2 ? t("goalStreak", focus.streak) : null].filter(Boolean).join(" · ")
      : t("goalWaiting");
    return h(
        "div",
        { class: "goal" },
        h("p", { class: "friend-sub", text: t("goalTitle") }),
        h("p", { class: "finding-title" }, h("span", { text: focus.title }), focus.section_label ? h("span", { class: "tag", text: focus.section_label }) : null),
        focus.drill ? h("p", { class: "finding-drill" }, icon("lightbulb"), h("span", {}, h("strong", { text: `${t("drill")}: ` }), focus.drill)) : null,
        marks.length ? h("div", { class: "goal-marks" }, marks) : null,
        h("p", { class: "muted small num", text: since ? `${progress} · ${t("goalSince", since)}` : progress }),
        h("div", { class: "row no-print" }, h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: clearGoal }, h("span", { text: t("goalClear") }))),
        explain("explainFocus")
      );
  }

  function renderCareer() {
    const root = document.getElementById("progress-root");
    const career = state.career;
    if (!career || !career.matches) {
      root.replaceChildren(
        pageHead(t("progressTitle"), t("progressSub")),
        h("section", { class: "card" }, h("div", { class: "card-body" }, emptyState("chart-line", t("progressEmptyTitle"), t("progressEmptyHint")), linkPerks("progress", "progressSoon"))),
        (career && coachCard(career.coach, "career")) || ""
      );
      hydrate(root);
      return;
    }
    const avg = career.averages || {};
    const trend = career.trend || {};
    const series = career.series || [];
    const streak = career.streak;
    const streakText = streak && streak.length >= 2 ? (streak.win ? t("streakWin", streak.length) : t("streakLoss", streak.length)) : null;
    const tiles = h(
      "div",
      { class: "tiles" },
      tile(t("tiles.winrate"), career.winrate == null ? "—" : `${career.winrate}%`, trendDelta(trend, "winrate", (v) => `${Math.round(v)}%`), streakText || t("recordLine", career.wins, career.losses, career.matches), resultStrip(series)),
      tile(t("tiles.kda"), decimal(avg.kda), trendDelta(trend, "kda", (v) => decimal(v))),
      tile(t("tiles.gpm"), number(avg.gpm), trendDelta(trend, "gpm", (v) => Math.round(v)), null, sparkline(series.map((match) => match.gpm))),
      tile(t("tiles.lh10"), number(avg.lh_10), trendDelta(trend, "lh_10", (v) => Math.round(v)), null, sparkline(series.map((match) => match.lh_10))),
      tile(t("tiles.score"), avg.score == null ? "—" : String(Math.round(avg.score)), trendDelta(trend, "score", (v) => Math.round(v)), null, sparkline(series.map((match) => match.score)))
    );

    const chartHost = h("div", { class: "chart-host", dataset: { chart: "career" } });
    const scoreCard = card(
      t("scoreChartTitle"),
      "chart-line",
      h(
        "div",
        {},
        h("p", { class: "muted small chart-note", text: t("scoreChartHint") }),
        careerBasisNote(career.basis),
        chartHost,
        h(
          "ul",
          { class: "chart-legend" },
          h("li", {}, h("span", { class: "chart-key chart-key-dot", style: "--key: var(--ok)" }), h("span", { text: t("winKey") })),
          h("li", {}, h("span", { class: "chart-key chart-key-dot", style: "--key: var(--error)" }), h("span", { text: t("lossKey") }))
        )
      )
    );

    const plan = career.focus_plan || [];
    const planCard = card(
      t("planTitle"),
      "target",
      plan.length
        ? h(
            "div",
            {},
            h("p", { class: "muted small", text: t("planHint") }),
            h(
              "ol",
              { class: "findings" },
              plan.map((item, index) =>
                h(
                  "li",
                  { class: "finding finding-improve" },
                  h("span", { class: "finding-index num", text: String(index + 1) }),
                  h(
                    "div",
                    { class: "finding-body" },
                    h(
                      "p",
                      { class: "finding-title" },
                      h("span", { text: item.title }),
                      item.section_label ? h("span", { class: "tag", text: item.section_label }) : null,
                      career.focus && career.focus.id === item.id ? h("span", { class: "tag tag-accent", text: t("goalCurrent") }) : null
                    ),
                    h("div", { class: "share" }, window.LauncherCharts.meter(item.share, item.share >= 50 ? "bad" : "ok"), h("span", { class: "muted small", text: item.text })),
                    item.drill ? h("p", { class: "finding-drill" }, icon("lightbulb"), h("span", {}, h("strong", { text: `${t("drill")}: ` }), item.drill)) : null,
                    career.focus && career.focus.id === item.id
                      ? null
                      : h(
                          "button",
                          { class: "btn btn-ghost btn-sm goal-set no-print", type: "button", onclick: (event) => setGoal(item.id, event.currentTarget) },
                          icon("target"),
                          h("span", { text: t("goalSet") })
                        )
                  )
                )
              )
            )
          )
        : h("p", { class: "muted", text: t("planEmpty") })
    );

    const strengths = career.recurring_strengths || [];
    const strengthsCard = strengths.length
      ? card(
          t("strengthsRecurring"),
          "sparkles",
          h(
            "ul",
            { class: "findings findings-compact" },
            strengths.map((item) =>
              h("li", { class: "finding finding-strength" }, h("span", { class: "dot", "data-tone": "good" }), h("div", { class: "finding-body" }, h("p", { class: "finding-title", text: item.title }), h("p", { class: "finding-text muted", text: item.text })))
            )
          )
        )
      : null;

    const heroes = career.heroes || [];
    const heroesCard = heroes.length
      ? card(
          t("heroesTitle"),
          "user",
          h(
            "div",
            { class: "table-wrap" },
            h(
              "table",
              // Headers wrap («На вашому / ранзі»): seven columns fit the main column without a sideways scroll.
              { class: "table table-wrapping" },
              h("thead", {}, h("tr", {}, h("th", { text: t("colHero") }), h("th", { class: "num-col", text: t("colMatches") }), h("th", { class: "num-col", text: t("colWinrate") }), h("th", { class: "num-col", text: t("colBracket"), title: career.rank_bracket_label ? t("bracketHint", career.rank_bracket_label) : "" }), h("th", { class: "num-col hide-narrow", text: "KDA" }), h("th", { class: "num-col hide-narrow", text: t("colGpm") }), h("th", { class: "num-col", text: t("colScore") }))),
              h(
                "tbody",
                {},
                heroes.map((hero) =>
                  h(
                    "tr",
                    {},
                    h("td", {}, heroLabel(hero.hero_id || hero.hero, hero.hero)),
                    h("td", { class: "num-col num", text: String(hero.matches) }),
                    h("td", { class: "num-col num", text: hero.winrate == null ? "—" : `${hero.winrate}%` }),
                    h("td", { class: "num-col num muted", text: hero.bracket_winrate == null ? "—" : percent1(hero.bracket_winrate) }),
                    h("td", { class: "num-col num hide-narrow", text: decimal(hero.kda) }),
                    h("td", { class: "num-col num hide-narrow", text: number(hero.gpm) }),
                    h("td", { class: "num-col num", text: hero.score == null ? "—" : String(Math.round(hero.score)) })
                  )
                )
              )
            )
          )
        )
      : null;

    const sharePanel = h("section", { class: "card share-panel no-print", hidden: true });
    const head = pageHead(t("progressTitle"), t("analyzed", career.analyzed, career.matches), [
      careerHeroSelect(career),
      // Progress over all heroes only: that is what the page shows.
      state.careerHero === null && career.analyzed ? shareButton(sharePanel, career, "progress") : null,
      pdfButton("career")
    ].filter(Boolean));
    root.replaceChildren(
      head,
      sharePanel,
      zone(t("zoneSummary"), t("zoneSummaryHint"), [tiles], { id: "summary", label: t("navSummary") }),
      zone(t("zoneGoals"), t("zoneGoalsHint"), [goalsCard(career)], { id: "goals", label: t("navGoals") }),
      twoColumns(
        [
          zone(t("zoneCoach"), t("zoneCoachHint"), [
            coachCard(career.coach, "career"),
            planCard,
            // Asking needs at least one review (the backend answers not_enough without one).
            state.careerHero === null && career.analyzed ? askCard(career, true) : null,
            state.careerHero === null ? adviceMarksCard(career.advice_feedback) : null
          ], { id: "coach", label: t("navCoach") }),
          zone(t("zoneGames"), t("zoneGamesHint"), [
            scoreCard,
            deathMapCard(career.death_map),
            lanesCard(career.lanes),
            heroesCard,
            state.careerHero === null ? heroPoolCard(career.hero_pool) : null,
            strengthsCard
          ], { id: "games", label: t("navGames") })
        ].filter(Boolean),
        [
          zone(t("zoneCompare"), t("zoneCompareHint"), [
            careerRankCard(career),
            state.careerHero === null ? rankHistoryCard(career.rank_history) : null,
            opponentsCard(career.opponents),
            state.careerHero === null ? friendCard() : null
          ], { id: "compare", label: t("navCompare") }),
          zone(t("zoneHero"), t("zoneHeroHint"), [selfCompareCard(career.self_compare), heroBuildCard(career.hero_build)], { id: "hero", label: t("navHero") })
        ].filter(Boolean)
      )
    );
    // A sticky bar with the zone links under the title; once the title has
    // scrolled away it names the page.
    const nav = sectionNav(root);
    if (nav) {
      const bar = h("div", { class: "page-toolbar no-print" }, h("span", { class: "page-toolbar-title", text: t("progressTitle") }), nav);
      head.after(bar);
      stickToolbar(bar, head);
    }
    watchSections(nav);
    hydrate(root);
    const careerMap = root.querySelector('[data-chart="career-map"]');
    if (careerMap) {
      drawCareerMap(careerMap, career.death_map);
    }
    const itemTrend = root.querySelector('[data-chart="item-trend"]');
    if (itemTrend) {
      drawItemTrend(itemTrend, career.hero_build.timing_trend);
    }
    const items = (career.series || []).map((match) => ({
      label: String(match.match_id),
      value: match.score,
      color: TONE_COLORS[scoreTone(match.score)],
      title: `${match.hero || "—"} · ${match.win === true ? t("win") : match.win === false ? t("loss") : "—"}`,
      detail: relativeTime(match.start_time),
      key: match.win === true ? "win" : match.win === false ? "loss" : null,
      matchId: match.match_id
    }));
    window.LauncherCharts.columns(chartHost, {
      items,
      yMax: 100,
      color: VIZ_1,
      valueLabel: t("scoreLabel"),
      ariaLabel: t("scoreChartTitle"),
      onSelect: (item) => openMatch(item.matchId)
    });
  }

  // --- home: the summary (app/home_summary.py) -------------------------------------------

  // Tilt warning and streak goals (app/player_goals.py) inside the summary.
  const GOAL_TEXT = { few_deaths: "streakFewDeaths", good_score: "streakGoodScore" };
  const SUMMARY_REFRESH_MS = 60 * 1000;

  async function refreshSummary(status) {
    const review = status.player && status.player.lastReview;
    const today = status.player && status.player.today;
    const key = [state.locale, review ? `${review.match_id}|${review.at}` : "", status.player && status.player.accountId, today ? today.games : 0].join("|");
    if (state.summaryKey === key && Date.now() - (state.summaryAt || 0) < SUMMARY_REFRESH_MS) {
      return;
    }
    state.summaryKey = key;
    state.summaryAt = Date.now();
    const result = await call("summary");
    renderSummary(result.ok ? result.data.summary : null);
  }

  function todayLine(today) {
    const uk = state.locale === "uk";
    if (!today) {
      return t("summaryNoGames");
    }
    return [
      uk ? `${today.games} ${plural(today.games, "матч", "матчі", "матчів")}` : `${today.games} ${today.games === 1 ? "match" : "matches"}`,
      `${today.wins}–${today.losses}`,
      today.avg_score == null ? null : uk ? `середня оцінка ${today.avg_score}` : `average score ${today.avg_score}`,
      // Today's matches judged by the focus (the focus block below spans days).
      today.focus_total ? (uk ? `фокус ${today.focus_met} з ${today.focus_total}` : `focus ${today.focus_met} of ${today.focus_total}`) : null
    ].filter(Boolean).join(" · ");
  }

  function goalChips(goals) {
    return (goals || [])
      .filter((goal) => GOAL_TEXT[goal.id])
      .map((goal) =>
        h(
          "span",
          { class: "chip goal-chip", "data-met": String(Boolean(goal.met)), title: t("streakBest", goal.best) },
          icon(goal.met ? "circle-check" : "target"),
          h("span", { text: t(GOAL_TEXT[goal.id], goal.target) }),
          h("span", { class: "goal-count num", text: goal.met ? t("streakMet", goal.current) : t("streakProgress", goal.current, goal.target) })
        )
      );
  }

  function renderSummary(summary) {
    const cardEl = document.getElementById("summary-card");
    const body = document.getElementById("summary-body");
    if (!cardEl || !body) {
      return;
    }
    cardEl.classList.toggle("hidden", !summary);
    if (!summary) {
      body.replaceChildren();
      return;
    }
    const last = summary.last;
    const result = last.win === true ? "win" : last.win === false ? "loss" : "unknown";
    const combat = combatScore(last, "/");
    const facts = [
      combat === "—" ? null : combat,
      last.duration ? clock(last.duration) : null,
      relativeTime(last.start_time, "short")
    ].filter(Boolean).join(" · ");
    const tip = last.tip || last.strength;
    const lastBlock = h(
      "button",
      { type: "button", class: "summary-last", dataset: { result }, onclick: () => openMatch(last.match_id) },
      h(
        "span",
        { class: "summary-last-head" },
        window.DotaIcons ? window.DotaIcons.heroPicture(document, last.hero_id || last.hero, "md") : null,
        h(
          "span",
          { class: "summary-last-text" },
          h("span", { class: "summary-label", text: t("summaryLast") }),
          h("span", { class: "summary-hero" }, h("span", { text: last.hero || "—" }), h("span", { class: `result-tag result-${result}`, text: last.win === true ? t("win") : last.win === false ? t("loss") : "—" })),
          h("span", { class: "muted small num", text: facts })
        ),
        scoreRing(last.score, "md")
      ),
      tip
        ? h(
            "span",
            { class: "summary-tip" },
            h("span", { class: "summary-tip-label", text: last.tip ? t("summaryTip") : t("summaryStrength") }),
            h("span", { class: "summary-tip-title", text: tip.title || "" }),
            last.tip && tip.drill ? h("span", { class: "muted small", text: tip.drill }) : null
          )
        : null,
      h("span", { class: "summary-open" }, h("span", { text: t("summaryOpen") }), icon("chevron-right"))
    );
    const tilt = summary.tilt
      ? h("p", { class: "tilt-line", role: "status", text: summary.tilt.reason === "losses" ? t("tiltLosses", summary.tilt.losses) : t("tiltScore", summary.tilt.scores[0], summary.tilt.scores[1], summary.tilt.usual) })
      : null;
    const chips = goalChips(summary.goals);
    const today = h(
      "div",
      { class: "summary-block" },
      h("p", { class: "summary-label", text: t("summaryToday") }),
      h("p", { class: "summary-value num", text: todayLine(summary.today) }),
      tilt,
      chips.length ? h("div", { class: "goals-line" }, chips) : null
    );
    let focusBlock;
    if (summary.focus) {
      const focus = summary.focus;
      const marks = focus.results.map((row) =>
        h("button", {
          type: "button",
          class: "goal-mark",
          dataset: { met: String(row.met) },
          title: `${row.hero || "—"}: ${row.met ? t("goalMet") : t("goalMissed")}`,
          "aria-label": `${row.hero || "—"}: ${row.met ? t("goalMet") : t("goalMissed")}`,
          onclick: () => openMatch(row.match_id)
        })
      );
      focusBlock = h(
        "div",
        { class: "summary-block" },
        h("p", { class: "summary-label", text: t("summaryFocus") }),
        h("p", { class: "summary-value", text: focus.title || "" }),
        marks.length
          ? h("div", { class: "week-plan-row" }, h("div", { class: "goal-marks" }, marks), h("span", { class: "muted small num", text: t("summaryFocusProgress", focus.met, focus.total) }))
          : h("p", { class: "muted small", text: t("goalWaiting") })
      );
    } else {
      focusBlock = h(
        "div",
        { class: "summary-block" },
        h("p", { class: "summary-label", text: t("summaryFocus") }),
        h("p", { class: "muted small", text: t("summaryNoFocus") }),
        h("button", { type: "button", class: "btn btn-sm", onclick: () => setView("progress") }, h("span", { text: t("summaryPickFocus") }))
      );
    }
    body.replaceChildren(h("div", { class: "summary-grid" }, lastBlock, h("div", { class: "summary-side" }, today, focusBlock)));
    hydrate(body);
  }

  // --- home: the last seven days ---------------------------------------------------

  const WEEK_REFRESH_MS = 60 * 1000;

  async function refreshWeek(status) {
    const review = status.player && status.player.lastReview;
    const key = `${state.locale}|${review ? review.match_id : ""}|${status.player && status.player.accountId}`;
    if (state.weekKey === key && Date.now() - (state.weekAt || 0) < WEEK_REFRESH_MS) {
      return;
    }
    state.weekKey = key;
    state.weekAt = Date.now();
    const result = await call("week");
    renderWeek(result.ok ? result.data.week : null);
  }

  // «Останні матчі» on Home: the newest reviewed games, asked again when a new
  // review is written (the same key as the week) or after a minute.
  const RECENT_MATCHES = 6;

  async function refreshRecent(status) {
    const review = status.player && status.player.lastReview;
    const key = `${review ? review.match_id : ""}|${status.player && status.player.accountId}`;
    if (state.recentKey === key && Date.now() - (state.recentAt || 0) < WEEK_REFRESH_MS) {
      return;
    }
    state.recentKey = key;
    state.recentAt = Date.now();
    const result = await call("matches", { limit: RECENT_MATCHES });
    renderRecent(result.ok ? result.data.items || [] : []);
  }

  function renderRecent(rows) {
    const cardEl = document.getElementById("recent-card");
    const list = document.getElementById("recent-list");
    if (!cardEl || !list) {
      return;
    }
    cardEl.classList.toggle("hidden", !rows.length);
    list.replaceChildren(
      ...rows.map((row) => {
        const score = combatScore(row, "/");
        const kda = score === "—" ? null : score;
        const facts = [kda, row.duration ? clock(row.duration) : null, relativeTime(row.start_time)].filter(Boolean).join(" · ");
        const result = row.win === true ? "win" : row.win === false ? "loss" : "unknown";
        return h(
          "li",
          {},
          h(
            "button",
            {
              type: "button",
              class: "recent-item",
              dataset: { result },
              "aria-label": `${row.hero || ""} ${row.win === true ? t("win") : row.win === false ? t("loss") : ""}`,
              onclick: () => openMatch(row.match_id)
            },
            window.DotaIcons ? window.DotaIcons.heroPicture(document, row.hero_id || row.hero, "md") : null,
            h(
              "span",
              { class: "recent-text" },
              h(
                "span",
                { class: "recent-hero" },
                h("span", { text: row.hero || "—" }),
                row.note ? h("span", { class: "row-note", title: row.note, "aria-label": `${t("noteLabel")}: ${row.note}` }, icon("sticky-note")) : null
              ),
              h("span", { class: "recent-facts muted num", text: facts }),
              // The items it ended with, small (0.50; reviewed matches only).
              Array.isArray(row.items) && row.items.length && window.DotaIcons
                ? h("span", { class: "recent-items", "aria-hidden": "true" }, row.items.slice(0, 6).map((key) => window.DotaIcons.itemPicture(document, key, "sm")))
                : null
            ),
            scoreRing(row.score, "sm")
          )
        );
      })
    );
  }

  // The review score as a small ring (0–100) in the grade's tone; "—" without one.
  // The score's tone, the same for its ring and its column on the charts.
  function scoreTone(score) {
    return !Number.isFinite(score) ? "idle" : score >= 65 ? "good" : score >= 50 ? "warn" : "bad";
  }

  // A little of the card's colour mixed in: whole columns in the pure status
  // colours were louder than the rings they match.
  const TONE_COLORS = {
    good: "color-mix(in srgb, var(--ok) 78%, var(--surface-1))",
    warn: "color-mix(in srgb, var(--warn) 78%, var(--surface-1))",
    bad: "color-mix(in srgb, var(--error) 78%, var(--surface-1))",
    idle: "var(--viz-muted)"
  };

  function scoreRing(score, size = "md") {
    const known = Number.isFinite(score);
    const tone = scoreTone(score);
    // No review yet: a quiet dash in the ring's place (an empty ring read as a
    // «minus» button).
    if (!known) {
      return h("span", { class: `score-ring score-ring-${size} score-ring-none`, dataset: { tone } }, h("span", { class: "score-ring-value num", text: "—" }));
    }
    const radius = 15.5;
    const length = 2 * Math.PI * radius;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 36 36");
    svg.setAttribute("aria-hidden", "true");
    const arcs = [["ring-track", null]];
    if (known && score > 0) {
      arcs.push(["ring-value", (Math.min(100, score) / 100) * length]);
    }
    for (const [cls, dash] of arcs) {
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", "18");
      circle.setAttribute("cy", "18");
      circle.setAttribute("r", String(radius));
      circle.setAttribute("class", cls);
      if (dash !== null) {
        circle.setAttribute("stroke-dasharray", `${dash} ${length}`);
      }
      svg.append(circle);
    }
    return h(
      "span",
      { class: `score-ring score-ring-${size}`, dataset: { tone }, title: known ? `${t("scoreLabel")}: ${score}` : "" },
      svg,
      h("span", { class: "score-ring-value num", text: known ? String(Math.round(score)) : "—" })
    );
  }

  // --- home: «Підсумок вечора» (app/session_summary.py) --------------------------------

  async function refreshSession(status) {
    // Only once Dota is closed: during the evening the card would be about half of it.
    if (status.dotaRunning) {
      renderSession(null, status);
      return;
    }
    const review = status.player && status.player.lastReview;
    const key = `${state.locale}|${review ? review.match_id : ""}|${status.player && status.player.accountId}`;
    if (state.sessionKey === key && Date.now() - (state.sessionAt || 0) < WEEK_REFRESH_MS) {
      renderSession(state.session, status);
      return;
    }
    state.sessionKey = key;
    state.sessionAt = Date.now();
    const result = await call("session");
    state.session = result.ok ? result.data.session : null;
    renderSession(state.session, status);
  }

  function renderSession(session, status) {
    const cardEl = document.getElementById("session-card");
    const body = document.getElementById("session-body");
    if (!cardEl || !body) {
      return;
    }
    const show = Boolean(session && session.id !== (status && status.sessionSeen));
    cardEl.classList.toggle("hidden", !show);
    if (!show) {
      return;
    }
    if (body.dataset.sessionId === `${state.locale}|${session.id}|${session.avg_score}`) {
      return; // drawn already: keep the copy button's state
    }
    body.dataset.sessionId = `${state.locale}|${session.id}|${session.avg_score}`;
    document.getElementById("session-dismiss").onclick = async () => {
      const result = await window.launcherApi.session({ dismiss: session.id });
      cardEl.classList.add("hidden");
      if (result && result.status) {
        state.status = { ...state.status, sessionSeen: session.id };
      }
    };
    let change = null;
    if (Number.isFinite(session.score_change)) {
      const tone = session.score_change > 0 ? "good" : session.score_change < 0 ? "bad" : "idle";
      const iconName = session.score_change > 0 ? "trending-up" : session.score_change < 0 ? "trending-down" : "minus";
      change = h("span", { class: `delta delta-${tone}` }, icon(iconName), h("span", { class: "num", text: `${session.score_change > 0 ? "+" : ""}${session.score_change}` }), h("span", { class: "muted", text: ` ${t("sessionVsUsual")}` }));
    }
    const tiles = [
      tile(t("sessionGames"), String(session.games), null, t("weekRecord", session.wins, session.losses)),
      tile(
        t("sessionScore"),
        session.avg_score == null ? "—" : String(session.avg_score),
        change,
        session.avg_score == null ? t("sessionNoScore") : change ? null : session.usual_score != null ? t("sessionUsual", session.usual_score) : null
      )
    ];
    if (session.best) {
      tiles.push(
        h(
          "button",
          { type: "button", class: "tile tile-link", onclick: () => openMatch(session.best.match_id) },
          h("p", { class: "tile-label", text: t("weekBest") }),
          h("p", { class: "tile-value with-pic" }, window.DotaIcons?.hero(session.best.hero) ? window.DotaIcons.heroPicture(document, session.best.hero, "sm") : null, h("span", { class: "num", text: String(session.best.score) })),
          h("p", { class: "tile-sub muted", text: session.best.hero || "" })
        )
      );
    }
    const facts = [t("sessionTime", session.minutes), session.avg_deaths != null ? t("sessionDeaths", session.avg_deaths) : null].filter(Boolean).join(" · ");
    const lines = [h("p", { class: "week-line muted num", text: facts })];
    const heroes = (session.heroes || []).filter((hero) => hero && hero.hero);
    if (heroes.length) {
      lines.push(
        h(
          "p",
          { class: "week-line week-heroes" },
          h("span", { class: "muted", text: `${t("weekHeroes")} ` }),
          heroes.map((hero) =>
            h(
              "span",
              { class: "week-hero", title: t("weekHeroTitle", hero.hero, hero.games, hero.wins) },
              window.DotaIcons?.hero(hero.hero) ? window.DotaIcons.heroPicture(document, hero.hero, "sm") : null,
              h("span", { text: hero.hero }),
              h("span", { class: "muted num", text: `${hero.wins}–${hero.games - hero.wins}` })
            )
          )
        )
      );
    }
    if (session.top_problem) {
      lines.push(h("p", { class: "week-line" }, h("span", { class: "muted", text: `${t("sessionProblem")} ` }), h("span", { text: t("sessionProblemText", session.top_problem.title, session.top_problem.count, session.top_problem.of) })));
    }
    if (session.focus) {
      lines.push(h("p", { class: "week-line", text: t("sessionFocus", session.focus.title, session.focus.met, session.focus.total) }));
    }
    const copy = h("button", { type: "button", class: "btn btn-primary btn-sm" }, icon("copy"), h("span", { text: t("sessionCopy") }));
    copy.addEventListener("click", async () => {
      const result = await window.launcherApi.session("copy");
      if (result && result.ok) {
        const label = copy.querySelector("span");
        label.textContent = t("sessionCopied");
        setTimeout(() => {
          label.textContent = t("sessionCopy");
        }, 1600);
      }
    });
    const preview = h(
      "details",
      { class: "session-preview" },
      h("summary", { text: t("sessionPreview") }),
      h("pre", { class: "report-preview-text", tabindex: "0", text: session.text || "" })
    );
    body.replaceChildren(h("div", { class: "tiles week-tiles" }, tiles), ...lines, h("div", { class: "session-actions" }, copy), preview);
    hydrate(body);
  }

  let shownWeek = null;

  function renderWeek(week) {
    shownWeek = week;
    const cardEl = document.getElementById("week-card");
    const body = document.getElementById("week-body");
    if (!cardEl || !body) {
      return;
    }
    cardEl.classList.toggle("hidden", !week);
    if (!week) {
      body.replaceChildren();
      return;
    }
    let change = null;
    if (Number.isFinite(week.score_change)) {
      const tone = week.score_change > 0 ? "good" : week.score_change < 0 ? "bad" : "idle";
      const iconName = week.score_change > 0 ? "trending-up" : week.score_change < 0 ? "trending-down" : "minus";
      change = h("span", { class: `delta delta-${tone}` }, icon(iconName), h("span", { class: "num", text: `${week.score_change > 0 ? "+" : ""}${week.score_change}` }), h("span", { class: "muted", text: ` ${t("weekVsPrevious")}` }));
    }
    // Without a comparison, say which side is missing (weekly_summary
    // score_note) instead of leaving the tile half empty.
    const scoreNote = change ? null : tOptional(`weekScoreNote.${week.score_note}`) || null;
    const tiles = [
      tile(t("weekGames"), String(week.games), null, t("weekRecord", week.wins, week.losses)),
      tile(t("tiles.score"), week.avg_score == null ? "—" : String(week.avg_score), change, scoreNote)
    ];
    if (week.best) {
      const best = h(
        "button",
        { type: "button", class: "tile tile-link", onclick: () => openMatch(week.best.match_id) },
        h("p", { class: "tile-label", text: t("weekBest") }),
        h("p", { class: "tile-value with-pic" }, window.DotaIcons?.hero(week.best.hero) ? window.DotaIcons.heroPicture(document, week.best.hero, "sm") : null, h("span", { class: "num", text: String(week.best.score) })),
        h("p", { class: "tile-sub muted", text: week.best.hero || "" })
      );
      tiles.push(best);
    }
    const lines = [];
    const heroes = (week.heroes || []).filter((hero) => hero && hero.hero);
    if (heroes.length > 1) {
      lines.push(
        h(
          "p",
          { class: "week-line week-heroes" },
          h("span", { class: "muted", text: `${t("weekHeroes")} ` }),
          heroes.map((hero) =>
            h(
              "span",
              { class: "week-hero", title: t("weekHeroTitle", hero.hero, hero.games, hero.wins) },
              window.DotaIcons?.hero(hero.hero) ? window.DotaIcons.heroPicture(document, hero.hero, "sm") : null,
              h("span", { text: hero.hero }),
              h("span", { class: "muted num", text: `${hero.wins}–${hero.games - hero.wins}` })
            )
          )
        )
      );
    }
    if (week.top_problem) {
      lines.push(h("p", { class: "week-line" }, h("span", { class: "muted", text: `${t("weekProblem")} ` }), h("span", { text: t("weekProblemText", week.top_problem.title, week.top_problem.count, week.top_problem.of) })));
    }
    if (week.focus) {
      const plan = week.focus;
      const marks = Array.from({ length: plan.plan }, (_, index) => {
        const result = plan.results[index];
        return h("span", { class: "goal-mark", dataset: { met: result ? String(result.met) : "none" }, title: result ? `${result.hero || "—"}: ${result.met ? t("goalMet") : t("goalMissed")}` : t("weekPlanNext") });
      });
      lines.push(
        h(
          "div",
          { class: "week-plan" },
          h("p", { class: "week-line" }, h("span", { class: "muted", text: `${t("weekFocus")} ` }), h("span", { text: plan.title || "" })),
          h("div", { class: "week-plan-row" }, h("div", { class: "goal-marks" }, marks), h("span", { class: "muted small num", text: t("weekPlanProgress", plan.met, plan.results.length, plan.plan) })),
          plan.drill ? h("p", { class: "muted small", text: plan.drill }) : null
        )
      );
    }
    // Every match of the week as a column (its score, win or loss); a click opens it.
    const scored = (week.matches || []).filter((match) => Number.isFinite(match.score));
    const chartHost = scored.length > 1 ? h("div", { class: "chart-host week-chart" }) : null;
    body.replaceChildren(h("div", { class: "tiles week-tiles" }, tiles), chartHost ? h("p", { class: "week-chart-title muted small", text: t("weekChartTitle") }) : null, chartHost, ...lines);
    hydrate(body);
    if (chartHost) {
      window.LauncherCharts.columns(chartHost, {
        items: scored.map((match) => ({
          label: String(match.match_id),
          value: match.score,
          color: TONE_COLORS[scoreTone(match.score)],
          title: `${match.hero || "—"} · ${match.win === true ? t("win") : match.win === false ? t("loss") : "—"}`,
          detail: relativeTime(match.start_time),
          key: match.win === true ? "win" : match.win === false ? "loss" : null,
          matchId: match.match_id
        })),
        yMax: 100,
        height: 132,
        color: VIZ_1,
        valueLabel: t("scoreLabel"),
        ariaLabel: t("weekChartTitle"),
        onSelect: (item) => openMatch(item.matchId)
      });
    }
  }

  function onStatus(status) {
    const localeChanged = state.locale !== (status.locale === "uk" ? "uk" : "en");
    const cameUp = status.backend === "running" && state.status?.backend !== "running";
    const backendChanged = status.backend !== state.status?.backend;
    state.locale = status.locale === "uk" ? "uk" : "en";
    state.status = status;
    // A tab waiting for the coach (offlinePage) opens once it runs, and says
    // «starting» / «not answering» as that changes.
    if (backendChanged && !state.player && ["matches", "progress", "profile"].includes(state.view)) {
      if (cameUp) {
        setView(state.view, { remember: false });
      } else {
        const root = document.getElementById(`${state.view}-root`);
        if (root) {
          root.replaceChildren(...offlinePage(state.view));
          hydrate(root);
        }
      }
    }
    if (status.backend === "running" && status.player && status.player.linked) {
      refreshSummary(status).catch(() => {});
      refreshWeek(status).catch(() => {});
      refreshRecent(status).catch(() => {});
      refreshSession(status).catch(() => {});
    } else {
      renderSummary(null);
      renderWeek(null);
      renderRecent([]);
      renderSession(null, status);
    }
    if (localeChanged) {
      // Texts from the backend (reviews, progress, profile) come in the new language only
      // when asked again.
      if (state.view === "matches") {
        renderMatches();
      } else if (state.view === "progress") {
        loadCareer();
      } else if (state.view === "profile") {
        loadProfile();
      } else if (state.view === "match" && state.matchId) {
        openMatchQuietly(state.matchId).then(applied => { if (applied) renderMatch(); });
      } else if (state.view === "settings") {
        renderAiSettings();
      }
    }
  }

  // «?»: the keys of Settings → «Hotkeys» in a dialog over any tab (the same
  // list, already in the UI language). Esc, the button or a click outside closes it.
  // --- Ctrl+K: the command palette --------------------------------------------
  // One field for everything: a tab, a match (by hero, result, date or the
  // player's note), a setting (the rows of Settings with the keywords their
  // search uses) or an action. ↑/↓ choose, Enter runs, Esc closes. Words
  // count from their start, like the settings search (SettingsSearch.terms).
  const PALETTE_LIMIT = 9;
  const PALETTE_GROUPS = ["tabs", "actions", "heroes", "matches", "settings"];

  function paletteActions() {
    const linked = Boolean(state.player?.linked);
    const actions = [
      linked && {
        icon: "refresh-cw",
        label: t("palSync"),
        keys: "sync оновити синхронізувати історія history refresh",
        run: async () => {
          setView("matches");
          await call("sync");
          loadMatches(true);
        }
      },
      linked && {
        icon: "search",
        label: t("palOpenNumber"),
        keys: "номер посилання opendota dotabuff stratz number link id",
        run: () => {
          setView("matches");
          setTimeout(() => document.querySelector(".open-number-input")?.focus(), 400);
        }
      },
      { icon: "circle-help", label: t("palHotkeys"), keys: "гарячі клавіші hotkeys keys shortcuts", run: () => showHotkeys() },
      { icon: "compass", label: t("palTour"), keys: "навчання екскурсія тур tour guide help", run: () => document.getElementById("tour-start")?.click() },
      {
        icon: "send",
        label: t("palReport"),
        keys: "проблема помилка баг звіт report bug problem",
        run: () => {
          setView("settings");
          const button = document.getElementById("report-open");
          if (button && button.getAttribute("aria-expanded") !== "true") {
            button.click();
          }
          button?.scrollIntoView({ block: "center" });
        }
      }
    ];
    return actions.filter(Boolean).map((item) => ({ ...item, group: "actions" }));
  }

  function paletteMatchItem(row) {
    const result = row.win === true ? t("win") : row.win === false ? t("loss") : "";
    const score = combatScore(row, "/");
    const kda = score === "—" ? null : score;
    return {
      group: "matches",
      hero: row.hero_id || row.hero,
      label: [row.hero || "—", result].filter(Boolean).join(" · "),
      detail: [kda, row.score == null ? null : `${row.score}/100`, relativeTime(row.start_time, "short"), row.note ? `«${row.note}»` : null].filter(Boolean).join(" · "),
      keys: `${row.match_id} ${row.note || ""}`,
      run: () => openMatch(row.match_id)
    };
  }

  function paletteSettingItems() {
    return [...document.querySelectorAll("#view-settings .setting")]
      .map((row) => {
        const title = row.querySelector(".setting-title")?.textContent.trim();
        if (!title) {
          return null;
        }
        return {
          group: "settings",
          icon: "settings",
          label: title,
          detail: row.closest(".zone")?.querySelector(".zone-title")?.textContent.trim() || "",
          keys: row.dataset.search || "",
          run: () => {
            setView("settings");
            const folded = row.closest("details");
            if (folded && !folded.open) {
              folded.open = true;
            }
            row.scrollIntoView({ block: "center" });
            row.classList.remove("flash");
            void row.offsetWidth;
            row.classList.add("flash");
            row.querySelector("input, button, select")?.focus({ preventScroll: true });
          }
        };
      })
      .filter(Boolean);
  }

  function paletteItems(rows) {
    const tabs = [
      ["home", "house"],
      ["matches", "history"],
      ["progress", "chart-line"],
      ["profile", "user"],
      ["settings", "settings"]
    ].map(([view, iconName]) => ({ group: "tabs", icon: iconName, label: t(`backTo.${view}`), keys: view, run: () => setView(view) }));
    // «Прогрес на Juggernaut»: Progress filtered to a hero of the list.
    const heroes = new Map();
    for (const row of rows) {
      if (row.hero_id && !heroes.has(row.hero_id)) {
        heroes.set(row.hero_id, row.hero || "");
      }
    }
    const heroItems = [...heroes].map(([heroId, name]) => ({
      group: "heroes",
      hero: heroId,
      label: t("palProgressHero", name || "—"),
      keys: "progress прогрес",
      run: () => {
        state.careerHero = heroId;
        setView("progress");
      }
    }));
    return [...tabs, ...paletteActions(), ...heroItems, ...rows.map(paletteMatchItem), ...paletteSettingItems()];
  }

  // Empty query: the tabs, the actions and the five newest matches. Words:
  // every item whose text has them all, those whose title has them first.
  function paletteFilter(items, query) {
    const search = window.SettingsSearch;
    const words = search ? search.terms(query) : [];
    if (!words.length) {
      const newest = items.filter((item) => item.group === "matches").slice(0, 5);
      return [...items.filter((item) => item.group === "tabs" || item.group === "actions"), ...newest];
    }
    return items
      .filter((item) => search.matches(`${item.label} ${item.detail || ""} ${item.keys || ""}`, words))
      .map((item) => ({ item, title: search.matches(item.label, words) ? 0 : 1 }))
      .sort((a, b) => a.title - b.title || PALETTE_GROUPS.indexOf(a.item.group) - PALETTE_GROUPS.indexOf(b.item.group))
      .map(({ item }) => item)
      .slice(0, PALETTE_LIMIT);
  }

  async function openPalette() {
    if (document.querySelector("dialog[open]") || document.querySelector(".tour")) {
      return;
    }
    let rows = state.matches;
    const input = h("input", {
      class: "input palette-input",
      type: "text",
      autocomplete: "off",
      spellcheck: "false",
      role: "combobox",
      "aria-expanded": "true",
      "aria-controls": "palette-list",
      "aria-label": t("palPlaceholder"),
      placeholder: t("palPlaceholder")
    });
    const list = h("ul", { class: "palette-list", id: "palette-list", role: "listbox", "aria-label": t("palPlaceholder") });
    const dialog = h(
      "dialog",
      { class: "palette", "aria-label": t("palPlaceholder") },
      h("div", { class: "palette-field" }, icon("search"), input),
      list,
      h("p", { class: "palette-hint muted small", text: t("palHint") })
    );
    let shown = [];
    let active = 0;
    const choose = (index) => {
      active = Math.max(0, Math.min(shown.length - 1, index));
      list.querySelectorAll("[role=option]").forEach((node, i) => {
        node.setAttribute("aria-selected", String(i === active));
        if (i === active) {
          input.setAttribute("aria-activedescendant", node.id);
          node.scrollIntoView({ block: "nearest" });
        }
      });
    };
    const run = (item) => {
      dialog.close();
      item?.run();
    };
    const draw = () => {
      shown = paletteFilter(paletteItems(rows), input.value);
      if (!shown.length) {
        list.replaceChildren(h("li", { class: "palette-empty muted", text: t("palEmpty") }));
        input.removeAttribute("aria-activedescendant");
        return;
      }
      list.replaceChildren(
        ...shown.map((item, index) =>
          h(
            "li",
            {
              id: `palette-${index}`,
              role: "option",
              class: "palette-item",
              "aria-selected": "false",
              onclick: () => run(item),
              onmousemove: () => active !== index && choose(index)
            },
            item.hero && window.DotaIcons ? window.DotaIcons.heroPicture(document, item.hero, "sm") : h("span", { class: "palette-icon" }, icon(item.icon || "circle")),
            h("span", { class: "palette-text" }, h("span", { class: "palette-label", text: item.label }), item.detail ? h("span", { class: "palette-detail muted", text: item.detail }) : null),
            h("span", { class: "palette-group muted", text: t(`palGroups.${item.group}`) })
          )
        )
      );
      hydrate(list);
      choose(0);
    };
    input.addEventListener("input", draw);
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        choose(active + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter") {
        event.preventDefault();
        run(shown[active]);
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    hydrate(dialog);
    dialog.showModal();
    input.focus();
    draw();
    // The matches of the whole table (no filter), when the list has not been
    // loaded yet or is filtered; the player first when no tab asked yet.
    if (!state.player) {
      await refreshPlayer();
      if (dialog.open) {
        draw();
      }
    }
    if (state.player?.linked && (!rows.length || state.filter.heroId || state.filter.result !== "all")) {
      const result = await call("matches", { limit: 50 });
      if (result.ok && dialog.open) {
        rows = result.data.items || [];
        draw();
      }
    }
  }

  function showHotkeys() {
    const source = document.querySelector("details.hotkeys");
    if (!source || document.querySelector("dialog.hotkeys-dialog")) {
      return;
    }
    const title = source.querySelector("summary span")?.textContent || "";
    const close = h("button", { class: "btn btn-ghost btn-sm btn-icon", type: "button", "aria-label": t("dialogClose"), title: t("dialogClose") }, icon("x"));
    const dialog = h(
      "dialog",
      { class: "hotkeys-dialog", "aria-labelledby": "hotkeys-dialog-title" },
      h("header", { class: "hotkeys-dialog-head" }, h("h2", { id: "hotkeys-dialog-title", text: title }), close),
      Array.from(source.querySelectorAll(".hotkeys-group, .hotkeys-list")).map((node) => node.cloneNode(true))
    );
    close.addEventListener("click", () => dialog.close());
    // A click on the dimmed backdrop lands on the dialog element itself.
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    hydrate(dialog);
    dialog.showModal();
    close.focus();
  }

  function init() {
    document.getElementById("zone-all-matches")?.addEventListener("click", () => setView("matches"));
    for (const tab of document.querySelectorAll(".tabs [data-view]")) {
      tab.addEventListener("click", () => setView(tab.dataset.view));
    }
    document.querySelector(".tabs")?.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      const tabs = [...document.querySelectorAll(".tabs [data-view]")];
      const index = tabs.findIndex((tab) => tab.getAttribute("aria-selected") === "true");
      const next = tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      setView(next.dataset.view);
    });
    // Keyboard: Ctrl+1…5 opens a tab, Esc leaves a match review for the list,
    // ←/→ in a review open the newer / older match of the list.
    // Never while typing, and never under the first-run tour (it owns Esc).
    // Ctrl+K anywhere (the key, not the letter: «л» on a Cyrillic layout).
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.code === "KeyK") {
        event.preventDefault();
        openPalette();
      }
    });
    document.getElementById("side-find")?.addEventListener("click", () => openPalette());
    // Alt+←/→ and the mouse's back / forward buttons walk the places visited.
    const historyBlocked = () => Boolean(document.querySelector(".tour, dialog[open]"));
    document.addEventListener("keydown", (event) => {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) {
        return;
      }
      if (historyBlocked() || event.target?.closest?.("textarea, [contenteditable='true']")) {
        return;
      }
      if (event.key === "ArrowLeft" ? goBack() : goForward()) {
        event.preventDefault();
      }
    });
    document.addEventListener("mouseup", (event) => {
      if ((event.button !== 3 && event.button !== 4) || historyBlocked()) {
        return;
      }
      event.preventDefault();
      if (event.button === 3) {
        goBack();
      } else {
        goForward();
      }
    });
    document.addEventListener("keydown", (event) => {
      // A dialog open (the keys list) owns its keys: Esc closes it, not the review.
      if (event.defaultPrevented || event.altKey || event.metaKey || document.querySelector(".tour, dialog[open]")) {
        return;
      }
      if (event.target?.closest?.("input, textarea, select, [contenteditable='true']")) {
        return;
      }
      if (event.key === "?" && !event.ctrlKey) {
        event.preventDefault();
        showHotkeys();
      } else if (event.ctrlKey && !event.shiftKey && /^[1-5]$/.test(event.key)) {
        const tab = document.querySelectorAll(".tabs [data-view]")[Number(event.key) - 1];
        if (tab) {
          event.preventDefault();
          tab.focus();
          setView(tab.dataset.view);
        }
      } else if (event.key === "Escape" && !event.ctrlKey && state.view === "match") {
        event.preventDefault();
        leaveReview();
      } else if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && !event.ctrlKey && !event.shiftKey && state.view === "match") {
        // ← newer, → older; the tabs and the charts keep their own arrows.
        if (event.target?.closest?.(".tabs")) {
          return;
        }
        const row = neighbourMatch(event.key === "ArrowLeft" ? -1 : 1);
        if (row) {
          event.preventDefault();
          openMatch(row.match_id);
        }
      }
    });
    api.onPlayerEvent?.((event) => {
      if (event.type === "open-match" && event.matchId) {
        openMatch(event.matchId);
      } else if (event.type === "open-home") {
        // The evening summary's tray note: its card is on Home.
        setView("home");
      } else if (event.type === "review-ready" && state.view === "matches") {
        loadMatches(true);
      }
    });
    // app.js may render its first status before this script loads.
    api.getStatus?.().then((status) => status && onStatus(status)).catch(() => {});
    let saved = "home";
    try {
      saved = localStorage.getItem(TAB_KEY) || "home";
    } catch {
      // Storage unavailable: start on Home.
    }
    if (["matches", "progress", "profile", "settings"].includes(saved)) {
      setView(saved, { remember: false });
    }
    // Keep the table fresh while it is open (new matches, sync results).
    setInterval(() => {
      if (state.view === "matches" && !document.hidden) {
        loadMatches();
      }
    }, 15000);
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (state.view === "match" && state.match?.analysis) {
          drawMatchCharts(document.getElementById("match-root"), state.match.analysis);
        } else if (state.view === "progress" && state.career) {
          renderCareer();
        } else if (state.view === "profile" && state.profile) {
          renderProfile();
        } else if (state.view === "home" && shownWeek) {
          renderWeek(shownWeek); // the score chart measures its column
        }
      }, 150);
    });
  }

  window.PlayerViews = { onStatus, openMatch, setView, loadMatches, loadCareer, loadProfile, loadFriends, refreshPlayer };
  init();
})();
