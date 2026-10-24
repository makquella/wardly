const assert = require("node:assert/strict");
const test = require("node:test");

const { createSpeaker, pickVoice, speechChoice, speechText, wantsSpeech } = require("../overlay/voice");

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
  return createSpeaker({ synth, Utterance, now: () => clock.t });
}

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
