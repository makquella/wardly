"""The offline analysis of recorded uses after a card (scripts/replay_outcomes.py).

The rows copy the Manta episode of match 9054793282 at 23:51-23:56 (wall time
`w` of the recording): stunned from 4576.14, silenced from 4577.56 with Manta
ready, Manta's cooldown first seen at 4580.95, in the snapshot where the
silence ends. The 0.60.0 report said «Manta pressed 0.0 s after» the 23:52
card: that measure started at the status end, not at the card."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from replay_outcomes import describe, historical_use  # noqa: E402

MANTA = {"kind": "item", "name": "item_manta", "mode": "now"}


def row(w: float, *flags: str, manta: float = 0, alive: bool = True) -> dict[str, Any]:
    return {
        "w": w,
        "clock": None,
        "flags": list(flags),
        "alive": alive,
        "item_cd": {"item_manta": manta},
        "item_charges": {},
        "ability_cd": {},
    }


EPISODE = [
    row(4575.62),
    row(4576.14, "stunned"),
    row(4576.70, "stunned"),
    row(4577.03, "stunned"),
    row(4577.56, "silenced"),
    row(4578.06, "silenced"),
    row(4579.12, "silenced"),
    row(4580.45, "silenced"),
    row(4580.95, manta=34),
    row(4581.55, manta=34),
]


def test_the_manta_card_at_23_52_is_followed_by_the_recorded_use_3_s_later():
    outcome = historical_use(
        EPISODE, tool=MANTA, decision_w=4577.56, shown_w=4577.60, status_flags=["silenced"]
    )
    assert outcome["outcome"] == "after_show"
    # The use lies between the last unused and the first used snapshot.
    assert outcome["used_between"] == [4580.45, 4580.95]
    assert outcome["delay_from_decision"] == [2.89, 3.39]
    assert outcome["delay_from_shown"][0] > 2.8
    # The silence ended in that very snapshot: which came first is unknown.
    assert outcome["order_with_status_end"] == "same_snapshot_unknown"
    assert outcome["voice_w"] is None  # not observable offline
    assert "0.0" not in describe(outcome)


def test_a_use_before_the_card_was_shown_is_already_done_with_its_negative_delay():
    rows = [row(10.0, "silenced"), row(10.5, "silenced"), row(11.0, manta=40), row(11.5, manta=40)]
    outcome = historical_use(
        rows, tool=MANTA, decision_w=10.0, shown_w=11.2, status_flags=["silenced"]
    )
    assert outcome["outcome"] == "already_done"
    assert outcome["delay_from_shown"] == [-0.7, -0.2]


def test_a_later_use_of_the_same_item_belongs_to_another_moment():
    # The silence ends without Manta; 40 s later Manta is used in another
    # fight: not the card's.
    rows = [row(10.0, "silenced"), row(11.0, "silenced"), row(12.0)]
    rows += [row(12.0 + i) for i in range(1, 40)] + [row(52.0, manta=40)]
    outcome = historical_use(
        rows, tool=MANTA, decision_w=10.0, shown_w=10.2, status_flags=["silenced"]
    )
    assert outcome["outcome"] == "not_used_in_episode"


def test_a_use_in_the_sampling_interval_of_the_show_has_no_order():
    rows = [row(10.0, "silenced"), row(10.5, "silenced"), row(11.0, manta=40)]
    outcome = historical_use(
        rows, tool=MANTA, decision_w=10.0, shown_w=10.7, status_flags=["silenced"]
    )
    assert outcome["outcome"] == "around_show"
    assert outcome["delay_from_shown"] == [-0.2, 0.3]


def test_a_death_before_any_use_is_reported_as_such():
    rows = [row(10.0, "stunned"), row(10.5, "stunned"), row(11.0, "stunned", alive=False)]
    outcome = historical_use(
        rows, tool=MANTA, decision_w=10.0, shown_w=10.1, status_flags=["stunned"]
    )
    assert outcome["outcome"] == "died_before_use"


def test_a_card_without_a_tool_has_no_historical_use():
    assert historical_use(EPISODE, tool=None, decision_w=4577.56, shown_w=4577.6)["outcome"] == (
        "no_tool"
    )
