const shell = document.querySelector("#overlay-shell");
const labelEl = document.querySelector("#label");
const priorityEl = document.querySelector("#priority");
const statusRow = document.querySelector("#status-row");
const actionEl = document.querySelector("#action");
const reasonEl = document.querySelector("#reason");
const stripEl = document.querySelector("#timer-strip");
const itemsEl = document.querySelector("#items-row");

// Short card texts in the system language; advice itself comes from the backend.
const OVERLAY_TEXT = {
  en: {
    urgent: "Urgent",
    tip: "Tip",
    coach: "Coach",
    demo: "Demo",
    waitingBackend: "Starting the coach…",
    backendStopped: "The coach is stopped: open Wardly to start it.",
    waitingGsi: "Waiting for Dota 2 to connect…",
    waitingGsiShort: "Waiting for game data…",
    monitoring: "Watching the lane — no urgent advice.",
    unsupportedHero: "This hero is not supported yet.",
    invalidState: "Waiting for valid game data…",
    listening: "Listening for advice…",
    muted: "Advice muted for 5 minutes.",
    mutedFor: (s) => `Advice muted (${s} s).`,
    noNewAdvice: "No new advice.",
    paused: "Advice paused to avoid overload.",
    watching: "Watching…",
    noUrgent: "No urgent advice.",
    noAction: "No urgent advice",
    plan: "Plan for this game",
    map: "Map",
    itemMinute: (m) => `usually by minute ${m}`,
    hintIn: (seconds) => (seconds > 0 ? `in ${seconds} s` : "now"),
    hintSoon: (title) => `Soon: ${title}`,
    sample: "Example",
    sampleAction: "Leave the wave now and reset HP before rejoining.",
    sampleReason: "Drag the card where you like, then press “Done” or Ctrl+Alt+L."
  },
  uk: {
    urgent: "Терміново",
    tip: "Порада",
    coach: "Тренер",
    demo: "Демо",
    waitingBackend: "Запускаємо тренера…",
    backendStopped: "Тренера зупинено: відкрийте Wardly, щоб запустити.",
    waitingGsi: "Чекаємо, поки Dota 2 підключиться…",
    waitingGsiShort: "Чекаємо на дані гри…",
    monitoring: "Стежимо за лінією — термінових порад немає.",
    unsupportedHero: "Цей герой поки не підтримується.",
    invalidState: "Чекаємо коректні дані гри…",
    listening: "Чекаємо наступну пораду…",
    muted: "Поради вимкнено на 5 хвилин.",
    mutedFor: (s) => `Поради вимкнено (${s} с).`,
    noNewAdvice: "Нових порад немає.",
    paused: "Поради на паузі, щоб не перевантажувати.",
    watching: "Спостерігаємо…",
    noUrgent: "Термінових порад немає.",
    noAction: "Термінових порад немає",
    plan: "План на гру",
    map: "Мапа",
    itemMinute: (m) => `зазвичай до ${m}-ї хвилини`,
    hintIn: (seconds) => (seconds > 0 ? `через ${seconds} с` : "зараз"),
    hintSoon: (title) => `Скоро: ${title}`,
    sample: "Приклад",
    sampleAction: "Ідіть із хвилі зараз і відновіть HP, перш ніж повернутися.",
    sampleReason: "Перетягніть картку, куди зручно, і натисніть «Готово» або Ctrl+Alt+L."
  }
};

function tr(key, ...args) {
  const table = OVERLAY_TEXT[config.locale] || OVERLAY_TEXT.en;
  const value = key.split(".").reduce((node, part) => (node ? node[part] : undefined), table);
  const resolved = value ?? key.split(".").reduce((node, part) => (node ? node[part] : undefined), OVERLAY_TEXT.en) ?? key;
  return typeof resolved === "function" ? resolved(...args) : resolved;
}

let config = {
  locale: "en",
  backendUrl: "",
  backendStatus: "starting",
  pollIntervalMs: 1000,
  locked: true,
  autoHideMs: 8000,
  urgentAutoHideMs: 12000,
  debugVisible: false,
  voice: "off",
  voiceVolume: 1,
  timers: true,
  compact: false
};
let pollTimer = null;
let hideTimer = null;
let mutedUntil = 0;
let lastAdviceKey = "";
let lastVisibleAdvice = null;
let lastSpokenKey = "";
const speaker = window.OverlayVoice && window.speechSynthesis
  ? window.OverlayVoice.createSpeaker({ synth: window.speechSynthesis, Utterance: window.SpeechSynthesisUtterance })
  : null;

init();

async function init() {
  config = { ...config, ...(await window.overlayApi.getConfig()) };
  applyConfig(config);
  window.overlayApi.onConfigUpdated((nextConfig) => {
    config = { ...config, ...nextConfig };
    applyConfig(config);
  });
  window.overlayApi.onMuted((timestamp) => {
    mutedUntil = Number(timestamp) || 0;
    speaker?.reset();
    showStatus(tr("muted"));
  });
  window.overlayApi.onRepeat?.(() => {
    if (!lastVisibleAdvice?.recommendation) {
      return;
    }
    const data = lastVisibleAdvice;
    renderAdvice(data, { refreshTimer: false });
    scheduleAutoHide(data.advice_mode || "coaching", { ...data, is_pinned: false });
    speaker?.say({
      key: lastAdviceKey,
      text: data.recommendation.action,
      fallbackText: data.recommendation.action_en,
      adviceMode: data.advice_mode,
      mode: config.voice,
      locale: config.locale,
      volume: config.voiceVolume,
      repeat: true
    });
  });
  window.overlayApi.onToggleDebug((visible) => {
    config.debugVisible = Boolean(visible);
    applyConfig(config);
  });
  startPolling();
}

function applyConfig(nextConfig) {
  document.body.classList.toggle("compact", nextConfig.compact === true);
  document.body.classList.toggle("locked", Boolean(nextConfig.locked));
  document.body.classList.toggle("unlocked", !nextConfig.locked);
  document.body.classList.toggle("debug-hidden", nextConfig.debugVisible === false);
}

function startPolling() {
  clearInterval(pollTimer);
  poll();
  pollTimer = setInterval(poll, Number(config.pollIntervalMs) || 1000);
}

async function poll() {
  // Muted or no answer: no fresh timers, so none are shown (a chip left from the
  // last answer would count down from a frozen value).
  if (Date.now() < mutedUntil) {
    renderStrip([]);
    showStatus(tr("mutedFor", secondsUntil(mutedUntil)));
    return;
  }

  const result = await window.overlayApi.fetchRecommendation();
  if (!result.ok) {
    renderStrip([]);
    showStatus(config.backendStatus === "stopped" ? tr("backendStopped") : tr("waitingBackend"));
    return;
  }

  renderOverlay(result.data);
}

// Map hint (timer or role tip) of the latest poll: shown in the top row next to
// advice, or as the card itself while there is no advice.
let currentHint = null;
const spokenHints = new Set();

// The backend withdrew the card on screen (the named item was used, a stun
// landed, the life ended, the numbers changed): it must not come back from
// lastVisibleAdvice on a cooldown poll, and its speech stops.
function dropWithdrawnAdvice(withdrawn) {
  const shown = lastVisibleAdvice?.recommendation;
  if (!withdrawn || !shown) {
    return;
  }
  const shownAction = shown.action_en || shown.action;
  if (shownAction !== withdrawn.action) {
    return;
  }
  speaker?.cancel(lastSpokenKey);
  lastVisibleAdvice = null;
  lastAdviceKey = "";
  lastSpokenKey = "";
}

function renderOverlay(data) {
  dropWithdrawnAdvice(data.withdrawn_advice);
  renderItems([]);
  renderStrip(data.post_game && data.post_game.main ? [] : data.timer_strip);
  // The score screen after a match: the summary of its review, nothing else.
  if (data.post_game && data.post_game.main) {
    showPostGame(data);
    return;
  }
  // Dead, waiting to respawn: how it happened and what to do now.
  if (data.death_screen && Array.isArray(data.death_screen.lines) && data.death_screen.lines.length) {
    showDeathScreen(data);
    return;
  }
  currentHint = data.map_hint && data.map_hint.title ? data.map_hint : null;
  speakHint(currentHint);
  if (data.recommendation && (data.status === "active_advice" || data.status === "cooldown")) {
    renderAdvice(data, { refreshTimer: data.status !== "active_advice" });
    return;
  }

  // A skill point to spend (the first one before the horn) keeps the card over
  // the plan: the plan used to replace it before anyone could read it.
  if (currentHint && (currentHint.over_plan || String(currentHint.id || "").startsWith("skill-")) && PLAN_STATUSES.has(data.status)) {
    showHint(currentHint, data);
    return;
  }

  // From -0:20 to 1:30, while there is no advice: the plan for this game.
  if (data.game_plan && Array.isArray(data.game_plan.lines) && data.game_plan.lines.length && PLAN_STATUSES.has(data.status)) {
    showPlan(data);
    return;
  }

  // Moving the card with nothing to show: a sample advice, so the player sets
  // the place and the size by a card of the real size, not a one-line status.
  if (!config.locked && !(data.status === "cooldown" && lastVisibleAdvice)) {
    showSample(data);
    return;
  }

  if (data.status === "waiting_for_gsi") {
    showStatus(tr("waitingGsi"), data);
    return;
  }

  if (data.status === "stale_gsi") {
    lastVisibleAdvice = null;
    lastAdviceKey = "";
    showStatus(data.message || tr("waitingGsiShort"), data);
    return;
  }

  if (data.status === "monitoring") {
    showStatus(data.message || tr("monitoring"), data);
    return;
  }

  if (data.status === "unsupported_hero") {
    showStatus(tr("unsupportedHero"), data);
    return;
  }

  if (data.status === "invalid_state") {
    showStatus(tr("invalidState"), data);
    return;
  }

  if (data.status === "cooldown") {
    if (lastVisibleAdvice) {
      renderAdvice(lastVisibleAdvice, { refreshTimer: false });
      return;
    }
    showStatus(data.message || statusMessage(data), data);
    return;
  }

  if (!data.recommendation) {
    showStatus(statusMessage(data), data);
    return;
  }

  renderAdvice(data, { refreshTimer: true });
}

// Item icons under the card's first line ([{key, name}]): the plan's build, the
// usual start on the empty-bag card. A picture that is not cached yet shows its
// initials (dota-icons.js).
function renderItems(items) {
  const list = Array.isArray(items) ? items.filter((item) => item && item.key).slice(0, 6) : [];
  itemsEl.classList.toggle("hidden", !list.length || !window.DotaIcons);
  if (!list.length || !window.DotaIcons) {
    itemsEl.replaceChildren();
    return;
  }
  itemsEl.replaceChildren(...list.map(itemCell));
}

// One icon; a build item of the plan carries its usual minute as a corner badge
// (as Dota draws charges), a start item bought twice its count («×2»), so the
// card keeps its height.
function itemCell(item) {
  const picture = window.DotaIcons.itemPicture(document, item.key, "sm", item.name);
  const minute = Number.isFinite(item.minute) ? Math.round(item.minute) : null;
  const count = Number.isInteger(item.count) && item.count > 1 ? item.count : null;
  if (minute === null && count === null) return picture;
  const cell = document.createElement("span");
  cell.className = "item-cell";
  const badge = document.createElement("small");
  badge.className = "item-min";
  badge.textContent = minute !== null ? `${minute}′` : `×${count}`;
  cell.title = minute !== null ? `${item.name || item.key} · ${tr("itemMinute", minute)}` : item.name || item.key;
  cell.append(picture, badge);
  return cell;
}

// The strip under the card: «Rune 0:50 · Stack 0:12 · Roshan 3:10», counting down.
function renderStrip(items) {
  const list = config.timers === false || !Array.isArray(items) ? [] : items.filter((item) => item && item.label);
  stripEl.classList.toggle("hidden", !list.length);
  stripEl.replaceChildren(
    ...list.map((item) => {
      const row = document.createElement("li");
      row.className = `timer-chip timer-${item.kind || "event"}`;
      row.dataset.soon = String(Number(item.in_seconds) <= 20);
      const label = document.createElement("span");
      label.textContent = item.label;
      const time = document.createElement("span");
      time.className = "timer-time";
      time.textContent = countdown(item.in_seconds);
      row.append(label, time);
      return row;
    })
  );
}

function countdown(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

// A new card slides in (a short fade); the same card refreshed stays still.
// A card left unchanged for IDLE_AFTER_MS fades to the background (body.idle):
// the plan or a timer does not sit bright over the game for minutes, and the
// next new card comes back at full strength, so the player notices it. Urgent
// advice, the score screen and a card being moved never fade (styles.css).
const IDLE_AFTER_MS = 20000;
let shownCardKey = "";
let idleTimer = 0;
function markCard(key) {
  if (key === shownCardKey) {
    return;
  }
  shownCardKey = key;
  document.body.classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => document.body.classList.add("idle"), IDLE_AFTER_MS);
  shell.classList.remove("enter");
  void shell.offsetWidth; // restart the animation
  shell.classList.add("enter");
}

function renderAdvice(data, options = { refreshTimer: true }) {
  const recommendation = data.recommendation;
  const adviceMode = data.advice_mode || (recommendation.priority === "high" ? "urgent" : "coaching");
  const key = [
    data.decision_point,
    recommendation.action,
    recommendation.reason,
    recommendation.priority,
    data.match_death_count || 0,
    data.last_death_minute || ""
  ].join("|");

  shell.className = [
    "overlay-shell",
    adviceMode === "urgent" ? "urgent" : "coaching",
    priorityClassName(recommendation.priority)
  ].filter(Boolean).join(" ");
  labelEl.textContent = labelText(adviceMode, data);
  // The corner carries the map timing when there is one; «medium priority»
  // only repeated the label on the left («Порада» / «Терміново») and its colour.
  priorityEl.textContent = currentHint ? hintShort(currentHint) : "";
  actionEl.textContent = recommendation.action || tr("noAction");
  reasonEl.textContent = recommendation.reason || "";
  renderStatusRow(data);
  reveal();
  markCard(`advice|${key}`);

  lastVisibleAdvice = data;
  // Spoken once per advice while it is still current (a tip skipped because
  // another one was being spoken gets its turn on a later poll).
  if (speaker && data.status === "active_advice") {
    lastSpokenKey = key;
    speaker.say({
      key,
      text: recommendation.action,
      fallbackText: recommendation.action_en,
      adviceMode,
      mode: config.voice,
      locale: config.locale,
      volume: config.voiceVolume
    });
  }
  if (options.refreshTimer && key !== lastAdviceKey) {
    lastAdviceKey = key;
    scheduleAutoHide(adviceMode, data);
  }
}

const PLAN_STATUSES = new Set(["no_advice", "monitoring", "unsupported_hero"]);
const spokenPlans = new Set();

function showPostGame(data) {
  clearTimeout(hideTimer);
  const card = data.post_game;
  // A win gets the green dot; a loss keeps the neutral one (no alarm after the game).
  shell.className = `overlay-shell plan post-game${card.win === true ? " priority-safe" : ""}`;
  labelEl.textContent = card.title;
  const top = [card.hero, card.result, card.score_text].filter(Boolean).join(" · ");
  if (card.hero && window.DotaIcons?.hero(card.hero)) {
    const name = document.createElement("span");
    name.textContent = top;
    priorityEl.replaceChildren(window.DotaIcons.heroPicture(document, card.hero, "sm"), name);
  } else {
    priorityEl.textContent = top;
  }
  actionEl.textContent = card.main;
  reasonEl.textContent = (card.detail || []).join(" ");
  renderStatusRow(data);
  reveal();
  markCard(`post|${card.title}|${card.main}`);
}

const spokenDeaths = new Set();

function showDeathScreen(data) {
  clearTimeout(hideTimer);
  const card = data.death_screen;
  const [first, ...rest] = card.lines;
  shell.className = "overlay-shell plan death-screen coaching";
  labelEl.textContent = card.title;
  priorityEl.textContent = "";
  actionEl.textContent = first;
  reasonEl.textContent = rest.join("\n");
  // The item to buy, as its icon (0.51).
  renderItems(card.items);
  renderStatusRow(data);
  reveal();
  markCard(`death|${card.id || first}`);
  // Read once per death when the voice reads every advice (the id stays while the gold changes).
  const key = `death|${card.id || data.match_death_count || ""}`;
  if (!speaker || spokenDeaths.has(key)) {
    return;
  }
  const spoken = speaker.say({
    key,
    text: card.lines.join(". "),
    fallbackText: Array.isArray(card.lines_en) ? card.lines_en.join(". ") : "",
    adviceMode: "coaching",
    mode: config.voice,
    locale: config.locale,
    volume: config.voiceVolume
  });
  if (spoken === "spoken" || spoken === "spoken_en" || spoken === "off") {
    spokenDeaths.add(key);
  }
}

function showPlan(data) {
  clearTimeout(hideTimer);
  const [first, ...rest] = data.game_plan.lines;
  shell.className = "overlay-shell plan coaching";
  labelEl.textContent = data.game_plan.title || tr("plan");
  const heroName = data.game_plan.hero || "";
  // "Juggernaut · 6–4": the player's record on the hero, when there is one.
  const heroLabel = data.game_plan.record ? `${heroName} · ${data.game_plan.record}` : heroName;
  if (heroName && window.DotaIcons?.hero(heroName)) {
    const name = document.createElement("span");
    name.textContent = heroLabel;
    priorityEl.replaceChildren(window.DotaIcons.heroPicture(document, heroName, "sm"), name);
  } else {
    priorityEl.textContent = heroLabel;
  }
  actionEl.textContent = first;
  reasonEl.textContent = rest.join("\n");
  renderItems(data.game_plan.items);
  renderStatusRow(data);
  reveal();
  markCard(`plan|${heroName}`);
  // Heard once per plan when the voice reads every advice (fullscreen players
  // never see the card).
  const planKey = `plan|${data.game_plan.hero || ""}|${data.game_plan.lines.join("|")}`;
  if (!speaker || spokenPlans.has(planKey)) {
    return;
  }
  const spoken = speaker.say({
    key: planKey,
    text: data.game_plan.lines.join(". "),
    fallbackText: Array.isArray(data.game_plan.lines_en) ? data.game_plan.lines_en.join(". ") : "",
    adviceMode: "coaching",
    mode: config.voice,
    locale: config.locale,
    volume: config.voiceVolume
  });
  // Once per plan, even when advice was spoken in between.
  if (spoken === "spoken" || spoken === "spoken_en" || spoken === "off") {
    spokenPlans.add(planKey);
  }
}

function hintShort(hint) {
  const when = Number.isFinite(hint.in_seconds) ? ` · ${tr("hintIn", Math.max(0, hint.in_seconds))}` : "";
  return `${hint.title}${when}`;
}

function showSample(data) {
  clearTimeout(hideTimer);
  shell.className = "overlay-shell coaching priority-medium sample";
  labelEl.textContent = tr("sample");
  priorityEl.textContent = "";
  actionEl.textContent = tr("sampleAction");
  reasonEl.textContent = tr("sampleReason");
  renderStatusRow(data);
  reveal();
  markCard("sample");
}

// While no advice is on the card, the map hint takes it (not while waiting for data).
function showHint(hint, data) {
  clearTimeout(hideTimer);
  shell.className = "overlay-shell hint coaching";
  labelEl.textContent = hint.label || tr("map");
  priorityEl.textContent = Number.isFinite(hint.in_seconds) ? tr("hintIn", Math.max(0, hint.in_seconds)) : "";
  actionEl.textContent = hint.title;
  // A skill tip: the ability's own icon before its name, as Dota draws it.
  if (hint.icon && window.DotaIcons) {
    const icon = window.DotaIcons.abilityPicture(document, hint.icon, "sm", hint.ability?.name || "");
    icon.classList.add("action-icon");
    actionEl.prepend(icon);
  }
  reasonEl.textContent = hint.hint || "";
  if (Array.isArray(hint.order) && hint.order.length) {
    renderOrder(hint.order, hint.icon);
  } else {
    renderItems(hint.items);
  }
  renderStatusRow(data);
  reveal();
  markCard(`hint|${hint.id || hint.title}`);
}

// The pros' skill order as icons with arrows between them; the one to level
// now is outlined. The reason under it says the same in words.
function renderOrder(order, next) {
  const steps = order.filter((step) => step && step.key).slice(0, 4);
  itemsEl.classList.toggle("hidden", !steps.length || !window.DotaIcons);
  if (!steps.length || !window.DotaIcons) {
    itemsEl.replaceChildren();
    return;
  }
  const cells = [];
  steps.forEach((step, index) => {
    if (index) {
      const arrow = document.createElement("span");
      arrow.className = "order-arrow";
      arrow.textContent = "→";
      cells.push(arrow);
    }
    const icon = window.DotaIcons.abilityPicture(document, step.key, "sm", step.name);
    icon.classList.toggle("is-next", step.key === next);
    cells.push(icon);
  });
  itemsEl.replaceChildren(...cells);
}

// Timers marked "speak" (Tormentor, wisdom shrine) are read once when the voice
// reads every advice: a fullscreen player never sees the card.
function speakHint(hint) {
  if (!speaker || !hint || !hint.speak || spokenHints.has(hint.id)) {
    return;
  }
  const spoken = speaker.say({
    key: `hint|${hint.id}`,
    text: tr("hintSoon", hint.title),
    fallbackText: hint.title_en ? OVERLAY_TEXT.en.hintSoon(hint.title_en) : "",
    adviceMode: "coaching",
    mode: config.voice,
    locale: config.locale,
    volume: config.voiceVolume
  });
  if (spoken === "spoken" || spoken === "spoken_en" || spoken === "off") {
    spokenHints.add(hint.id);
  }
}

const NO_HINT_STATUSES = new Set(["waiting_for_gsi", "stale_gsi", "invalid_state"]);

function showStatus(message, data = {}) {
  if (currentHint && !NO_HINT_STATUSES.has(data.status) && Date.now() >= mutedUntil) {
    showHint(currentHint, data);
    return;
  }
  clearTimeout(hideTimer);
  shell.className = "overlay-shell status";
  labelEl.textContent = statusLabel(data);
  priorityEl.textContent = "";
  actionEl.textContent = message;
  reasonEl.textContent = "";
  renderStatusRow(data);
  reveal();
}

function reveal() {
  shell.classList.remove("hidden");
}

function scheduleAutoHide(adviceMode, data = {}) {
  clearTimeout(hideTimer);
  if (data.is_pinned) {
    return;
  }

  const activeUntil = Date.parse(data.active_advice_until || "");
  const activeDuration = Number.isFinite(activeUntil) ? Math.max(0, activeUntil - Date.now()) : 0;
  const timeout = adviceMode === "urgent"
    ? Number(config.urgentAutoHideMs) || 12000
    : Number(config.autoHideMs) || 8000;
  const visibleFor = Math.max(timeout, activeDuration);
  hideTimer = setTimeout(() => {
    showStatus(tr("listening"));
  }, visibleFor);
}

function statusMessage(data) {
  if (data.suppressed_reason === "duplicate" || data.suppressed_reason === "duplicate_death_review") {
    return tr("noNewAdvice");
  }
  if (data.suppressed_reason === "rate_limit") {
    return tr("paused");
  }
  if (data.suppressed_reason === "cooldown") {
    return tr("watching");
  }
  return data.message || tr("noUrgent");
}

function renderStatusRow(data) {
  const chips = [];
  if (data.demo_mode) {
    chips.push("DEMO REPLAY MODE");
  } else if (data.status === "waiting_for_gsi" || data.status === "stale_gsi") {
    chips.push("WAITING FOR GSI");
  } else if (data.current_mode === "live_gsi" || data.source_type === "live_gsi") {
    chips.push("LIVE GSI MODE");
  }
  const hero = data.hero || "";
  const time = data.simulated_time_label || minuteLabel(data.minute);
  if (hero || time) {
    chips.push([hero, time].filter(Boolean).join(" "));
  }
  if (data.stage) {
    chips.push(data.stage);
  }
  if (Number.isFinite(data.hp_percent)) {
    chips.push(`HP ${data.hp_percent}%`);
  }
  if (Number.isFinite(data.mana_percent)) {
    chips.push(`Mana ${data.mana_percent}%`);
  }
  if (data.gpm !== null && data.gpm !== undefined) {
    chips.push(`GPM ${data.gpm}`);
  }
  if (data.last_hits !== null && data.last_hits !== undefined) {
    chips.push(`LH ${data.last_hits}`);
  }
  if (data.context_confidence) {
    chips.push(`conf ${data.context_confidence}`);
  }
  if (data.source && data.source !== "none") {
    chips.push(data.source);
  }
  if (Array.isArray(data.missing_signals) && data.missing_signals.length) {
    chips.push(`missing ${data.missing_signals.length}`);
  }

  statusRow.replaceChildren();
  if (!chips.length) {
    statusRow.classList.add("hidden");
    return;
  }

  for (const chip of chips.slice(0, 7)) {
    const item = document.createElement("span");
    item.className = "status-chip";
    item.textContent = chip;
    statusRow.appendChild(item);
  }
  statusRow.classList.remove("hidden");
}

function secondsUntil(timestamp) {
  return Math.max(0, Math.ceil((timestamp - Date.now()) / 1000));
}

// Card title: what kind of card this is. Source and mode moved to the
// debug line (Ctrl+Alt+D) to keep the card quiet during a game.
function labelText(adviceMode, data) {
  const kind = adviceMode === "urgent" ? tr("urgent") : tr("tip");
  return data.demo_mode ? `${kind} · ${tr("demo")}` : kind;
}

function statusLabel(data) {
  return data.demo_mode ? `${tr("coach")} · ${tr("demo")}` : tr("coach");
}

function priorityClassName(priority) {
  const value = String(priority || "").toLowerCase();
  if (value === "high" || value === "urgent") {
    return "priority-high";
  }
  if (value === "medium") {
    return "priority-medium";
  }
  if (value === "low") {
    return "priority-low";
  }
  if (value === "safe") {
    return "priority-safe";
  }
  return "";
}

function minuteLabel(minute) {
  const value = Number(minute);
  if (!Number.isFinite(value)) {
    return "";
  }
  return `${String(Math.max(0, Math.floor(value))).padStart(2, "0")}:00`;
}
