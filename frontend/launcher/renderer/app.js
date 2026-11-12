// Control panel: one status line (what is going on + what to do), three
// cards (current match, recent advice, overlay settings) and a collapsed
// "For developers" section with every other tool (service, GSI config, live
// GSI, recordings, replay demos, Deep Review, logs). Texts follow the system
// language (uk/en) sent by the main process as status.locale.

const I18N = window.WardlyAppTexts.create(window.WardlyWhatsNew);

const $ = (selector) => document.querySelector(selector);
const els = {
  service: $("#service"),
  serviceText: $("#service-text"),
  sidePlayer: $("#side-player"),
  sideAvatar: $("#side-avatar"),
  sidePlayerName: $("#side-player-name"),
  status: $("#status"),
  statusTitle: $("#status-title"),
  statusHint: $("#status-hint"),
  statusAction: $("#status-action"),
  statusActionLabel: $("#status-action-label"),
  matchStats: $("#match-body .stats"),
  matchEmpty: $("#match-empty"),
  coverageNote: $("#coverage-note"),
  statHero: $("#stat-hero"),
  statClock: $("#stat-clock"),
  statStage: $("#stat-stage"),
  statData: $("#stat-data"),
  adviceList: $("#advice-list"),
  adviceEmpty: $("#advice-empty"),
  overlayToggle: $("#overlay-toggle"),
  overlayHint: $("#overlay-hint"),
  positionButtons: [...document.querySelectorAll("#position-group [data-position]")],
  positionHint: $("#position-hint"),
  sizeButtons: [...document.querySelectorAll("#size-group [data-size]")],
  overlayTimers: $("#overlay-timers"),
  skillArrows: $("#skill-arrows"),
  skillArrowsCalibrate: $("#skill-arrows-calibrate"),
  skillArrowsHint: $("#skill-arrows-hint"),
  overlayCompact: $("#overlay-compact"),
  languageButtons: [...document.querySelectorAll("#language-group [data-language]")],
  uiScaleButtons: [...document.querySelectorAll("#ui-scale-group [data-scale]")],
  frequencyButtons: [...document.querySelectorAll("#frequency-group [data-frequency]")],
  roleButtons: [...document.querySelectorAll("#role-group [data-role]")],
  roleHint: $("#role-hint"),
  roleNote: $("#role-note"),
  roleMismatch: $("#role-mismatch"),
  roleMismatchText: $("#role-mismatch-text"),
  roleAuto: $("#role-auto"),
  mapHints: $("#map-hints"),
  frequencyHint: $("#frequency-hint"),
  voiceButtons: [...document.querySelectorAll("#voice-group [data-voice]")],
  voiceHint: $("#voice-hint"),
  voiceTest: $("#voice-test"),
  voiceSettings: $("#voice-settings"),
  moveToggle: $("#move-toggle"),
  moveLabel: $("#move-label"),
  moveHint: $("#move-hint"),
  autostart: $("#autostart"),
  discordPresence: $("#discord-presence"),
  discordState: $("#discord-state"),
  weeklyHint: $("#weekly-hint"),
  weeklyForm: $("#weekly-form"),
  weeklyInput: $("#weekly-input"),
  weeklyConnect: $("#weekly-connect"),
  weeklySend: $("#weekly-send"),
  weeklyClear: $("#weekly-clear"),
  autostartHint: $("#autostart-hint"),
  autostartTitle: $("#autostart-title"),
  updateHint: $("#update-hint"),
  updateAction: $("#update-action"),
  updateLabel: $("#update-label"),
  whatsNewCard: $("#whats-new-card"),
  whatsNewHeading: $("#whats-new-heading"),
  whatsNewList: $("#whats-new-list"),
  whatsNewDismiss: $("#whats-new-dismiss"),
  inviteCard: $("#invite-card"),
  statsAskCard: $("#stats-ask-card"),
  statsAskYes: $("#stats-ask-yes"),
  statsAskNo: $("#stats-ask-no"),
  statsAskPrivacy: $("#stats-ask-privacy"),
  inviteCopy: $("#invite-copy"),
  inviteDismiss: $("#invite-dismiss"),
  tourStart: $("#tour-start"),
  nowZone: $("#now-zone"),
  setupCard: $("#setup-card"),
  setupSteps: $("#setup-steps"),
  setupCount: $("#setup-count"),
  setupBar: $("#setup-bar"),
  setupPreview: $("#setup-preview"),
  setupPreviewImg: $("#setup-preview-img"),
  setupDismiss: $("#setup-dismiss"),
  odHint: $("#od-hint"),
  odForm: $("#od-form"),
  odKey: $("#od-key"),
  odSave: $("#od-save"),
  odGet: $("#od-get"),
  odClear: $("#od-clear"),
  reportAction: $("#report-action"),
  backupExport: $("#backup-export"),
  backupImport: $("#backup-import"),
  backupHint: $("#backup-hint"),
  transferHint: $("#transfer-hint"),
  transferCode: $("#transfer-code"),
  transferSend: $("#transfer-send"),
  transferHave: $("#transfer-have"),
  transferForm: $("#transfer-form"),
  transferInput: $("#transfer-input"),
  transferReceive: $("#transfer-receive"),
  reportHint: $("#report-hint"),
  reportOpen: $("#report-open"),
  reportPanel: $("#report-panel"),
  reportNote: $("#report-note"),
  reportCount: $("#report-count"),
  shareStats: $("#share-stats"),
  settingsMore: $("#settings-more"),
  matchRecords: $("#match-records"),
  recordsHint: $("#records-hint"),
  recordsList: $("#records-list"),
  recordsSendPanel: $("#records-send-panel"),
  recordsSendLabel: $("#records-send-label"),
  recordsSendNow: $("#records-send-now"),
  recordsSendCancel: $("#records-send-cancel"),
  recordsSendPrivacy: $("#records-send-privacy"),
  statsHint: $("#stats-hint"),
  statsPreview: $("#stats-preview"),
  statsPreviewText: $("#stats-preview-text"),
  statsPrivacy: $("#stats-privacy"),
  serverDelete: $("#server-delete"),
  reportPreview: $("#report-preview"),
  reportPreviewText: $("#report-preview-text"),
  reportPrivacy: $("#report-privacy"),
  reportSend: $("#report-send"),
  reportCancel: $("#report-cancel"),
  devTools: $("#dev-tools"),
  logs: $("#logs"),
  gsiPath: $("#gsi-path"),
  gsiDetail: $("#gsi-detail")
};
const factEls = {
  backend: $("#backend-status"),
  dota: $("#dota-status"),
  overlay: $("#overlay-status"),
  demo: $("#demo-status"),
  recording: $("#recording-status"),
  gsi: $("#gsi-status"),
  mode: $("#mode-status"),
  llm: $("#llm-status")
};
// «Автоматичні копії» (renderBackups below; init() binds them before the end of this file).
const autoBackupEls = {
  toggle: $("#auto-backup"),
  status: $("#auto-backup-status"),
  list: $("#auto-backup-list"),
  now: $("#auto-backup-now")
};
let lastBackups = null;
let backupsLocale = "";
let backupsLoaded = false;

const liveEls = {
  connection: $("#live-connection"),
  last: $("#live-last"),
  hero: $("#live-hero"),
  time: $("#live-time"),
  stage: $("#live-stage"),
  advice: $("#live-advice"),
  missing: $("#live-missing")
};
const logModeButtons = { clean: $("#log-clean"), verbose: $("#log-verbose") };
const demoStartButtons = ["#run-demo", "#preset-pl", "#preset-jugg", "#deep-review"].map($).filter(Boolean);
const controlButtons = {
  startBackend: $("#start-backend"),
  restartBackend: $("#restart-backend"),
  stopBackend: $("#stop-backend"),
  startOverlay: $("#start-overlay"),
  stopOverlay: $("#stop-overlay"),
  stopDemo: $("#stop-demo"),
  startRecording: $("#start-recording"),
  stopRecording: $("#stop-recording")
};

const DEV_OPEN_KEY = "dota-ai-coach.devToolsOpen";
let locale = "en";
let textsLocale = "";
let gsiEndpoint = "";
let statusAction = null;
let lastVoice = { mode: "off", volume: 1 };
let voiceListChecked = false;
// process.platform of the launcher, from the status ("linux" has its own wording).
let hostPlatform = "";
let openDotaLoaded = false;
// Problem report row: a result message stays until the panel is opened again.
let reportSticky = false;
// A transfer by code is on its way: keep its hint on re-renders.
let transferBusy = false;
// The week in Discord: the answer of the last button press, shown instead of
// the stored state until the next press; the stored state from the status.
let weeklyMessage = "";
let weeklyBusy = false;
let lastWeekly = null;
let reportPreviewLoaded = false;
let settingsSearching = false;
let toastTimer = null;
let serverDeleteArmed = false;
let serverDeleteNote = "";
const seenAdvice = new Set();
const openWhy = new Set();

init();

// ---------------------------------------------------------------------------
// i18n
// ---------------------------------------------------------------------------

function lookup(table, key) {
  return key.split(".").reduce((node, part) => (node ? node[part] : undefined), table);
}

function tr(key, ...args) {
  const resolved = lookup(I18N[locale], key) ?? lookup(I18N.en, key) ?? key;
  return typeof resolved === "function" ? resolved(...args) : resolved;
}

// Like tr() for values that may be missing (backend-provided codes).
function trOr(key, fallback) {
  const value = lookup(I18N[locale], key) ?? lookup(I18N.en, key);
  return typeof value === "string" ? value : fallback;
}

function renderWeekly(state) {
  lastWeekly = state;
  const configured = Boolean(state && state.configured);
  els.weeklyForm.hidden = configured;
  els.weeklySend.hidden = !configured;
  els.weeklyClear.hidden = !configured;
  if (weeklyMessage) {
    els.weeklyHint.textContent = weeklyMessage;
    return;
  }
  if (!configured) {
    // A webhook deleted in Discord was disconnected by the launcher: say why.
    const gone = state && state.last && state.last.code === "webhook_gone";
    els.weeklyHint.textContent = gone ? `${tr("weeklyErrors.webhook_gone")} ${tr("weeklyHint")}` : tr("weeklyHint");
    return;
  }
  const last = state.last;
  const date = last && last.at ? new Date(last.at).toLocaleDateString(locale === "uk" ? "uk-UA" : "en-GB", { day: "numeric", month: "long" }) : "";
  if (last && !last.ok) {
    els.weeklyHint.textContent = trOr(`weeklyErrors.${last.code}`, tr("weeklyErrors.fallback"));
  } else if (last && last.sent) {
    els.weeklyHint.textContent = `${tr("weeklyConnected", state.hint)} ${tr("weeklySent", date)}`;
  } else if (last && !last.manual) {
    els.weeklyHint.textContent = `${tr("weeklyConnected", state.hint)} ${tr("weeklyEmpty", date)}`;
  } else {
    els.weeklyHint.textContent = tr("weeklyConnected", state.hint);
  }
}

function applyStaticTexts() {
  if (textsLocale === locale) {
    return;
  }
  textsLocale = locale;
  document.documentElement.lang = locale;
  for (const element of document.querySelectorAll("[data-i18n]")) {
    element.textContent = tr(element.dataset.i18n);
  }
  for (const element of document.querySelectorAll("[data-i18n-placeholder]")) {
    element.placeholder = tr(element.dataset.i18nPlaceholder);
  }
  for (const element of document.querySelectorAll("[data-i18n-title]")) {
    element.title = tr(element.dataset.i18nTitle);
    element.setAttribute("aria-label", element.title);
  }
  // A field's name for a screen reader (it has no visible label).
  for (const element of document.querySelectorAll("[data-i18n-aria]")) {
    element.setAttribute("aria-label", tr(element.dataset.i18nAria));
  }
  els.backupHint.textContent = tr("backupHint");
  if (!transferBusy && els.transferCode.hidden) {
    els.transferHint.textContent = tr("transferHint");
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

async function init() {
  window.LucideIcons?.hydrate(document);

  bind("#start-backend", () => window.launcherApi.startBackend());
  bind("#stop-backend", () => window.launcherApi.stopBackend());
  bind("#restart-backend", () => window.launcherApi.restartBackend());
  bind("#start-overlay", () => window.launcherApi.startOverlay());
  bind("#stop-overlay", () => window.launcherApi.stopOverlay());
  bind("#run-demo", () => window.launcherApi.runDemo("plMacro"));
  bind("#stop-demo", () => window.launcherApi.stopDemo());
  bind("#preset-pl", () => window.launcherApi.runDemo("plMacro"));
  bind("#preset-jugg", () => window.launcherApi.runDemo("juggSafety"));
  bind("#deep-review", () => window.launcherApi.runDeepReview("plMacro"));
  bind("#open-logs", () => window.launcherApi.openLogs());
  bind("#open-results", () => window.launcherApi.openSimulationResults());
  bind("#open-readme", () => window.launcherApi.openReadme());
  bind("#clear-logs", () => window.launcherApi.clearLogs());
  bind("#copy-logs", () => window.launcherApi.copyLogs());
  bind("#log-clean", () => window.launcherApi.setLogMode("clean"));
  bind("#log-verbose", () => window.launcherApi.setLogMode("verbose"));
  bind("#check-gsi", checkGsi);
  bind("#install-gsi", () => installGsi(els.gsiPath.value));
  bind("#choose-gsi", chooseGsiFolder);
  bind("#check-live-gsi", checkLiveGsi);
  bind("#ops-refresh", refreshOps);
  bind("#start-recording", startLiveRecording);
  bind("#stop-recording", stopLiveRecording);
  bind("#open-records", () => window.launcherApi.openSessionRecords());

  els.sidePlayer.addEventListener("click", () => document.getElementById("tab-profile").click());
  els.statusAction.addEventListener("click", async () => {
    if (!statusAction) {
      return;
    }
    const action = statusAction;
    els.statusAction.disabled = true;
    await run(action.run);
    els.statusAction.disabled = false;
    if (action.doneLabel) {
      flashLabel(els.statusActionLabel, action.doneLabel);
    }
  });
  els.overlayToggle.addEventListener("change", () =>
    run(() => (els.overlayToggle.checked ? window.launcherApi.startOverlay() : window.launcherApi.stopOverlay()))
  );
  for (const button of els.positionButtons) {
    button.addEventListener("click", () =>
      run(async () => renderStatus(await window.launcherApi.setOverlayPosition(button.dataset.position)))
    );
  }
  for (const button of els.languageButtons) {
    button.addEventListener("click", () =>
      run(async () => renderStatus(await window.launcherApi.setLanguage(button.dataset.language)))
    );
  }
  for (const button of els.uiScaleButtons) {
    button.addEventListener("click", () =>
      run(async () => renderStatus(await window.launcherApi.setUiScale(button.dataset.scale)))
    );
  }
  // Ctrl + plus / minus / 0 (main.js): the new size for a moment.
  window.launcherApi.onUiScale?.((scale) => showToast(tr("uiScaleToast", percent(scale))));

  // «Знайти налаштування» (settings-search.js); Ctrl+F on Settings goes to it (the
  // key, not the letter: «а» on a Cyrillic layout), and leaving Settings clears
  // it, so every row is back the next time.
  const settingsView = $("#view-settings");
  const settingsSearch = window.SettingsSearch?.attach({
    view: settingsView,
    input: $("#settings-search"),
    empty: $("#settings-search-empty"),
    onChange: (active) => {
      settingsSearching = active;
    }
  });
  $("#settings-search-clear")?.addEventListener("click", () => {
    settingsSearch?.clear();
    $("#settings-search")?.focus();
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.code === "KeyF" && !settingsView.classList.contains("hidden")) {
      event.preventDefault();
      settingsSearch?.focus();
    }
  });
  new MutationObserver(() => {
    if (settingsView.classList.contains("hidden") && settingsSearch?.active()) {
      settingsSearch.clear();
    }
  }).observe(settingsView, { attributes: true, attributeFilter: ["class"] });
  for (const button of els.sizeButtons) {
    button.addEventListener("click", () =>
      run(async () => renderStatus(await window.launcherApi.setOverlaySize(button.dataset.size)))
    );
  }
  for (const [input, key] of [[els.overlayTimers, "timers"], [els.overlayCompact, "compact"]]) {
    input.addEventListener("change", () =>
      run(async () => renderStatus(await window.launcherApi.setOverlayDisplay({ [key]: input.checked })))
    );
  }
  els.skillArrows.addEventListener("change", () =>
    run(async () => renderStatus(await window.launcherApi.skillArrows(els.skillArrows.checked ? "on" : "off")))
  );
  els.skillArrowsCalibrate.addEventListener("click", () =>
    run(async () => renderStatus(await window.launcherApi.skillArrows("calibrate")))
  );
  for (const button of els.frequencyButtons) {
    button.addEventListener("click", () =>
      run(async () => renderStatus(await window.launcherApi.setAdviceFrequency(button.dataset.frequency)))
    );
  }
  for (const button of els.roleButtons) {
    button.addEventListener("click", () =>
      run(async () => renderStatus(await window.launcherApi.setAdvicePreferences({ role: button.dataset.role })))
    );
  }
  els.roleAuto.addEventListener("click", () =>
    run(async () => renderStatus(await window.launcherApi.setAdvicePreferences({ role: "auto" })))
  );
  els.mapHints.addEventListener("change", () =>
    run(async () => renderStatus(await window.launcherApi.setAdvicePreferences({ mapHints: els.mapHints.checked })))
  );
  for (const button of els.voiceButtons) {
    button.addEventListener("click", () =>
      run(async () => renderStatus(await window.launcherApi.setOverlayVoice(button.dataset.voice)))
    );
  }
  els.voiceTest.addEventListener("click", () => run(testVoice));
  els.voiceSettings.addEventListener("click", () => run(() => window.launcherApi.openSpeechSettings()));
  window.speechSynthesis?.addEventListener?.("voiceschanged", () => renderVoiceHint(lastVoice));
  els.moveToggle.addEventListener("click", () =>
    run(async () => {
      // Pressed = the card is unlocked for dragging; pressing again locks it.
      const moving = els.moveToggle.getAttribute("aria-pressed") === "true";
      renderStatus(await window.launcherApi.setOverlayLocked(moving));
    })
  );
  els.updateAction.addEventListener("click", () =>
    run(async () => {
      if (els.updateAction.dataset.mode === "install") {
        await window.launcherApi.installUpdate();
      } else if (els.updateAction.dataset.mode === "open") {
        await window.launcherApi.openUpdatePage();
      } else {
        renderStatus(await window.launcherApi.checkForUpdates());
      }
    })
  );
  els.odSave.addEventListener("click", () => run(saveOpenDotaKey));
  els.odKey.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      run(saveOpenDotaKey);
    }
  });
  els.odGet.addEventListener("click", () => run(() => window.launcherApi.openAiKeyPage("opendota")));
  els.odClear.addEventListener("click", () =>
    run(async () => {
      await window.launcherApi.player("odClear");
      await refreshOpenDota();
    })
  );
  document.querySelector("#tab-settings")?.addEventListener("click", () => run(refreshOpenDota));
  els.whatsNewDismiss.addEventListener("click", () =>
    run(async () => renderStatus(await window.launcherApi.dismissWhatsNew()))
  );
  // The invite: the link goes to the clipboard, the button says so, then the card goes.
  els.inviteCopy.addEventListener("click", () =>
    run(async () => {
      const status = await window.launcherApi.invite("copy");
      flashLabel(els.inviteCopy.querySelector("span"), tr("inviteCopied"));
      setTimeout(() => renderStatus(status), 1400);
    })
  );
  els.statsAskYes.addEventListener("click", () =>
    run(async () => renderStatus(await window.launcherApi.statsAnswer("yes")))
  );
  els.statsAskNo.addEventListener("click", () =>
    run(async () => renderStatus(await window.launcherApi.statsAnswer("no")))
  );
  els.statsAskPrivacy.addEventListener("click", () => run(() => window.launcherApi.openPrivacy()));
  els.inviteDismiss.addEventListener("click", () =>
    run(async () => renderStatus(await window.launcherApi.invite("dismiss")))
  );
  els.tourStart.addEventListener("click", () => startTour());
  els.setupDismiss.addEventListener("click", () =>
    run(async () => renderStatus(await window.launcherApi.dismissSetup()))
  );
  // History backup: one file with every match and review (no keys), merged back on load.
  const backupButtons = () => [els.backupExport, els.backupImport];
  async function backupRun(action) {
    backupButtons().forEach((button) => (button.disabled = true));
    try {
      const result = await action();
      if (result && result.canceled) {
        els.backupHint.textContent = tr("backupHint");
        return;
      }
      if (result && result.ok) {
        els.backupHint.textContent = result.path
          ? tr("backupSaved", result.matches, result.path.split(/[\\/]/).pop())
          : tr("backupLoaded", result.imported?.matches?.added ?? 0, result.linked);
      } else {
        els.backupHint.textContent = tr(result?.code === "not_backup" ? "backupNotBackup" : result?.code === "newer_version" ? "backupNewer" : result?.code === "restore_failed" ? "backupRestoreFailed" : "backupFailed");
      }
    } finally {
      backupButtons().forEach((button) => (button.disabled = false));
    }
  }
  els.backupExport.addEventListener("click", () => run(() => backupRun(() => window.launcherApi.exportHistory())));
  autoBackupEls.toggle.addEventListener("change", () =>
    run(async () => {
      const result = await window.launcherApi.player("backupSettings", { enabled: autoBackupEls.toggle.checked });
      if (result.ok) {
        renderBackups(result.data);
      }
    })
  );
  autoBackupEls.now.addEventListener("click", () =>
    run(async () => {
      autoBackupEls.now.disabled = true;
      autoBackupEls.status.textContent = tr("autoBackupMaking");
      try {
        const result = await window.launcherApi.player("backupMake");
        await refreshBackups();
        autoBackupEls.status.textContent = tr(result.ok ? "autoBackupMade" : "autoBackupFailed");
      } finally {
        autoBackupEls.now.disabled = false;
      }
    })
  );
  // The same history by a one-time code (main.js sendHistoryByCode / receiveHistoryByCode).
  const transferError = (code) => trOr(`transferErrors.${code}`, tr("transferErrors.fallback"));
  async function transferRun(button, busyText, action) {
    transferBusy = true;
    button.disabled = true;
    els.transferCode.hidden = true;
    els.transferHint.textContent = busyText;
    try {
      await action();
    } finally {
      transferBusy = false;
      button.disabled = false;
    }
  }
  els.transferSend.addEventListener("click", () =>
    run(() =>
      transferRun(els.transferSend, tr("transferSending"), async () => {
        const result = await window.launcherApi.sendHistoryByCode();
        if (result && result.ok) {
          const time = result.expiresAt ? new Date(result.expiresAt).toLocaleTimeString(locale === "uk" ? "uk-UA" : "en-GB", { hour: "2-digit", minute: "2-digit" }) : "—";
          els.transferCode.textContent = result.code;
          els.transferCode.hidden = false;
          els.transferHint.textContent = tr("transferReady", result.matches, time);
        } else {
          els.transferHint.textContent = result?.code === "backend_down" ? tr("backupFailed") : transferError(result?.code);
        }
      })
    )
  );
  // «I have a code» opens the field on the receiving computer; the sending
  // one never needs it, so it stays folded.
  els.transferHave.addEventListener("click", () => {
    const open = els.transferForm.hidden;
    els.transferForm.hidden = !open;
    els.transferHave.setAttribute("aria-expanded", String(open));
    if (open) {
      els.transferInput.focus();
    }
  });
  els.transferForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const code = els.transferInput.value.trim();
    if (!code) {
      els.transferInput.focus();
      return;
    }
    run(() =>
      transferRun(els.transferReceive, tr("transferReceiving"), async () => {
        const result = await window.launcherApi.receiveHistoryByCode(code);
        if (result && result.ok) {
          els.transferInput.value = "";
          els.transferHint.textContent = tr("backupLoaded", result.imported?.matches?.added ?? 0, result.linked);
        } else {
          els.transferHint.textContent = result?.code === "newer_version" ? tr("backupNewer") : result?.code === "restore_failed" ? tr("backupRestoreFailed") : result?.code === "backend_down" ? tr("backupFailed") : transferError(result?.code);
        }
      })
    );
  });
  els.backupImport.addEventListener("click", () => run(() => backupRun(() => window.launcherApi.importHistory())));
  els.reportAction.addEventListener("click", () =>
    run(async () => {
      els.reportAction.disabled = true;
      reportSticky = true;
      setReportHint(tr("reportSaving"));
      try {
        const result = await window.launcherApi.saveProblemReport();
        setReportHint(
          result && result.ok ? tr("reportSaved", result.path.split(/[\\/]/).pop()) : tr("reportFailed"),
          result && result.ok ? result.path : result?.error || ""
        );
      } finally {
        els.reportAction.disabled = false;
      }
    })
  );
  els.reportOpen.addEventListener("click", () => toggleReportPanel(els.reportPanel.hidden));
  els.reportCancel.addEventListener("click", () => toggleReportPanel(false));
  els.reportPreview.addEventListener("toggle", () => {
    if (els.reportPreview.open && !reportPreviewLoaded) {
      reportPreviewLoaded = true;
      els.reportPreviewText.textContent = tr("reportPreviewLoading");
      window.launcherApi
        .previewProblemReport()
        .then((text) => {
          els.reportPreviewText.textContent = text;
        })
        .catch(() => {
          reportPreviewLoaded = false;
          els.reportPreviewText.textContent = tr("reportFailed");
        });
    }
  });
  els.reportNote.addEventListener("input", countReportNote);
  els.reportPrivacy.addEventListener("click", () => run(() => window.launcherApi.openPrivacy()));
  els.reportSend.addEventListener("click", () =>
    run(async () => {
      els.reportSend.disabled = true;
      els.reportCancel.disabled = true;
      setReportHint(tr("reportSending"));
      try {
        const result = await window.launcherApi.sendProblemReport(els.reportNote.value);
        if (result?.ok) {
          setReportHint(tr("reportSentId", result.id));
          reportSticky = true;
          toggleReportPanel(false);
          els.reportNote.value = "";
          countReportNote();
        } else if (result?.queued) {
          setReportHint(tr("reportQueued"));
          reportSticky = true;
          toggleReportPanel(false);
        } else {
          setReportHint(tr("reportRefused", (result?.path || "").split(/[\\/]/).pop()), result?.path || "");
          reportSticky = true;
        }
      } finally {
        els.reportSend.disabled = false;
        els.reportCancel.disabled = false;
      }
    })
  );
  els.matchRecords.addEventListener("change", () =>
    run(async () => {
      renderStatus(await window.launcherApi.setAdvicePreferences({ matchRecords: els.matchRecords.checked }));
      refreshRecords();
    })
  );
  els.recordsList.addEventListener("click", (event) => {
    const send = event.target.closest("button[data-send-record]");
    if (send) {
      openRecordsSend(send.dataset.sendRecord);
      return;
    }
    const button = event.target.closest("button[data-record]");
    if (!button) {
      return;
    }
    button.disabled = true;
    Promise.resolve(window.launcherApi.matchRecords({ save: button.dataset.record }))
      .then((result) => {
        els.recordsHint.textContent = result && result.ok ? tr("recordsSaved") : tr("recordsFailed");
      })
      .catch(() => {
        els.recordsHint.textContent = tr("recordsFailed");
      })
      .finally(() => {
        button.disabled = false;
      });
  });
  els.recordsSendCancel.addEventListener("click", closeRecordsSend);
  els.recordsSendPrivacy.addEventListener("click", () => run(() => window.launcherApi.openPrivacy()));
  els.recordsSendNow.addEventListener("click", () => run(sendPendingRecord));
  els.settingsMore.addEventListener("toggle", () => {
    if (els.settingsMore.open) {
      refreshRecords();
    }
  });
  els.shareStats.addEventListener("change", () =>
    run(async () => {
      serverDeleteNote = "";
      renderStatus(await window.launcherApi.setShareStats(els.shareStats.checked));
    })
  );
  els.statsPreview.addEventListener("toggle", () => {
    if (!els.statsPreview.open) {
      return;
    }
    // Always fresh: the counts change with every match.
    els.statsPreviewText.textContent = tr("statsPreviewLoading");
    Promise.resolve(window.launcherApi.statsPreview())
      .then((result) => {
        els.statsPreviewText.textContent = result && result.ok ? result.text : tr("statsPreviewFailed");
      })
      .catch(() => {
        els.statsPreviewText.textContent = tr("statsPreviewFailed");
      });
  });
  els.statsPrivacy.addEventListener("click", () => run(() => window.launcherApi.openPrivacy()));
  els.serverDelete.addEventListener("click", () =>
    run(async () => {
      // Two presses: the first one asks, for a few seconds.
      if (!serverDeleteArmed) {
        serverDeleteArmed = true;
        els.serverDelete.querySelector("span").textContent = tr("serverDeleteConfirm");
        setTimeout(() => {
          serverDeleteArmed = false;
          els.serverDelete.querySelector("span").textContent = tr("serverDelete");
        }, 5000);
        return;
      }
      serverDeleteArmed = false;
      els.serverDelete.disabled = true;
      try {
        const result = await window.launcherApi.deleteServerData();
        serverDeleteNote = result && result.ok ? tr("serverDeleted") : tr("serverDeleteFailed", (result && result.code) || "?");
        els.serverDelete.querySelector("span").textContent = tr("serverDelete");
        if (result && result.status) {
          renderStatus(result.status);
        }
      } finally {
        els.serverDelete.disabled = false;
      }
    })
  );
  els.discordPresence.addEventListener("change", () =>
    run(async () => renderStatus(await window.launcherApi.setDiscordPresence(els.discordPresence.checked)))
  );
  async function weeklyRun(button, action, url) {
    if (weeklyBusy) {
      return;
    }
    weeklyBusy = true;
    button.disabled = true;
    if (action === "send") {
      weeklyMessage = tr("weeklySending");
      renderWeekly(lastWeekly);
    }
    try {
      const result = await window.launcherApi.discordWeekly(action, url);
      if (result && result.ok) {
        weeklyMessage = action === "send" && !result.sent ? tr("weeklyNoMatchesNow") : "";
        if (action === "set") {
          els.weeklyInput.value = "";
        }
      } else {
        weeklyMessage = trOr(`weeklyErrors.${result?.code}`, tr("weeklyErrors.fallback"));
      }
      if (result && result.status) {
        renderStatus(result.status);
      }
    } finally {
      weeklyBusy = false;
      button.disabled = false;
      renderWeekly(lastWeekly);
    }
  }
  els.weeklyForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const url = els.weeklyInput.value.trim();
    if (!url) {
      els.weeklyInput.focus();
      return;
    }
    run(() => weeklyRun(els.weeklyConnect, "set", url));
  });
  els.weeklySend.addEventListener("click", () => run(() => weeklyRun(els.weeklySend, "send")));
  els.weeklyClear.addEventListener("click", () => run(() => weeklyRun(els.weeklyClear, "clear")));
  els.autostart.addEventListener("change", () =>
    run(async () => {
      await window.launcherApi.setAutostart(els.autostart.checked);
      renderStatus(await window.launcherApi.getStatus());
    })
  );

  // Remember whether the developer section was open (per-user convenience).
  try {
    els.devTools.open = localStorage.getItem(DEV_OPEN_KEY) === "1";
  } catch {
    // Storage unavailable: start collapsed.
  }
  els.devTools.addEventListener("toggle", () => {
    if (els.devTools.open) {
      run(refreshOps);
    }
    // Opened by the settings search for a moment: not the player's choice.
    if (settingsSearching) {
      return;
    }
    try {
      localStorage.setItem(DEV_OPEN_KEY, els.devTools.open ? "1" : "0");
    } catch {
      // Ignore.
    }
  });

  window.launcherApi.onStatus(renderStatus);
  window.launcherApi.onLogs(renderLogs);

  renderLogs(await window.launcherApi.getLogs());
  renderStatus(await window.launcherApi.getStatus());
}

// "Copied" for a moment, then the label the next render gives it.
// ---------------------------------------------------------------------------
// First-run tour (renderer/tour.js draws it; the steps and texts are here)
// ---------------------------------------------------------------------------

// The steps of the first-run tour; `image` is a real advice card shot from the
// overlay (assets/tour/<lang>/, the same pictures as the site).
const TOUR_STEPS = [
  { id: "welcome", view: "home" },
  { id: "card", view: "home", image: "lowhp" },
  { id: "mapline", view: "home", image: "timer" },
  { id: "plan", view: "home", image: "plan" },
  { id: "status", view: "home", target: "#status" },
  { id: "setup", view: "home", target: "#setup-card" },
  { id: "match", view: "home", target: "#match-card" },
  { id: "matches", view: "home", target: "#tab-matches" },
  { id: "progress", view: "home", target: "#tab-progress" },
  { id: "profile", view: "home", target: "#tab-profile" },
  { id: "settings", view: "settings", target: "#overlay-card" },
  { id: "voice", view: "settings", target: "#advice-settings-card" },
  { id: "ai", view: "settings", target: "#ai-settings-root" },
  { id: "help", view: "settings", target: "#help-card" },
  { id: "done", view: "home" }
];

let tourShown = false;
let activeTour = null;

function openTourView(view) {
  const tab = document.querySelector(`#tab-${view}`);
  if (tab && tab.getAttribute("aria-selected") !== "true") {
    tab.click();
  }
}

function startTour() {
  if (activeTour || !window.LauncherTour) {
    return;
  }
  tourShown = true;
  activeTour = window.LauncherTour.start({
    steps: TOUR_STEPS.map((step) => ({
      ...step,
      title: tr(`tour.steps.${step.id}.title`),
      text: tr(`tour.steps.${step.id}.text`),
      image: step.image ? `../assets/tour/${locale === "uk" ? "uk" : "en"}/${step.image}.webp` : undefined
    })),
    labels: {
      next: tr("tour.next"),
      back: tr("tour.back"),
      skip: tr("tour.skip"),
      done: tr("tour.done"),
      count: (i, n) => tr("tour.count", i, n)
    },
    openView: openTourView,
    viewSelector: ".view",
    onClose: () => {
      activeTour = null;
      openTourView("home");
      run(async () => renderStatus(await window.launcherApi.tourDone()));
    }
  });
}

// 1.1 → «110 %» (uk) / “110%” (en).
function percent(value) {
  return new Intl.NumberFormat(locale === "uk" ? "uk-UA" : "en-US", { style: "percent", maximumFractionDigits: 0 }).format(value);
}

// A short note at the bottom of the window, gone in 2 s (the interface size
// after a key press: nothing else on the page names it).
function showToast(text) {
  const toast = $("#toast");
  if (!toast) {
    return;
  }
  toast.textContent = text;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 2000);
}

function flashLabel(element, text) {
  const previous = element.textContent;
  element.textContent = text;
  setTimeout(() => {
    if (element.textContent === text) {
      element.textContent = previous;
    }
  }, 1600);
}

async function run(handler) {
  try {
    return await handler();
  } catch (error) {
    renderLogs(`${els.logs.textContent || ""}\n[renderer] ${error.message || error}\n`);
    return undefined;
  }
}

function bind(selector, handler) {
  const element = $(selector);
  if (element) {
    element.addEventListener("click", () => run(handler));
  }
}

async function checkGsi() {
  updateGsiDetail(await window.launcherApi.checkGsi(els.gsiPath.value));
}

async function installGsi(customPath) {
  updateGsiDetail(await window.launcherApi.installGsi(customPath));
}

async function chooseGsiFolder() {
  const folder = await window.launcherApi.chooseGsiFolder();
  if (folder) {
    els.gsiPath.value = folder;
    await checkGsi();
  }
}

async function checkLiveGsi() {
  renderLiveStatus(await window.launcherApi.checkLiveGsi());
}

async function startLiveRecording() {
  await window.launcherApi.startLiveRecording();
  await checkLiveGsi();
}

async function stopLiveRecording() {
  await window.launcherApi.stopLiveRecording();
  await checkLiveGsi();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

// «Зберігати записи матчів»: the recordings of the last week, newest first,
// each with a button that saves its file to Downloads.
function refreshRecords() {
  if (!els.matchRecords.checked) {
    return;
  }
  Promise.resolve(window.launcherApi.matchRecords("list"))
    .then((result) => renderRecords(result && result.ok ? result : null))
    .catch(() => renderRecords(null));
}

// Sending a recording to the developer: «Send to developer» opens the panel
// with exactly what goes and what does not; only its «Send» uploads, one
// recording per confirmation (services/api POST /v1/session).
let recordsView = { records: [], upload: false, sent: {} };
let pendingRecord = "";

function openRecordsSend(id) {
  const record = recordsView.records.find((row) => row.id === id);
  if (!record || record.active) {
    return;
  }
  pendingRecord = id;
  els.recordsSendLabel.textContent = recordLabel(record);
  els.recordsSendPanel.hidden = false;
  els.recordsSendNow.disabled = false;
  els.recordsSendNow.focus();
}

function closeRecordsSend() {
  pendingRecord = "";
  els.recordsSendPanel.hidden = true;
}

async function sendPendingRecord() {
  const id = pendingRecord;
  if (!id) {
    return;
  }
  els.recordsSendNow.disabled = true;
  els.recordsSendCancel.disabled = true;
  els.recordsHint.textContent = tr("recordsSending");
  try {
    const result = await window.launcherApi.matchRecords({ upload: id });
    if (result && result.ok) {
      recordsView.sent = { ...recordsView.sent, [id]: { id: result.id } };
      closeRecordsSend();
      renderRecords(recordsView);
      els.recordsHint.textContent = tr("recordsSent", result.id);
    } else {
      const errors = tr("recordsSendErrors");
      els.recordsHint.textContent = errors[result && result.code] || errors.failed;
    }
  } catch {
    els.recordsHint.textContent = tr("recordsSendErrors").failed;
  } finally {
    els.recordsSendNow.disabled = false;
    els.recordsSendCancel.disabled = false;
  }
}

function recordLabel(record) {
  const when = record.started_at
    ? new Date(record.started_at).toLocaleString(locale === "uk" ? "uk-UA" : "en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit"
      })
    : "";
  const hero = String(record.hero || "").replace(/^npc_dota_hero_/, "").replace(/_/g, " ");
  const parts = [when, hero];
  if (Number.isFinite(record.minutes)) {
    parts.push(tr("recordsMinutes", record.minutes));
  }
  if (Number.isFinite(record.advice)) {
    parts.push(tr("recordsAdvice", record.advice));
  }
  return parts.filter(Boolean).join(" · ");
}

function renderRecords(view) {
  if (!view || !Array.isArray(view.records)) {
    return;
  }
  const records = view.records;
  recordsView = { records, upload: Boolean(view.upload), sent: view.sent || {} };
  if (pendingRecord && !records.some((row) => row.id === pendingRecord)) {
    closeRecordsSend();
  }
  els.recordsHint.textContent = records.length ? tr("recordsCount", records.length) : tr("recordsEmpty");
  els.recordsList.replaceChildren(
    ...records.map((record) => {
      const item = document.createElement("li");
      item.className = "records-item";
      const label = document.createElement("span");
      label.className = "records-label";
      label.textContent = recordLabel(record);
      const button = document.createElement("button");
      button.className = "btn btn-ghost";
      button.type = "button";
      button.dataset.record = record.id;
      button.textContent = tr("recordsSave");
      const actions = document.createElement("span");
      actions.className = "records-actions";
      const sent = recordsView.sent[record.id];
      if (sent) {
        const badge = document.createElement("span");
        badge.className = "records-sent";
        badge.textContent = tr("recordsSentBadge", sent.id);
        actions.append(badge);
      } else if (recordsView.upload && record.active) {
        // The match is still being written: sent after it ends.
        const wait = document.createElement("span");
        wait.className = "records-sent";
        wait.dataset.recordActive = record.id;
        wait.textContent = tr("recordsActive");
        actions.append(wait);
      } else if (recordsView.upload) {
        const send = document.createElement("button");
        send.className = "btn btn-ghost";
        send.type = "button";
        send.dataset.sendRecord = record.id;
        send.textContent = tr("recordsSend");
        actions.append(send);
      }
      actions.append(button);
      item.append(label, actions);
      return item;
    })
  );
  els.recordsList.hidden = records.length === 0;
}

function renderStatus(status) {
  if (!status) {
    return;
  }
  locale = I18N[status.locale] ? status.locale : "en";
  hostPlatform = status.platform || "";
  applyStaticTexts();
  gsiEndpoint = status.gsiEndpoint || "";
  document.body.dataset.loading = String(isLoading(status));

  renderService(status);
  renderStatusLine(status);
  renderSetup(status);
  renderWhatsNew(status);
  els.inviteCard.classList.toggle("hidden", !status.invite);
  els.statsAskCard.classList.toggle("hidden", !status.statsAsk);
  // «Now» (current match, recent advice) only while Dota runs or there is advice
  // to show; with Dota closed the summary and the week lead.
  const live = status.live || {};
  els.nowZone.classList.toggle(
    "hidden",
    !(status.dotaRunning || live.inMatch || live.connected || (status.recentAdvice || []).length || status.demo === "running")
  );
  if (status.tour && !tourShown) {
    // The first start: the tour opens once the panel has drawn its first status.
    tourShown = true;
    setTimeout(() => startTour(), 400);
  }
  renderReport(status);
  if (status.backend === "running" && !openDotaLoaded) {
    openDotaLoaded = true;
    run(refreshOpenDota);
  }
  renderMatch(status);
  renderAdvice(status);
  renderOverlaySettings(status);
  renderFacts(status);
  if (lastOps && opsLocale !== locale) {
    renderOps(lastOps);
  }
  if (status.backend === "running" && !backupsLoaded) {
    backupsLoaded = true;
    run(refreshBackups);
  } else if (lastBackups && backupsLocale !== locale) {
    renderBackups(lastBackups);
  }
  renderControlButtons(status);
  renderLogMode(status.logMode || "clean");
  updateGsiDetail({ status: status.gsiConfig, path: status.gsiPath });
  // Matches / Progress views (renderer/matches.js).
  window.PlayerViews?.onStatus(status);
}

function setReportHint(text, title = "") {
  els.reportHint.textContent = text;
  els.reportHint.title = title;
}

function renderReport(status) {
  if (reportSticky) {
    return;
  }
  const report = status.report || {};
  const parts = [tr("reportHint")];
  if (report.queued) {
    parts.push(tr("reportQueuedCount", report.queued));
  } else if (report.last?.id) {
    parts.push(tr("reportLast", report.last.id));
  }
  setReportHint(parts.join(". "));
}

// Characters left in the note: a long idea is not cut off without notice.
function countReportNote() {
  els.reportCount.textContent = `${els.reportNote.value.length} / ${els.reportNote.maxLength}`;
}

function toggleReportPanel(open) {
  els.reportPanel.hidden = !open;
  els.reportOpen.setAttribute("aria-expanded", String(open));
  if (open) {
    reportSticky = false;
    reportPreviewLoaded = false;
    els.reportPreview.open = false;
    els.reportPreviewText.textContent = "";
    els.reportNote.focus();
  }
}

// OpenDota key: the backend keeps it and only ever answers with a hint.
async function refreshOpenDota() {
  const result = await window.launcherApi.player("odStatus");
  renderOpenDota(result && result.ok ? result.data : null);
}

function renderOpenDota(data) {
  const configured = Boolean(data && data.configured);
  els.odForm.classList.toggle("hidden", configured);
  els.odClear.classList.toggle("hidden", !configured || data.source !== "app");
  els.odHint.textContent = !configured
    ? tr("odHintOff")
    : data.source === "env"
      ? tr("odHintEnv")
      : tr("odHintOn", data.key_hint || "");
}

async function saveOpenDotaKey() {
  const key = els.odKey.value.trim();
  if (!key) {
    return;
  }
  els.odSave.disabled = true;
  try {
    const result = await window.launcherApi.player("odSave", { apiKey: key });
    if (result && result.ok) {
      els.odKey.value = "";
      renderOpenDota(result.data);
    } else {
      els.odHint.textContent = tr("odBad");
    }
  } finally {
    els.odSave.disabled = false;
  }
}

// First-run checklist: the required steps in order, then the optional AI coach.
// Hidden once the required steps are done or the player hides it.
function setupSteps(status) {
  const player = status.player || {};
  // Data from the game proves Dota and the config work, wherever Dota lives.
  const dataSeen = Boolean(status.setup?.gsiSeen || status.live?.connected);
  return [
    { id: "service", done: status.backend === "running" },
    { id: "dota", done: Boolean(status.dotaDir || status.dotaRunning || dataSeen), action: () => window.launcherApi.chooseDotaFolder() },
    { id: "gsi", done: status.gsiConfig === "installed" || dataSeen, action: () => window.launcherApi.installGsi("") },
    // Shown only when Steam's saved settings could be read.
    ...(status.launchOption === "ok" || status.launchOption === "missing"
      ? [{ id: "launch", done: status.launchOption === "ok" || dataSeen, action: () => window.launcherApi.copyLaunchOption() }]
      : []),
    // While waiting for Dota: the sample advice card over the screen (the overlay unlocked), to see and place it.
    // Only with the overlay on: a switched-off overlay shows no card, and the player chose that.
    ...(status.overlay === "running"
      ? [{ id: "preview", done: Boolean(status.setup?.previewed), optional: true, action: () => window.launcherApi.setOverlayLocked(false) }]
      : []),
    // One click starts Dota 2 through Steam (not while it already runs: then it needs a restart).
    { id: "data", done: dataSeen, action: status.dotaRunning ? null : () => window.launcherApi.launchDota() },
    { id: "account", done: Boolean(player.linked), action: () => window.PlayerViews?.setView("matches") },
    {
      id: "ai",
      done: Boolean(player.aiConfigured),
      optional: true,
      action: () => {
        window.PlayerViews?.setView("settings");
        document.getElementById("ai-settings-root")?.scrollIntoView({ block: "start" });
      }
    }
  ];
}

function renderWhatsNew(status) {
  const version = String(status.whatsNew || "");
  const table = (I18N[locale] || I18N.en).whatsNew || {};
  const versions = version ? window.WardlyWhatsNew.versions(table, version, String(status.whatsNewFrom || "")) : [];
  const show = versions.includes(version);
  els.whatsNewCard.classList.toggle("hidden", !show);
  const signature = `${locale}|${versions.join(",")}`;
  if (!show || els.whatsNewList.dataset.signature === signature) {
    return;
  }
  els.whatsNewList.dataset.signature = signature;
  els.whatsNewHeading.textContent = tr("whatsNewTitle", version);
  const items = [];
  for (const each of versions) {
    if (each !== version) {
      const label = document.createElement("li");
      label.className = "whats-new-version";
      label.textContent = tr("whatsNewAlso", each);
      items.push(label);
    }
    for (const text of table[each]) {
      const item = document.createElement("li");
      item.textContent = text;
      items.push(item);
    }
  }
  els.whatsNewList.replaceChildren(...items);
}

function renderSetup(status) {
  const steps = setupSteps(status);
  const required = steps.filter((step) => !step.optional);
  const doneCount = required.filter((step) => step.done).length;
  const hide = isLoading(status) || status.setup?.dismissed || doneCount === required.length;
  els.setupCard.classList.toggle("hidden", Boolean(hide));
  els.setupPreview.classList.toggle("hidden", Boolean(hide));
  if (hide) {
    return;
  }
  els.setupCount.textContent = tr("setupCount", doneCount, required.length);
  els.setupBar.style.width = `${Math.round((doneCount / Math.max(1, required.length)) * 100)}%`;
  const preview = `../assets/tour/${locale === "uk" ? "uk" : "en"}/lowhp.webp`;
  if (!els.setupPreviewImg.src.endsWith(preview.slice(2))) {
    els.setupPreviewImg.src = preview;
  }
  // The first open required step gets the action (optional ones keep theirs); later ones wait for it.
  const next = steps.find((step) => !step.done && !step.optional);
  const signature = JSON.stringify([locale, steps.map((step) => step.done), next?.id]);
  if (els.setupSteps.dataset.signature === signature) {
    return;
  }
  els.setupSteps.dataset.signature = signature;
  // Numbers count the required steps only (the optional ones carry an icon).
  const numbers = new Map(required.map((step, index) => [step, index + 1]));
  els.setupSteps.replaceChildren(
    ...steps.map((step) => {
      const [title, hint] = tr(`setup.${step.id}`);
      const item = document.createElement("li");
      item.className = "setup-step";
      item.dataset.done = String(step.done);
      item.dataset.current = String(step === next);
      // A done step is a check; an open required one shows its number (the next
      // one in red); the optional one is not counted in «3 of 6», so no number.
      const numbered = !step.done && !step.optional;
      const mark = document.createElement(numbered ? "span" : "i");
      mark.className = "setup-mark";
      if (numbered) {
        mark.textContent = String(numbers.get(step));
      } else {
        mark.dataset.icon = step.done ? "circle-check" : "sparkles";
      }
      const text = document.createElement("span");
      text.className = "setup-text";
      const titleEl = document.createElement("span");
      titleEl.className = "setup-step-title";
      titleEl.textContent = title;
      text.append(titleEl);
      if (!step.done) {
        const hintEl = document.createElement("span");
        hintEl.className = "setup-step-hint";
        hintEl.textContent = hint;
        text.append(hintEl);
      }
      item.append(mark, text);
      if (!step.done && step.action && (step === next || step.optional)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = step === next && !step.optional ? "btn btn-primary btn-sm" : "btn btn-sm";
        button.textContent = tr(`setupActions.${step.id}`);
        button.addEventListener("click", async () => {
          await run(step.action);
          if (step.id === "launch") {
            flashLabel(button, tr("actions.copied"));
          }
        });
        item.append(button);
      }
      return item;
    })
  );
  window.LucideIcons?.hydrate(els.setupSteps);
}

function isLoading(status) {
  return status.backend === "starting";
}

function isOffline(status) {
  return status.backend === "stopped" || status.backend === "stopping";
}

function renderService(status) {
  const state = status.backend || "stopped";
  els.service.dataset.state = state;
  // The port is a developer's detail (also under «Для розробника»): a tooltip here.
  els.serviceText.textContent = `${tr("service")} ${tr(`serviceStates.${state}`)}`;
  els.service.title = status.backendPort && state === "running" ? `127.0.0.1:${status.backendPort}` : "";
  renderSidePlayer(status.player);
}

// The linked player at the foot of the side navigation: the Steam avatar (the
// first letter while there is none) and the name; a click opens Profile.
function renderSidePlayer(player) {
  const name = player && player.linked ? player.name : null;
  els.sidePlayer.classList.toggle("hidden", !name);
  if (!name || (els.sidePlayer.dataset.name === name && els.sidePlayer.dataset.avatar === (player.avatar || ""))) {
    return;
  }
  els.sidePlayer.dataset.name = name;
  els.sidePlayer.dataset.avatar = player.avatar || "";
  els.sidePlayerName.textContent = name;
  els.sidePlayer.title = name;
  const letter = document.createTextNode(Array.from(name.trim())[0]?.toUpperCase() || "?");
  if (player.avatar) {
    const img = document.createElement("img");
    img.alt = "";
    img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => img.replaceWith(letter));
    img.src = player.avatar;
    els.sideAvatar.replaceChildren(img);
  } else {
    els.sideAvatar.replaceChildren(letter);
  }
}

// The hero's art behind the current match card (styles.css .art-card).
function setMatchArt(art) {
  const card = document.getElementById("match-card");
  card.querySelector(":scope > .dota-hero-art")?.remove();
  card.classList.toggle("art-card", Boolean(art));
  if (art) {
    card.prepend(art);
  }
}

function formatClock(seconds) {
  if (!Number.isFinite(seconds)) {
    return "";
  }
  const sign = seconds < 0 ? "−" : "";
  const total = Math.abs(Math.trunc(seconds));
  return `${sign}${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function stageLabel(stage) {
  return trOr(`stages.${stage}`, stage);
}

// Decide the single status line and its one action.
function resolveStatusLine(status) {
  const live = status.live || {};
  const api = window.launcherApi;
  const actions = {
    start: { label: tr("actions.start"), icon: "play", run: () => api.startBackend() },
    install: { label: tr("actions.install"), icon: "download", run: () => installGsi("") },
    chooseDota: { label: tr("actions.chooseDota"), icon: "folder-search", run: () => api.chooseDotaFolder() },
    fullscreenSeen: { label: tr("actions.fullscreenSeen"), icon: "eye", run: () => api.dismissFullscreenWarning() },
    copyLaunchOption: { label: tr("actions.copyLaunchOption"), icon: "copy", run: () => api.copyLaunchOption(), doneLabel: tr("actions.copied") }
  };

  if (isLoading(status)) {
    return { state: "loading", title: tr("status.loadingTitle"), hint: tr("status.loadingHint") };
  }
  if (isOffline(status)) {
    return { state: "error", title: tr("status.backendDownTitle"), hint: tr("status.backendDownHint"), action: actions.start };
  }
  if (status.demo === "running") {
    return { state: "ok", title: tr("status.demoTitle", status.demoPreset), hint: tr("status.demoHint") };
  }
  if (status.gsiConfig === "error") {
    return { state: "error", title: tr("status.gsiErrorTitle"), hint: tr("status.gsiErrorHint"), action: actions.chooseDota };
  }
  if (status.gsiConfig !== "installed") {
    return status.dotaDir
      ? { state: "warn", title: tr("status.noGsiTitle"), hint: tr("status.noGsiHint"), action: actions.install }
      : { state: "error", title: tr("status.noDotaTitle"), hint: tr("status.noDotaHint"), action: actions.chooseDota };
  }
  if (status.dotaFullscreen) {
    // Sent only while Dota runs in exclusive fullscreen with the overlay on.
    return {
      state: "warn",
      title: tr("status.fullscreenTitle"),
      hint: tr(status.platform === "linux" ? "status.fullscreenHintLinux" : "status.fullscreenHint"),
      action: actions.fullscreenSeen
    };
  }
  if (live.inMatch) {
    const hint = status.overlay === "running" ? tr("status.inGameHint") : tr("status.inGameOverlayOff");
    return { state: "ok", title: tr("status.inGameTitle", live.hero, formatClock(live.clockTime)), hint };
  }
  if (!status.dotaRunning) {
    return { state: "idle", title: tr("status.notRunningTitle"), hint: tr("status.notRunningHint") };
  }
  if (!live.connected && status.launchOption === "missing") {
    // Dota runs, the config is there, but nothing arrives: the usual cause.
    return { state: "warn", title: tr("status.launchOptionTitle"), hint: tr("status.launchOptionHint"), action: actions.copyLaunchOption };
  }
  // Dota runs outside a match: say plainly whether its data reaches the coach.
  return live.connected
    ? { state: "ok", title: tr("status.connectedTitle"), hint: tr("status.waitingHintConnected") }
    : { state: "warn", title: tr("status.noDataTitle"), hint: tr("status.waitingHintNoData") };
}

function renderStatusLine(status) {
  const line = resolveStatusLine(status);
  els.status.dataset.state = line.state;
  els.statusTitle.textContent = line.title;
  els.statusHint.textContent = line.hint || "";
  statusAction = line.action || null;
  els.statusAction.classList.toggle("hidden", !statusAction);
  if (statusAction) {
    els.statusActionLabel.textContent = statusAction.label;
    const icon = els.statusAction.querySelector("i[data-icon]");
    icon.dataset.icon = statusAction.icon;
    window.LucideIcons?.hydrate(els.statusAction);
  }
}

function skeleton(widthClass) {
  const span = document.createElement("span");
  span.className = `skeleton skeleton-line ${widthClass}`;
  return span;
}

function setEmpty(container, visible, { title, hint, icon } = {}) {
  container.classList.toggle("hidden", !visible);
  if (!visible) {
    return;
  }
  const iconEl = container.querySelector("i[data-icon]");
  if (icon && iconEl && iconEl.dataset.icon !== icon) {
    iconEl.dataset.icon = icon;
    window.LucideIcons?.hydrate(container);
  }
  if (title !== undefined) {
    container.querySelector(".empty-title").textContent = title;
  }
  if (hint !== undefined) {
    container.querySelector(".empty-hint").textContent = hint;
  }
}

function renderMatch(status) {
  const live = status.live || {};
  if (isLoading(status)) {
    els.matchStats.classList.remove("hidden");
    setEmpty(els.matchEmpty, false);
    delete els.statHero.dataset.hero;
    els.statHero.replaceChildren(skeleton("w-70"));
    els.statClock.replaceChildren(skeleton("w-40"));
    els.statStage.replaceChildren(skeleton("w-60"));
    els.statData.replaceChildren(skeleton("w-50"));
    return;
  }
  els.coverageNote.classList.add("hidden");
  els.roleNote.classList.add("hidden");
  if (isOffline(status)) {
    els.matchStats.classList.add("hidden");
    setEmpty(els.matchEmpty, true, { title: tr("offlineTitle"), hint: tr("offlineHint"), icon: "wifi-off" });
    return;
  }
  if (!live.inMatch) {
    els.matchStats.classList.add("hidden");
    setEmpty(els.matchEmpty, true, { title: tr("matchEmptyTitle"), hint: tr("matchEmptyHint"), icon: "clock" });
    return;
  }
  els.matchStats.classList.remove("hidden");
  setEmpty(els.matchEmpty, false);
  const coverageKey = live.coverage === "safety" ? "coverageSafety" : live.coverage === "support" ? "coverageSupport" : null;
  els.coverageNote.classList.toggle("hidden", !coverageKey);
  if (coverageKey) {
    els.coverageNote.textContent = tr(coverageKey);
  }
  const role = live.role && tr(`roleNames.${live.role.role}`);
  els.roleNote.classList.toggle("hidden", !live.role);
  els.roleNote.textContent = live.role ? tr("roleNote", role, tr(`roleSource.${live.role.source}`)) : "";
  const mismatch = live.role && live.role.mismatch;
  els.roleMismatch.classList.toggle("hidden", !mismatch);
  els.roleMismatchText.textContent = mismatch
    ? tr("roleMismatch", role, tr(`roleNames.${live.role.mismatch}`))
    : "";
  if (live.hero && window.DotaIcons?.hero(live.hero)) {
    // Keep the element while the hero stays the same (no flicker every second).
    if (els.statHero.dataset.hero !== live.hero) {
      els.statHero.dataset.hero = live.hero;
      const name = document.createElement("span");
      name.textContent = live.hero;
      const label = document.createElement("span");
      label.className = "with-pic";
      label.append(window.DotaIcons.heroPicture(document, live.hero, "sm"), name);
      els.statHero.replaceChildren(label);
      setMatchArt(window.DotaIcons.heroArt?.(document, live.hero) || null);
    }
  } else {
    delete els.statHero.dataset.hero;
    els.statHero.textContent = live.hero || "—";
    setMatchArt(null);
  }
  els.statClock.textContent = formatClock(live.clockTime) || "—";
  els.statStage.textContent = live.stage && live.stage !== "unknown" ? stageLabel(live.stage) : "—";
  // Whole seconds: Dota sends data several times a second, «0.4 s» says nothing more.
  const seconds = Number.isFinite(live.secondsSinceLastGsi) ? Math.round(live.secondsSinceLastGsi) : null;
  const dot = document.createElement("span");
  dot.className = "dot";
  dot.dataset.tone = live.connected ? "ok" : "warn";
  const text = document.createElement("span");
  text.className = "num";
  text.textContent = seconds === null ? "—" : seconds < 2 ? tr("dataFreshNow") : tr("dataFresh", seconds);
  els.statData.replaceChildren(dot, text);
}

function priorityTone(priority) {
  const value = String(priority || "").toLowerCase();
  if (value === "high" || value === "urgent") {
    return "error";
  }
  if (value === "medium") {
    return "warn";
  }
  if (value === "low" || value === "safe") {
    return "ok";
  }
  return "";
}

function renderAdvice(status) {
  if (isLoading(status)) {
    els.adviceEmpty.classList.add("hidden");
    els.adviceList.classList.remove("hidden");
    els.adviceList.replaceChildren(
      ...["w-80", "w-60", "w-70"].map((width) => {
        const item = document.createElement("li");
        item.className = "advice-item";
        item.append(skeleton(width));
        return item;
      })
    );
    return;
  }
  const items = Array.isArray(status.recentAdvice) ? status.recentAdvice : [];
  const offline = isOffline(status);
  if (offline || !items.length) {
    els.adviceList.classList.add("hidden");
    els.adviceList.replaceChildren();
    setEmpty(els.adviceEmpty, true, {
      title: offline ? tr("offlineTitle") : tr("adviceEmptyTitle"),
      hint: offline ? tr("offlineHint") : tr("adviceEmptyHint"),
      icon: offline ? "wifi-off" : "sparkles"
    });
    return;
  }
  els.adviceEmpty.classList.add("hidden");
  els.adviceList.classList.remove("hidden");
  const firstRender = seenAdvice.size === 0;
  els.adviceList.replaceChildren(
    ...items.map((advice) => {
      const key = `${advice.timestamp}|${advice.action}`;
      const item = document.createElement("li");
      item.className = "advice-item";
      if (!firstRender && !seenAdvice.has(key)) {
        item.classList.add("is-new");
      }
      seenAdvice.add(key);

      const dot = document.createElement("span");
      dot.className = "dot";
      const tone = priorityTone(advice.priority);
      if (tone) {
        dot.dataset.tone = tone;
      }
      const priority = String(advice.priority || "").toLowerCase();
      dot.title = trOr(`priority.${priority}`, priority);

      const action = document.createElement("span");
      action.className = "advice-action";
      action.textContent = advice.action || "";
      action.title = advice.action || "";

      const time = document.createElement("span");
      time.className = "advice-time";
      time.textContent = advice.game_time || "";

      const reason = document.createElement("span");
      reason.className = "advice-reason";
      reason.textContent = advice.reason || "";
      reason.title = advice.reason || "";

      item.append(dot, action, time, reason);
      // What the coach saw (backend advice_why.py), folded: the list redraws
      // every second, so the open ones are remembered by key.
      if (advice.why) {
        const why = document.createElement("details");
        why.className = "advice-why";
        why.open = openWhy.has(key);
        why.addEventListener("toggle", () => (why.open ? openWhy.add(key) : openWhy.delete(key)));
        const summary = document.createElement("summary");
        summary.textContent = tr("adviceWhy");
        const text = document.createElement("p");
        text.textContent = advice.why;
        why.append(summary, text);
        item.append(why);
      }
      return item;
    })
  );
}

function renderOverlaySettings(status) {
  const enabled = status.overlay === "running";
  els.overlayToggle.checked = enabled;
  els.overlayHint.textContent = !enabled
    ? tr("overlayReason.off")
    : status.overlayVisible
      ? tr("overlayReason.in_game")
      : tr(`overlayReason.${status.overlayReasonCode || "no_match"}`);

  const position = status.overlayPosition || "right-center";
  for (const button of els.positionButtons) {
    button.setAttribute("aria-checked", String(button.dataset.position === position));
    button.disabled = !enabled;
  }
  els.positionHint.textContent = position === "custom" ? tr("positionCustom") : tr("positionHint");

  const language = status.language || "auto";
  for (const button of els.languageButtons) {
    button.setAttribute("aria-checked", String(button.dataset.language === language));
  }
  const scale = Number(status.uiScale) || 1;
  for (const button of els.uiScaleButtons) {
    button.setAttribute("aria-checked", String(Number(button.dataset.scale) === scale));
    button.firstElementChild.textContent = percent(Number(button.dataset.scale));
  }

  const size = status.overlaySize || "normal";
  for (const button of els.sizeButtons) {
    button.setAttribute("aria-checked", String(button.dataset.size === size));
    button.disabled = !enabled;
  }

  const display = status.overlayDisplay || { timers: true, compact: false };
  els.overlayTimers.checked = display.timers !== false;
  els.overlayCompact.checked = display.compact === true;
  els.overlayTimers.disabled = !enabled;
  els.overlayCompact.disabled = !enabled;

  // Skill arrows: on until switched off, drawn once the frame is laid.
  const arrows = status.skillArrows || { enabled: true, manual: false };
  els.skillArrows.checked = arrows.enabled !== false;
  els.skillArrows.disabled = !enabled;
  els.skillArrowsCalibrate.disabled = !enabled || arrows.calibrating === true;
  els.skillArrowsHint.textContent = tr(
    `skillArrowsHint.${arrows.enabled === false ? "off" : arrows.manual ? "manual" : "on"}`
  );

  const frequency = status.adviceFrequency || "normal";
  for (const button of els.frequencyButtons) {
    button.setAttribute("aria-checked", String(button.dataset.frequency === frequency));
  }
  els.frequencyHint.textContent = tr(`frequencyHint.${frequency}`);

  const role = status.adviceRole || "auto";
  for (const button of els.roleButtons) {
    button.setAttribute("aria-checked", String(button.dataset.role === role));
  }
  els.roleHint.textContent = tr(`roleHint.${role}`);
  els.mapHints.checked = status.mapHints !== false;

  lastVoice = status.overlayVoice || { mode: "off", volume: 1 };
  for (const button of els.voiceButtons) {
    button.setAttribute("aria-checked", String(button.dataset.voice === lastVoice.mode));
    button.disabled = !enabled;
  }
  els.voiceTest.disabled = !enabled;
  renderVoiceHint(lastVoice);

  const moving = status.overlayLocked === false;
  els.moveToggle.setAttribute("aria-pressed", String(moving));
  els.moveToggle.disabled = !enabled;
  els.moveLabel.textContent = moving ? tr("moveDone") : tr("moveStart");
  els.moveHint.textContent = moving ? tr("moveActiveHint") : tr("moveHint");

  els.matchRecords.checked = Boolean(status.matchRecords);
  if (!status.matchRecords) {
    els.recordsHint.textContent = tr("recordsOff");
    els.recordsList.hidden = true;
    closeRecordsSend();
  }
  els.shareStats.checked = Boolean(status.shareStats);
  const statsDate = status.statsSentAt
    ? new Date(status.statsSentAt).toLocaleDateString(locale === "uk" ? "uk-UA" : "en-GB", { day: "numeric", month: "long" })
    : "";
  els.statsHint.textContent =
    serverDeleteNote || (!status.shareStats ? tr("statsOff") : statsDate ? tr("statsSent", statsDate) : tr("statsOn"));

  els.discordPresence.checked = status.discordPresence !== false;
  const discordState = status.discordState || { state: "idle" };
  // "Waiting for Dota" repeats the hint above: only the other states are shown.
  els.discordState.hidden = status.discordPresence === false || discordState.state === "idle";
  els.discordState.textContent =
    discordState.state === "rejected"
      ? tr("discordStates.rejected", discordState.error || "?")
      : trOr(`discordStates.${discordState.state}`, tr("discordStates.idle"));
  renderWeekly(status.discordWeekly || null);
  els.autostartTitle.dataset.i18n = status.platform === "linux" ? "autostartLinux" : "autostart";
  els.autostartTitle.textContent = tr(els.autostartTitle.dataset.i18n);
  els.autostart.checked = Boolean(status.autostart);
  els.autostart.disabled = !status.autostartSupported;
  els.autostartHint.textContent = !status.autostartSupported
    ? tr("autostartUnavailable")
    : status.autostart
      ? tr("autostartOn")
      : tr("autostartOff");

  renderUpdate(status);
}

// The overlay speaks with the system voices; the panel checks which one it
// will use (the UI language, else English with the English original) and
// plays a sample.
function systemSpeech() {
  return window.OverlayVoice && window.speechSynthesis
    ? window.OverlayVoice.speechChoice(
        window.speechSynthesis.getVoices(),
        locale,
        tr("voiceSample"),
        lookup(I18N.en, "voiceSample")
      )
    : null;
}

function renderVoiceHint(voice) {
  const mode = voice?.mode || "off";
  const choice = systemSpeech();
  const missing = mode !== "off" && voiceListLoaded() && (!choice || choice.fallback);
  // «Add a voice» opens Windows Settings: Linux has no such page, only the hint.
  els.voiceSettings.classList.toggle("hidden", !missing || hostPlatform === "linux");
  if (missing) {
    els.voiceHint.textContent = choice ? tr(voiceKey("voiceEnglishFallback"), choice.voice.name) : tr(voiceKey("voiceNoVoice"));
    return;
  }
  els.voiceHint.textContent = [tr(`voiceHint.${mode}`), mode !== "off" && choice ? choice.voice.name : ""]
    .filter(Boolean)
    .join(" · ");
}

// Chromium fills the voice list asynchronously: an empty list right after
// start does not yet mean there are no voices.
function voiceKey(key) {
  return hostPlatform === "linux" ? `${key}Linux` : key;
}

function voiceListLoaded() {
  return (window.speechSynthesis?.getVoices() || []).length > 0 || voiceListChecked;
}

function testVoice() {
  const choice = systemSpeech();
  if (!choice) {
    voiceListChecked = true;
    els.voiceHint.textContent = tr(voiceKey("voiceNoVoice"));
    els.voiceSettings.classList.toggle("hidden", hostPlatform === "linux");
    return;
  }
  const { voice } = choice;
  const utterance = new window.SpeechSynthesisUtterance(choice.text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  utterance.volume = Number(lastVoice.volume ?? 1);
  utterance.rate = 1.05;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

function renderUpdate(status) {
  const update = status.update || { status: "disabled" };
  const current = status.appVersion || update.currentVersion || "";
  const known = ["disabled", "idle", "checking", "up-to-date", "available", "downloading", "ready", "error"];
  const state = known.includes(update.status) ? update.status : "idle";
  // Installing restarts the app, so it is never offered while Dota runs (nor
  // the download page of a package that is installed by hand).
  const blocked = (state === "ready" || state === "available") && Boolean(update.blockedByGame);
  const hintKey = blocked ? (state === "available" ? "availableBlocked" : "blocked") : state === "idle" && update.mode === "notify" ? "idleNotify" : state;
  els.updateHint.textContent = tr(`updateHint.${hintKey}`, current, update.version || "", update.percent || 0);
  els.updateHint.title = state === "error" ? update.error || "" : "";
  const install = state === "ready";
  const open = state === "available";
  els.updateAction.dataset.mode = install ? "install" : open ? "open" : "check";
  els.updateAction.classList.toggle("btn-primary", install || open);
  els.updateLabel.textContent = install ? tr("updateInstall") : open ? tr("updateOpen") : tr("updateCheck");
  els.updateAction.disabled = blocked || state === "disabled" || state === "checking" || state === "downloading";
}

function renderFacts(status) {
  const backendPort = status.backendPort && status.backend !== "stopped" ? ` · :${status.backendPort}` : "";
  factEls.backend.textContent = `${tr(`serviceStates.${status.backend || "stopped"}`)}${backendPort}`;
  factEls.dota.textContent = tr(`dotaStates.${status.dota || "not_found"}`);
  factEls.overlay.textContent = status.overlay !== "running" ? tr("off") : status.overlayVisible ? tr("shown") : tr("hidden");
  factEls.overlay.title = status.overlayReason || "";
  factEls.demo.textContent = status.demo === "running"
    ? [tr("running"), status.demoPreset].filter(Boolean).join(" · ")
    : tr("stopped");
  factEls.recording.textContent = status.recording === "running" ? tr("running") : tr("stopped");
  factEls.gsi.textContent = tr(`gsiConfigStates.${status.gsiConfig || "unknown"}`);
  factEls.mode.textContent = trOr(`modes.${status.mode || "Live GSI"}`, status.mode || "Live GSI");
  factEls.llm.textContent = status.llm === "on" ? tr("on") : tr("off");
}

function isActiveProcess(state) {
  return state === "running" || state === "starting";
}

function renderControlButtons(status) {
  const backendRunning = isActiveProcess(status.backend);
  const overlayRunning = isActiveProcess(status.overlay);
  const demoRunning = isActiveProcess(status.demo);
  const recordingRunning = isActiveProcess(status.recording);

  controlButtons.startBackend.disabled = backendRunning;
  controlButtons.restartBackend.disabled = status.backend === "starting" || status.backend === "stopping";
  controlButtons.stopBackend.disabled = !backendRunning;
  controlButtons.startOverlay.disabled = overlayRunning;
  controlButtons.stopOverlay.disabled = !overlayRunning;
  controlButtons.stopDemo.disabled = !demoRunning;
  controlButtons.startRecording.disabled = recordingRunning;
  controlButtons.stopRecording.disabled = !recordingRunning;
  for (const button of demoStartButtons) {
    button.disabled = demoRunning;
    button.title = demoRunning ? tr("demoBusy") : "";
  }
}

function renderLogMode(mode) {
  for (const [name, button] of Object.entries(logModeButtons)) {
    button?.setAttribute("aria-checked", String(name === mode));
  }
}

function updateGsiDetail(result = {}) {
  if (result.path) {
    els.gsiDetail.textContent = tr("gsiPath", result.path, gsiEndpoint);
  } else if (result.status === "not found") {
    els.gsiDetail.textContent = `${tr("gsiPathMissing")}\n${tr("gsiEndpoint", gsiEndpoint)}`;
  } else {
    els.gsiDetail.textContent = tr("gsiEndpoint", gsiEndpoint);
  }
}

function renderLiveStatus(status = {}) {
  const setValue = (element, text, state) => {
    element.textContent = text;
    element.dataset.state = state || "";
  };
  if (status.error) {
    setValue(liveEls.connection, tr("liveUnavailable"), "bad");
    liveEls.advice.textContent = status.error;
    return;
  }
  setValue(liveEls.connection, status.gsi_connected ? tr("liveConnected") : tr("liveWaiting"), status.gsi_connected ? "good" : "bad");
  setValue(liveEls.last, status.seconds_since_last_gsi == null ? "—" : `${status.seconds_since_last_gsi} s`);
  setValue(liveEls.hero, status.hero || "—");
  setValue(liveEls.time, Number.isFinite(status.clock_time) ? formatClock(status.clock_time) : String(status.game_time ?? "—"));
  setValue(liveEls.stage, status.stage ? stageLabel(status.stage) : "—");
  liveEls.advice.textContent = status.current_advice
    ? tr("liveAdvice", status.current_advice)
    : status.last_advice_time
      ? tr("liveAdviceLast", status.last_advice_time)
      : tr("liveAdviceNone");
  const missing = Array.isArray(status.missing_important_fields) && status.missing_important_fields.length
    ? status.missing_important_fields.join(", ")
    : tr("none");
  liveEls.missing.textContent = tr("liveMissing", missing);
}

// «Operations health» in the developer section (renderer/ops-health.js): read
// when the section opens, on «Refresh» and every OPS_REFRESH_MS while it is open
// and the window is visible.
const OPS_REFRESH_MS = 10000;
let lastOps = null;
let opsLocale = "";
let opsTimer = null;

async function refreshOps() {
  renderOps(await window.launcherApi.operationsHealth());
  clearTimeout(opsTimer);
  opsTimer = setTimeout(() => {
    if (els.devTools.open && !document.hidden) {
      run(refreshOps);
    }
  }, OPS_REFRESH_MS);
}

function renderOps(health) {
  lastOps = health || {};
  opsLocale = locale;
  const rowsEl = $("#ops-rows");
  const warningsEl = $("#ops-warnings");
  if (!rowsEl || !warningsEl || typeof OpsHealth === "undefined") {
    return;
  }
  if (lastOps.error) {
    rowsEl.replaceChildren();
    warningsEl.replaceChildren(Object.assign(document.createElement("li"), { textContent: tr("opsUnavailable") }));
    return;
  }
  rowsEl.replaceChildren(
    ...OpsHealth.rows(lastOps, tr).map(({ key, value, state }) => {
      const row = document.createElement("div");
      const term = Object.assign(document.createElement("dt"), { textContent: tr(key) });
      const detail = Object.assign(document.createElement("dd"), { textContent: value });
      detail.dataset.state = state;
      row.append(term, detail);
      return row;
    })
  );
  const warnings = OpsHealth.warningTexts(lastOps, trOr);
  warningsEl.replaceChildren(
    ...(warnings.length ? warnings : [tr("opsAllGood")]).map((text) => Object.assign(document.createElement("li"), { textContent: text }))
  );
  warningsEl.dataset.state = warnings.length ? "bad" : "good";
}

// «Автоматичні копії» (backend auto_backup.py): the switch, «Зробити копію
// зараз» and each copy with «Перевірити» (a preview that writes nothing), then
// «Відновити» when it would add something.

async function refreshBackups() {
  const result = await window.launcherApi.player("backups");
  if (result.ok) {
    renderBackups(result.data);
  }
}

function backupSize(bytes) {
  const uk = locale === "uk";
  const mb = Number(bytes || 0) / 1048576;
  return mb >= 1 ? `${mb.toFixed(1)} ${uk ? "МБ" : "MB"}` : `${Math.max(1, Math.round(Number(bytes || 0) / 1024))} ${uk ? "КБ" : "KB"}`;
}

function backupDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(locale === "uk" ? "uk-UA" : "en-GB", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
}

function renderBackups(state) {
  lastBackups = state || {};
  backupsLocale = locale;
  const items = Array.isArray(lastBackups.items) ? lastBackups.items : [];
  autoBackupEls.toggle.checked = lastBackups.enabled !== false;
  autoBackupEls.status.textContent = lastBackups.enabled === false ? tr("autoBackupOff") : items.length ? "" : tr("autoBackupNone");
  autoBackupEls.list.replaceChildren(
    ...items.map((item) => {
      const row = document.createElement("li");
      row.className = "auto-backup-item";
      const label = document.createElement("span");
      label.textContent = tr("autoBackupItem", backupDate(item.created_at), trOr(`autoBackupKinds.${item.kind}`, item.kind), item.matches, backupSize(item.size));
      const note = document.createElement("span");
      note.className = "setting-hint";
      note.setAttribute("aria-live", "polite");
      const check = document.createElement("button");
      check.type = "button";
      check.className = "btn btn-sm btn-ghost";
      check.textContent = tr("autoBackupCheck");
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "btn btn-sm";
      restore.textContent = tr("autoBackupRestore");
      restore.classList.add("hidden");
      check.addEventListener("click", () =>
        run(async () => {
          check.disabled = true;
          note.textContent = tr("autoBackupChecking");
          const result = await window.launcherApi.player("backupPreview", { backupId: item.id });
          check.disabled = false;
          if (!result.ok || !result.data || !result.data.preview) {
            note.textContent = tr(result.data && result.data.code === "not_backup" ? "autoBackupBroken" : "backupFailed");
            return;
          }
          const imported = result.data.imported || {};
          const added = Number(imported.matches?.added || 0);
          const filled = ["players", "matches", "meta", "cache"].reduce((sum, table) => sum + Number(imported[table]?.filled || 0), 0);
          note.textContent = tr("autoBackupPreview", added, filled);
          restore.classList.toggle("hidden", !(added || filled || Object.values(imported).some((part) => Number(part?.added || 0))));
        })
      );
      restore.addEventListener("click", () =>
        run(async () => {
          restore.disabled = true;
          const result = await window.launcherApi.player("backupRestore", { backupId: item.id });
          restore.disabled = false;
          restore.classList.add("hidden");
          note.textContent = result.ok && result.data && result.data.imported
            ? tr("autoBackupRestored", Number(result.data.imported.matches?.added || 0))
            : tr(result.data && result.data.code === "not_backup" ? "autoBackupBroken" : "backupRestoreFailed");
        })
      );
      const actions = document.createElement("span");
      actions.className = "auto-backup-actions";
      actions.append(check, restore);
      row.append(label, actions, note);
      return row;
    })
  );
}

function renderLogs(logs) {
  els.logs.textContent = logs || "";
  els.logs.scrollTop = els.logs.scrollHeight;
}
