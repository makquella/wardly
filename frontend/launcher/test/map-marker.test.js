const assert = require("node:assert/strict");
const test = require("node:test");

const { MAP_SRC, markerLayout } = require("../overlay/map-marker");

test("a card's place and the player's dot become positions on the map picture", () => {
  const layout = markerLayout({ target: [0.25, 0.8], player: [0.5, 0.5], kind: "danger" });
  assert.deepEqual(layout, {
    target: { left: "25.0%", top: "80.0%" },
    player: { left: "50.0%", top: "50.0%" },
    kind: "danger"
  });
  assert.equal(MAP_SRC, "dota-asset://map/detailed_740");
});

test("no target, no map; a broken player point only drops the player's dot", () => {
  assert.equal(markerLayout(null), null);
  assert.equal(markerLayout({ player: [0.5, 0.5] }), null);
  assert.equal(markerLayout({ target: [1.2, 0.5] }), null);
  assert.equal(markerLayout({ target: ["0.5", 0.5] }), null);
  const layout = markerLayout({ target: [0.1, 0.2], player: [NaN, 0.1], kind: "whatever" });
  assert.equal(layout.player, null);
  assert.equal(layout.kind, "farm");
});
