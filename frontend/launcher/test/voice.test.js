const assert = require("node:assert/strict");
const test = require("node:test");

const {
  START_TIMEOUT_MS,
  createSpeaker,
  pickVoice,
  speechChoice,
  speechText,
  voiceLogLine,
  wantsSpeech
} = require("../overlay/voice");

const VOICES = [
  { name: "Microsoft David", lang: "en-US", localService: true },
  { name: "Google українська", lang: "uk-UA", localService: false },
  { name: "Microsoft Ostap", lang: "uk-UA", localService: true }
];

function fakeSynth() {
  const synth = {
    speaking: false,
    spoken: [],
    cancels: 0,
    getVoices: () => VOICES,
    speak(utterance) {
      synth.spoken.push(utterance);
    },
    cancel() {
      synth.cancels += 1;
    }
  };
  return synth;
}

class Utterance {
  constructor(text) {
    this.text = text;
  }
}

function speaker(synth, clock) {
  return createSpeaker({ synth, Utterance, now: () => clock.t, setTimer: () => 0, clearTimer: () => {} });
}

// A speaker whose events and start watchdog the test drives.
function watchedSpeaker(synth) {
  const events = [];
  const timers = new Map();
  let next = 1;
  const voice = createSpeaker({
    synth,
    Utterance,
    onEvent: (event) => events.push(event),
    setTimer: (fn, ms) => {
      timers.set(next, { fn, ms });
      return next++;
    },
    clearTimer: (id) => timers.delete(id)
  });
  const fire = () => {
    for (const [id, timer] of [...timers]) {
      timers.delete(id);
      timer.fn();
    }
  };
  return { voice, events, timers, fire };
}

const URGENT = { adviceMode: "urgent", mode: "urgent", locale: "en" };

test("modes decide which advice is spoken", () => {
  assert.equal(wantsSpeech("off", "urgent"), false);
  assert.equal(wantsSpeech("urgent", "urgent"), true);
  assert.equal(wantsSpeech("urgent", "coaching"), false);
  assert.equal(wantsSpeech("all", "coaching"), true);
  assert.equal(wantsSpeech("loud", "urgent"), false);
});

test("a local voice of the UI language is preferred", () => {
  assert.equal(pickVoice(VOICES, "uk").name, "Microsoft Ostap");
  assert.equal(pickVoice(VOICES, "en").name, "Microsoft David");
  assert.equal(pickVoice(VOICES.slice(0, 1), "uk"), null);
});

test("long actions are cut at a word boundary", () => {
  const text = `${"Farm the safe lane jungle camps ".repeat(8)}now`;
  const spoken = speechText(text);
  assert.ok(spoken.length <= 160 && !spoken.endsWith(" "));
  assert.equal(speechText("  Back   off.  "), "Back off.");
});

test("each advice is spoken once, tips keep a gap, urgent interrupts", () => {
  const synth = fakeSynth();
  const clock = { t: 0 };
  const voice = speaker(synth, clock);
  const tip = { key: "a", text: "Stack the camp", adviceMode: "coaching", mode: "all", locale: "uk" };

  assert.equal(voice.say(tip), "spoken");
  assert.equal(synth.spoken[0].voice.name, "Microsoft Ostap");
  assert.equal(voice.say(tip), "same");

  clock.t = 1000;
  assert.equal(voice.say({ ...tip, key: "b" }), "too_soon");
  clock.t = 5000;
  synth.speaking = true;
  assert.equal(voice.say({ ...tip, key: "b" }), "busy");

  assert.equal(voice.say({ ...tip, key: "c", adviceMode: "urgent", text: "Back off" }), "spoken");
  assert.equal(synth.cancels, 1);
  assert.equal(synth.spoken.at(-1).text, "Back off");
});

test("urgent-only mode ignores tips; no voice for the language is reported", () => {
  const synth = fakeSynth();
  const voice = speaker(synth, { t: 0 });
  assert.equal(voice.say({ key: "a", text: "Stack", adviceMode: "coaching", mode: "urgent", locale: "uk" }), "off");
  synth.getVoices = () => VOICES.slice(0, 1);
  assert.equal(voice.say({ key: "b", text: "Відходьте", adviceMode: "urgent", mode: "urgent", locale: "uk" }), "no_voice");
  assert.equal(synth.spoken.length, 0);
});

test("without a Ukrainian voice the English original is read by an English voice", () => {
  const synth = fakeSynth();
  synth.getVoices = () => VOICES.slice(0, 1);
  const voice = speaker(synth, { t: 0 });
  const said = voice.say({
    key: "a",
    text: "Відходьте зараз",
    fallbackText: "Back off now",
    adviceMode: "urgent",
    mode: "urgent",
    locale: "uk"
  });
  assert.equal(said, "spoken_en");
  assert.equal(synth.spoken[0].text, "Back off now");
  assert.equal(synth.spoken[0].lang, "en-US");
  // With a Ukrainian voice the Ukrainian text wins; English never falls back.
  assert.deepEqual(speechChoice(VOICES, "uk", "Відходьте", "Back off").text, "Відходьте");
  assert.equal(speechChoice(VOICES.slice(1), "en", "Back off", "Back off"), null);
  assert.equal(speechChoice(VOICES.slice(0, 1), "uk", "Відходьте", ""), null);
});

test("a repeat asked by the player is spoken again at once, but never when the voice is off", () => {
  const synth = fakeSynth();
  const clock = { t: 0 };
  const voice = speaker(synth, clock);
  const tip = { key: "a", text: "Stack the camp", adviceMode: "coaching", mode: "urgent", locale: "en" };
  assert.equal(voice.say(tip), "off");
  assert.equal(voice.say({ ...tip, repeat: true }), "spoken");
  clock.t = 500;
  assert.equal(voice.say({ ...tip, repeat: true }), "spoken");
  assert.equal(synth.cancels, 2);
  assert.equal(voice.say({ ...tip, mode: "off", repeat: true }), "off");
});

test("a withdrawn card stops only its own speech", () => {
  const synth = fakeSynth();
  const clock = { t: 0 };
  const voice = speaker(synth, clock);
  const say = (key) =>
    voice.say({ key, text: "Use Magic Wand now, then step back.", adviceMode: "urgent", mode: "all", locale: "en" });
  assert.equal(say("wand"), "spoken");
  synth.speaking = true;
  // Another card's key: nothing is cut.
  assert.equal(voice.cancel("blink"), false);
  assert.equal(synth.cancels, 1); // the urgent say itself cancels once
  // Its own key while speaking: cut, and the same card could be said again.
  assert.equal(voice.cancel("wand"), true);
  assert.equal(synth.cancels, 2);
  synth.speaking = false;
  clock.t += 10_000;
  assert.equal(say("wand"), "spoken");
});

test("a tip skipped while busy is never spoken by itself later", () => {
  // No queue: a tip that found the voice busy is spoken only if a later poll
  // still returns it (the backend revalidated it); a withdrawn tip never is.
  const synth = fakeSynth();
  const clock = { t: 0 };
  const voice = speaker(synth, clock);
  synth.speaking = true;
  const tip = { key: "farm|1", text: "Farm the bottom wave.", adviceMode: "coaching", mode: "all", locale: "en" };
  assert.equal(voice.say(tip), "busy");
  synth.speaking = false;
  clock.t += 10_000;
  assert.equal(synth.spoken.length, 0);
  assert.equal(voice.say(tip), "spoken");
});

test("the system voice reports each change once: speaking, failures, a stuck queue", () => {
  const synth = fakeSynth();
  const { voice, events, timers, fire } = watchedSpeaker(synth);

  assert.equal(voice.say({ key: "a", text: "Back off.", ...URGENT }), "spoken");
  assert.equal([...timers.values()][0].ms, START_TIMEOUT_MS);
  synth.spoken[0].onstart();
  assert.equal(timers.size, 0, "a started utterance stops its watchdog");
  voice.say({ key: "b", text: "Use Glimmer Cape.", ...URGENT });
  synth.spoken[1].onstart();
  assert.deepEqual(events, [{ kind: "speaking", detail: "Microsoft David (en-US)" }]);

  // An urgent card cutting the previous one is our own interruption.
  voice.say({ key: "c", text: "Reset HP.", ...URGENT });
  synth.spoken[1].onerror({ error: "interrupted" });
  synth.spoken[2].onerror({ error: "audio-hardware" });
  assert.deepEqual(events.at(-1), { kind: "error", detail: "audio-hardware" });

  // Spoken into a dead queue: nothing starts, the queue is reset.
  const cancels = synth.cancels;
  voice.say({ key: "d", text: "Buy Black King Bar.", ...URGENT });
  fire();
  assert.deepEqual(events.at(-1), { kind: "not_started", detail: "Microsoft David (en-US)" });
  assert.equal(synth.cancels, cancels + 2, "cut before speaking, then reset by the watchdog");
  assert.equal(events.length, 3);
});

test("no voice is reported with the language and the count, a paused queue is resumed", () => {
  const synth = { ...fakeSynth(), getVoices: () => [], paused: false };
  const { voice, events } = watchedSpeaker(synth);
  assert.equal(voice.say({ key: "a", text: "Back off.", ...URGENT }), "no_voice");
  assert.equal(voice.say({ key: "b", text: "Back off.", ...URGENT }), "no_voice");
  assert.deepEqual(events, [{ kind: "no_voice", detail: "en, 0 system voices" }]);

  const paused = fakeSynth();
  let resumed = 0;
  paused.paused = true;
  paused.resume = () => {
    resumed += 1;
  };
  watchedSpeaker(paused).voice.say({ key: "a", text: "Back off.", ...URGENT });
  assert.equal(resumed, 1);
});

test("voice log lines take only known kinds and a plain detail", () => {
  assert.equal(
    voiceLogLine({ kind: "speaking", detail: "Microsoft Zira (en-US)" }),
    "Voice: speaking with Microsoft Zira (en-US)."
  );
  assert.equal(
    voiceLogLine({ kind: "not_started", detail: "Microsoft Zira (en-US)" }),
    "Voice: the system speech did not start within 5 s (Microsoft Zira (en-US)); its queue was reset."
  );
  assert.equal(voiceLogLine({ kind: "error", detail: "a\nfake [launcher] line<script>" }), "Voice: the system speech failed (afake launcher linescript).");
  assert.equal(voiceLogLine({ kind: "error", detail: "" }), "Voice: the system speech failed (?).");
  assert.equal(voiceLogLine({ kind: "toString" }), null);
  assert.equal(voiceLogLine({ kind: "rm" }), null);
  assert.equal(voiceLogLine(null), null);
  assert.equal(voiceLogLine("speaking"), null);
});
