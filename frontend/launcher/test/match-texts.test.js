"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { create } = require("../renderer/match-texts");

test("match copy binds the view's number/decimal/clock formatters", () => {
  const calls = [];
  const format = (kind) => (value) => { calls.push([kind, value]); return `${kind}(${value})`; };
  const text = create({ number: format("number"), decimal: format("decimal"), clock: format("clock"), plural: format("plural") });
  for (const lang of ["uk", "en"]) {
    const facts = text[lang].sectionFacts.fights({ stuns: 2.5, enemy_stuns: 3.5, tower_damage: 400, enemy_tower_damage: 500 }).filter(Boolean).join(" ");
    assert.ok(facts.includes("decimal(2.5)") && facts.includes("decimal(3.5)"));
    assert.ok(facts.includes("number(400)") && facts.includes("number(500)"));
    const items = text[lang].sectionFacts.items({ first_item: { item: "Maelstrom", t: 1200 }, save_item: { item: "Glimmer Cape", t: 1400 } }).filter(Boolean).join(" ");
    assert.ok(items.includes("clock(1200)") && items.includes("clock(1400)"));
  }
  assert.equal(calls.length, 12);
});

test("Ukrainian plurals keep using the supplied function", () => {
  const calls = [];
  const text = create({ plural: (...args) => { calls.push(args); return "chosen-form"; } });
  assert.equal(text.uk.pfNeedSparks(3), "Ще 3 chosen-form");
  assert.deepEqual(calls, [[3, "іскра", "іскри", "іскор"]]);
});

test("formatters can follow locale switches without recreating the tables", () => {
  let locale = "en";
  const text = create({ decimal: (value) => `${locale}:${value}` });
  assert.ok(text.en.sectionFacts.fights({ stuns: 2.5 }).filter(Boolean).join(" ").includes("en:2.5"));
  locale = "uk";
  assert.ok(text.uk.sectionFacts.fights({ stuns: 2.5 }).filter(Boolean).join(" ").includes("uk:2.5"));
});

test("every live decision point has a UK and EN label for the advice marks card", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const source = fs.readFileSync(path.join(__dirname, "../../../backend/app/decision_points.py"), "utf8");
  const points = new Set(source.match(/"[A-Z][A-Z_]{4,}"/g).map((quoted) => quoted.slice(1, -1)));
  const text = create({});
  assert.ok(points.size > 10);
  for (const lang of ["uk", "en"]) {
    for (const point of points) {
      assert.ok(text[lang].adviceKinds[point], `${lang} ${point}`);
    }
  }
});

test("the public lane matchup line reads in both languages", () => {
  const text = create({});
  assert.equal(
    text.uk.laneMatchupHard("Juggernaut", "Viper", 12, 20),
    "Ця лінія зазвичай важка: у публічних іграх Juggernaut програє її проти Viper 12 з 20."
  );
  assert.equal(
    text.en.laneMatchupHard("Juggernaut", "Viper", 12, 20),
    "A hard lane in general: in public games Juggernaut loses it to Viper 12 of 20 times."
  );
  assert.ok(text.uk.laneMatchupEasy("Juggernaut", "Lion", 13, 20).includes("зазвичай зручна"));
  assert.ok(text.en.laneMatchupEasy("Juggernaut", "Lion", 13, 20).includes("wins it against Lion 13 of 20"));
});
