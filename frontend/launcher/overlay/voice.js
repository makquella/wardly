// Spoken advice (optional): Chromium's speechSynthesis with the voices of the
// system (Windows: SAPI voices such as "Microsoft Ostap" for Ukrainian, where installed). Works
// even when exclusive fullscreen hides the card. Pure rules + a small speaker
// so the rules run in node tests; loaded as a plain script by the overlay and
// the control panel (window.OverlayVoice).
(function attach(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.OverlayVoice = api;
  }
})(typeof self !== "undefined" ? self : this, () => {
  const MODES = ["off", "urgent", "all"];
  // Tips never talk over each other; an urgent one interrupts a tip.
  const MIN_GAP_MS = 4000;
  const MAX_CHARS = 160;
  // A system voice that has not started this long after speak() is stuck
  // (Chromium on Windows can keep a dead queue): the queue is reset.
  const START_TIMEOUT_MS = 5000;
  // Errors of our own interruption (an urgent card cuts a tip) are no failure.
  const OWN_ERRORS = new Set(["interrupted", "canceled"]);

  function normalizeMode(mode) {
    return MODES.includes(mode) ? mode : "off";
  }

  function wantsSpeech(mode, adviceMode) {
    const current = normalizeMode(mode);
    return current === "all" || (current === "urgent" && adviceMode === "urgent");
  }

  // A voice for the language: local (offline) voices first, then any.
  function pickVoice(voices, locale) {
    const prefix = String(locale || "en").toLowerCase().slice(0, 2);
    const matching = (voices || []).filter((voice) => String(voice.lang || "").toLowerCase().startsWith(prefix));
    return matching.find((voice) => voice.localService) || matching[0] || null;
  }

  // The voice and the words: in the panel's language, or — when Windows has no
  // voice for it (a Ukrainian voice needs a language pack) — the English
  // original with an English voice. null: nothing can be spoken.
  function speechChoice(voices, locale, text, fallbackText) {
    const voice = pickVoice(voices, locale);
    if (voice) {
      return { voice, text, fallback: false };
    }
    const english = String(locale || "en").toLowerCase().startsWith("en") ? null : pickVoice(voices, "en");
    return english && fallbackText ? { voice: english, text: fallbackText, fallback: true } : null;
  }

  // Only the action is spoken: the reason is for reading.
  function speechText(action) {
    const text = String(action || "").replace(/\s+/g, " ").trim();
    if (text.length <= MAX_CHARS) {
      return text;
    }
    const cut = text.slice(0, MAX_CHARS);
    const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf(", "), cut.lastIndexOf(" "));
    return cut.slice(0, end > 40 ? end : MAX_CHARS).trim();
  }

  // synth: speechSynthesis-like ({speak, cancel, speaking, getVoices});
  // Utterance: SpeechSynthesisUtterance-like constructor.
  // onEvent({kind, detail}): what the system voice did, each change once
  // (kind: "speaking" | "no_voice" | "error" | "not_started"), for the log.
  function createSpeaker({
    synth,
    Utterance,
    now = () => Date.now(),
    onEvent = null,
    setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (id) => clearTimeout(id)
  }) {
    let lastKey = "";
    let lastAt = -Infinity;
    let reported = "";
    let watchdog = null;

    function report(kind, detail = "") {
      const text = String(detail || "").slice(0, 80);
      const id = `${kind}|${text}`;
      if (!onEvent || id === reported) {
        return;
      }
      reported = id;
      try {
        onEvent({ kind, detail: text });
      } catch {
        // The log is best effort: speech never depends on it.
      }
    }

    function stopWatchdog() {
      if (watchdog !== null) {
        clearTimer(watchdog);
        watchdog = null;
      }
    }

    function watch(utterance, label) {
      stopWatchdog();
      let started = false;
      utterance.onstart = () => {
        started = true;
        stopWatchdog();
        report("speaking", label);
      };
      utterance.onerror = (event) => {
        stopWatchdog();
        const code = String(event?.error || "unknown");
        if (!OWN_ERRORS.has(code)) {
          report("error", code);
        }
      };
      watchdog = setTimer(() => {
        watchdog = null;
        if (!started) {
          report("not_started", label);
          synth.cancel();
        }
      }, START_TIMEOUT_MS);
    }

    // Returns what happened: "spoken" | "spoken_en" | "off" | "same" | "busy" | "too_soon" | "no_voice" | "empty".
    // fallbackText: the English original, read when there is no voice for locale.
    // repeat: asked for by the player (hotkey): spoken whenever the voice is
    // on at all, right away, even if it was just said.
    function say({ key, text, fallbackText = "", adviceMode, mode, locale, volume = 1, repeat = false }) {
      if (!synth || !Utterance || !(repeat ? normalizeMode(mode) !== "off" : wantsSpeech(mode, adviceMode))) {
        return "off";
      }
      if (key && key === lastKey && !repeat) {
        return "same";
      }
      const spoken = speechText(text);
      if (!spoken) {
        return "empty";
      }
      const urgent = adviceMode === "urgent" || repeat;
      if (!urgent && (synth.speaking || now() - lastAt < MIN_GAP_MS)) {
        return synth.speaking ? "busy" : "too_soon";
      }
      const voices = synth.getVoices() || [];
      const choice = speechChoice(voices, locale, spoken, speechText(fallbackText));
      if (!choice) {
        report("no_voice", `${String(locale || "en")}, ${voices.length} system voices`);
        return "no_voice";
      }
      const { voice } = choice;
      if (urgent) {
        synth.cancel();
      }
      const utterance = new Utterance(choice.text);
      utterance.lang = voice.lang;
      try {
        utterance.voice = voice;
      } catch {
        // Not a real SpeechSynthesisVoice: the language picks the voice.
      }
      utterance.volume = Math.min(1, Math.max(0, Number(volume)));
      utterance.rate = 1.05;
      watch(utterance, `${voice.name || "?"} (${voice.lang || "?"})`);
      // A queue left paused (Chromium) plays nothing until resumed.
      if (synth.paused && typeof synth.resume === "function") {
        synth.resume();
      }
      synth.speak(utterance);
      lastKey = key || "";
      lastAt = now();
      return choice.fallback ? "spoken_en" : "spoken";
    }

    // The card being spoken was withdrawn (the game moved on): stop it, and
    // only it. Returns whether something was cut.
    function cancel(key) {
      if (!synth || !key || key !== lastKey) {
        return false;
      }
      const speaking = Boolean(synth.speaking);
      stopWatchdog();
      if (speaking) {
        synth.cancel();
      }
      lastKey = "";
      return speaking;
    }

    function reset() {
      stopWatchdog();
      lastKey = "";
      lastAt = -Infinity;
      if (synth) {
        synth.cancel();
      }
    }

    return { say, cancel, reset };
  }

  // The launcher log line for an onEvent (main.js; the renderer's words are
  // never trusted: only known kinds, a short plain detail). null: not logged.
  const LOG_LINES = {
    speaking: (detail) => `speaking with ${detail}.`,
    no_voice: (detail) => `no system voice (${detail}); nothing is spoken.`,
    error: (detail) => `the system speech failed (${detail}).`,
    not_started: (detail) => `the system speech did not start within ${START_TIMEOUT_MS / 1000} s (${detail}); its queue was reset.`
  };

  function voiceLogLine(event) {
    const line = event && typeof event === "object" && Object.hasOwn(LOG_LINES, event.kind) ? LOG_LINES[event.kind] : null;
    if (!line) {
      return null;
    }
    const detail = String(event.detail ?? "").replace(/[^\p{L}\p{N} ().,:_-]/gu, "").slice(0, 80).trim() || "?";
    return `Voice: ${line(detail)}`;
  }

  return { MODES, MIN_GAP_MS, START_TIMEOUT_MS, createSpeaker, voiceLogLine, normalizeMode, pickVoice, speechChoice, speechText, wantsSpeech };
});
