// The small map on a hint card: where the card points (the farm target, an
// attacked building, a fight, enemy summons) and where the player is now, over
// the game's minimap art (dota-asset://map/detailed_740, cached by the
// launcher; a dark square until it loads). The backend sends both points as
// [left, top] shares of the picture (map_hints.map_point). Pure layout, so it
// runs in node tests; loaded as a plain script by the overlay (window.OverlayMapMarker).
(function attach(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.OverlayMapMarker = api;
  }
})(typeof self !== "undefined" ? self : this, () => {
  const MAP_SRC = "dota-asset://map/detailed_740";
  const KINDS = new Set(["farm", "danger"]);

  function point(value) {
    if (!Array.isArray(value) || value.length !== 2) return null;
    const [left, top] = value;
    if (!Number.isFinite(left) || !Number.isFinite(top)) return null;
    if (left < 0 || left > 1 || top < 0 || top > 1) return null;
    return { left: `${(left * 100).toFixed(1)}%`, top: `${(top * 100).toFixed(1)}%` };
  }

  // {target, player (or null), kind} with CSS positions, or null: no target, no map.
  function markerLayout(marker) {
    if (!marker || typeof marker !== "object") return null;
    const target = point(marker.target);
    if (!target) return null;
    return {
      target,
      player: point(marker.player),
      kind: KINDS.has(marker.kind) ? marker.kind : "farm"
    };
  }

  return { MAP_SRC, markerLayout };
});
