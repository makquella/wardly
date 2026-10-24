"""
player_service.py - the linked player, their match history and reviews.

Ties together the SQLite store, the live match tracker, the OpenDota client
and the analyses:

- Account: the Steam account playing is read from GSI (player.steamid) and
  linked automatically the first time; it can also be linked by hand (Steam
  ID, Friend ID or profile link). A different account seen in GSI later is
  offered as "detected", never switched silently.
- History: a background sync pulls the profile and the last matches from
  OpenDota and reviews the most recent ones.
- After a live match: the GSI timeline is stored and reviewed at once
  (offline), then OpenDota is asked to parse the replay; when the parsed
  match arrives the review is rebuilt with the full data.

Network work runs on one background thread (JobQueue), never on the GSI path.
Without internet (or with OPENDOTA_ENABLED=false) everything still works from
the app's own GSI recordings.

AI coach (optional, coach_review.py): with a Groq / OpenRouter key the rule
based reviews get a coach's explanation on a second job thread; results are
cached per match, language and facts, and rebuilt when the facts change.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import (
    advice_feedback,
    auto_backup,
    cosmetics,
    rank_history,
    review_basis,
    stratz_builds,
)
from app.analysis_texts import rank_label, render_analysis
from app.ask_runs import AskRuns
from app.auto_backup import AutoBackups
from app.career_analysis import NOT_RECURRING, analyze_career
from app.coach_llm import PROVIDERS, AISettings, CoachLLM, CoachLLMError, settings_from
from app.coach_review import (
    COACH_VERSION,
    QUESTION_LIMIT,
    FactChecker,
    answer_question,
    career_facts,
    facts_hash,
    match_facts,
    recent_match_line,
    review_career,
    review_match,
)
from app.death_screen import build_death_screen
from app.diagnostics import record_error
from app.dota_constants import (
    TURBO_GAME_MODE,
    hero_id_from_name,
    hero_name,
    is_reviewable_match,
)
from app.draft_analysis import pool_heroes
from app.finding_history import finding_history
from app.focus_goal import can_focus, focus_summary, match_result, new_focus, played_after
from app.friend_compare import compare
from app.game_plan import build_game_plan, key_item
from app.hero_items import plan_fight, plan_for, plan_note, plan_skills
from app.hero_meta import item_key, start_items
from app.hero_profiles import get_hero_position
from app.history_backup import export_backup, import_backup, preview_backup
from app.home_summary import home_summary
from app.job_queue import JOB_STOP_TIMEOUT_SECONDS, JobQueue
from app.lane_duel import lane_records
from app.map_analysis import map_side, zone
from app.map_hints import SAVE_ITEMS
from app.match_facts import facts_from_opendota, facts_from_timeline, merge_facts
from app.match_memory import DEATH_PATTERN_RADIUS
from app.match_records import MATCH_RECORDS
from app.match_tracker import MatchTracker, account_from_gsi
from app.next_item import (
    buy_now,
    has_components,
    net_worth,
    next_build_item,
    next_listed_item,
    owned_items,
    save_build_item,
)
from app.opendota import (
    TRIM_VERSION,
    OpenDotaClient,
    OpenDotaError,
    my_player,
    summary_from_match,
    trim_match,
)
from app.personal_baseline import MAX_GAMES as MAX_BASELINE_GAMES
from app.personal_baseline import personal_baseline
from app.player_contracts import analysis_core_valid
from app.player_goals import goal_streaks, tilt
from app.player_profile import MMR_MAX, MMR_MIN, add_anchor, build_profile
from app.player_store import SCHEMA_VERSION, PlayerStore
from app.post_game import post_game_card
from app.post_match_analysis import ANALYSIS_VERSION, analyze_match
from app.schemas import is_supported_hero
from app.secret_box import SecretBox
from app.session_summary import session_summary
from app.share_progress import public_progress
from app.share_review import public_review
from app.situational_items import draft_item as draft_counter_item
from app.situational_items import lineup_save_item, situational_item
from app.skill_build import skill_order
from app.steam_ids import parse_account_id, steam64_from_account_id
from app.usage_stats import usage_stats
from app.weekly_summary import weekly_summary

RECENT_MATCHES_LIMIT = 50
# The profile counts every stored match (achievements, level, the rating graph).
PROFILE_MATCHES_LIMIT = 5000
REVIEW_RECENT_MATCHES = 12
# On sync, ask OpenDota to parse this many of the newest unparsed matches (a
# parsed replay adds lanes, last hits at 10:00, the build and the map). Valve
# keeps replays for about two weeks; a week keeps the requests useful.
PARSE_RECENT_MATCHES = 5
PARSE_MAX_AGE_SECONDS = 7 * 24 * 3600
# OpenDota learns about a match a minute or two after it ends.
FIRST_FETCH_DELAY_SECONDS = 120
PARSE_POLL_SECONDS = 90
PARSE_POLL_ATTEMPTS = 12
# OpenDota meta data cache (player_store cache table).
ITEM_CONSTANTS_KEY = "opendota:items"
# Stored reviews whose final items are read into the table per request (0.50).
BACKFILL_ITEMS_PER_CALL = 10
POPULARITY_KEY = "opendota:item_popularity"
TIMINGS_KEY = "opendota:item_timings"
SKILLS_KEY = "opendota:pro_skills"
HERO_STATS_KEY = "opendota:hero_stats"
MATCHUPS_KEY = "opendota:matchups"
META_TTL_SECONDS = 7 * 24 * 3600
HERO_STATS_TTL_SECONDS = 24 * 3600
GAME_PLAN_CACHE_SECONDS = 60
# The score screen card (post_game.py): shown this long after the review is written.
POST_GAME_CARD_SECONDS = 150
SKIPPED_MODES_META = "skipped_modes"
FOCUS_META = "focus"
FRIEND_META = "friend"
FRIEND_CACHE = "friend:matches"
TODAY_MAX_MATCHES = 30
GOAL_MATCHES = 30  # rows read for the streak goals and the tilt warning
# Earlier matches read for a repeating problem (some cannot show every problem).
REPEATS_LOOKUP = 25
# "Ask the coach": the last questions per match, and how long the player waits.
ASK_CACHE_KEY = "coach:ask"
# Before 0.54 the coach also answered in Russian. Reviews are cached per language
# (`…:ru` is simply never asked for again); questions share one history, so the
# Russian answers stay stored (backups, restores) but are no longer shown.
RETIRED_COACH_LANG = "ru"
ASK_HISTORY = 5
ASK_TIMEOUT_SECONDS = 60.0
# Automatic local copies (auto_backup.py): meta "auto_backup" = "off" turns
# them off; the app version of the last copy marks an update.
AUTO_BACKUP_META = "auto_backup"
AUTO_BACKUP_VERSION_META = "auto_backup_app_version"
AUTO_BACKUP_EVERY_SECONDS = auto_backup.EVERY_SECONDS
AUTO_BACKUP_KEEP = auto_backup.KEEP
AUTO_BACKUP_BUDGET = auto_backup.BUDGET_BYTES
# The whole question, both attempts: past this the second attempt is not started,
# so the answer (or an error) comes within this plus one call, under the
# launcher's 150-second wait. A second request with the same id waits as long.
ASK_DEADLINE_SECONDS = 75.0
ASK_JOIN_WAIT_SECONDS = ASK_DEADLINE_SECONDS + ASK_TIMEOUT_SECONDS
# AI coach.
AI_SETTINGS_KEY = "ai_settings"
# The replay is still being parsed: wait for the full data before asking the model.
COACH_WAITS_FOR = {"waiting_opendota", "parsing"}
COACH_MIN_CAREER_MATCHES = 3
# "Overloaded" (HTTP 503 on every model) costs no quota: retry by itself later.
COACH_BUSY_RETRY_SECONDS = (60, 120, 180)
OPENDOTA_KEY_META = "opendota_api_key"
# OpenDota keys are UUIDs; allow any similar token, never spaces or URL parts.
OPENDOTA_KEY_RE = re.compile(r"[A-Za-z0-9-]{16,80}")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# The review chart's «your best match on this hero»: from the last 40 on the
# hero, when 2+ other reviewed matches exist.
BEST_ON_HERO_LOOKUP = 40
BEST_ON_HERO_MIN = 2
# The death screen card shows for this many seconds of clock after a death at most.
DEATH_SCREEN_WINDOW = 150
# Deaths in the same place within this many seconds make a pattern.
PLACE_WINDOW = 10 * 60
# ...and this many in the same place over the whole match, however spread out.
MATCH_PLACE_MIN = 3


def _death_place(death: dict[str, Any]) -> dict[str, Any] | None:
    """Zone and map half of the latest death, and the deaths there lately."""
    team = str(death.get("team") or "").lower()
    places = [
        p
        for p in death.get("places") or []
        if isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float))
    ]
    if team not in {"radiant", "dire"} or not places or places[-1].get("t") != death["t"]:
        return None
    radiant = team == "radiant"

    def where(p: dict[str, Any]) -> tuple[str, str]:
        return zone(p["x"], p["y"]), map_side(p["x"], p["y"], radiant)

    last = places[-1]
    here = where(last)

    def close(p: dict[str, Any]) -> bool:
        # The same named zone is not the same place: «the jungle by the river»
        # spans the map, and two deaths 6.7k units apart under one label are
        # two events (match_memory.DEATH_PATTERN_RADIUS).
        distance = ((p["x"] - last["x"]) ** 2 + (p["y"] - last["y"]) ** 2) ** 0.5
        return where(p) == here and distance <= DEATH_PATTERN_RADIUS

    same = [
        p
        for p in places
        if isinstance(p.get("t"), int) and death["t"] - p["t"] <= PLACE_WINDOW and close(p)
    ]
    in_match = sum(1 for p in places if close(p))
    return {
        "zone": here[0],
        "side": here[1],
        "count": len(same),
        "minutes": max(1, -(-(death["t"] - same[0]["t"]) // 60)),
        # Same place over the whole match (the window above misses a spot the
        # player keeps coming back to every 15 minutes).
        "in_match": in_match,
    }


def _recent_deaths(deaths: list[dict[str, Any]], at: int) -> dict[str, int] | None:
    """How many deaths the last PLACE_WINDOW seconds of clock up to `at` hold
    (this one included) and over how many minutes; None for a single death."""
    times = [
        d["t"] for d in deaths if isinstance(d.get("t"), int) and 0 <= at - d["t"] <= PLACE_WINDOW
    ]
    if len(times) < 2:
        return None
    return {"count": len(times), "minutes": max(1, -(-(at - min(times)) // 60))}


class PlayerService:
    def __init__(
        self,
        data_dir: Path,
        *,
        client: OpenDotaClient | None = None,
        auto_start: bool = True,
        llm: Any = None,
        env_ai: AISettings | None = None,
    ) -> None:
        self._lifecycle_lock = threading.RLock()
        self.configure(data_dir, client=client, auto_start=auto_start, llm=llm, env_ai=env_ai)

    def configure(
        self,
        data_dir: Path,
        *,
        client: OpenDotaClient | None = None,
        auto_start: bool = True,
        llm: Any = None,
        env_ai: AISettings | None = None,
        stop_timeout: float = JOB_STOP_TIMEOUT_SECONDS,
        secrets: SecretBox | None = None,
    ) -> None:
        """(Re)open the store in `data_dir`; used at startup and by tests.

        `llm` replaces the configured AI client (tests); `env_ai` is the key
        from .env used when the player has not entered one; `secrets` replaces
        the OS sealing of stored keys (tests; secret_box.py).
        """
        with self._lifecycle_lock:
            if not self._stop_queues(timeout=stop_timeout):
                raise TimeoutError("Player service jobs are still running; store remains unchanged")
            old_store = getattr(self, "store", None)
            if old_store is not None:
                if not self._shutdown_complete:
                    self.tracker.flush()
                old_store.close()
            self._open_store(
                data_dir,
                client=client,
                auto_start=auto_start,
                llm=llm,
                env_ai=env_ai,
                secrets=secrets,
            )

    def _open_store(
        self,
        data_dir: Path,
        *,
        client: OpenDotaClient | None,
        auto_start: bool,
        llm: Any,
        env_ai: AISettings | None,
        secrets: SecretBox | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.client = client
        # A schema change ahead: a copy of the SQLite file as it was, first.
        self.backups = AutoBackups(self.data_dir / "backups")
        with contextlib.suppress(OSError, sqlite3.Error):
            self.backups.pre_migration_snapshot(self.data_dir / "coach.sqlite3", SCHEMA_VERSION)
        self.store = PlayerStore(self.data_dir / "coach.sqlite3")
        # Stored keys under the OS's protection (DPAPI on Windows); keys an
        # older version left in plain text are sealed now.
        self.secrets = secrets or SecretBox()
        self._seal_stored_secrets()
        # The key from .env (if any); a key entered in the launcher wins.
        self._env_opendota_key = str(getattr(client, "api_key", "") or "")
        self._apply_opendota_key()
        self.jobs = JobQueue(auto_start=auto_start)
        # Model calls take up to a couple of minutes: their own thread, so they
        # never hold back OpenDota syncs.
        self.ai_jobs = JobQueue(auto_start=auto_start, name="coach-ai")
        self.llm = llm
        self.env_ai = env_ai
        self._coach_lock = threading.Lock()
        self._shop_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._coach_jobs: dict[str, dict[str, Any]] = {}
        # AI questions: one provider run per request id (ask_runs.py), and the
        # stored Q&A history is read and written under one lock.
        self.asks = AskRuns()
        self._ask_history_lock = threading.Lock()
        self.tracker = MatchTracker(
            self.data_dir / "live_match.json", on_finished=self._on_match_finished
        )
        # A week of match recordings lives next to the store (off unless switched on).
        MATCH_RECORDS.configure(self.data_dir)
        self._detected: dict[str, Any] | None = None
        # Friend fetches that failed (code), by friend account id; cleared on retry.
        self._friend_errors: dict[int, str] = {}
        # Matches asked for by number (add_match): pending, ready or an error code.
        self._adding: dict[int, str] = {}
        self._plans: dict[tuple[Any, ...], tuple[float, dict[str, Any] | None]] = {}
        self._sync: dict[str, Any] = {
            "state": "idle",
            "at": None,
            "error": None,
            "error_code": None,
        }
        self._shutdown_complete = False
        # Recovery callbacks need all service state initialized first.
        self.tracker.retry_pending()

    def _stop_queues(self, *, timeout: float) -> bool:
        queues = [
            queue
            for name in ("jobs", "ai_jobs")
            if (queue := getattr(self, name, None)) is not None
        ]
        # Signal both before joining either, with one budget across both queues.
        for queue in queues:
            queue.request_stop()
        deadline = time.monotonic() + max(0.0, timeout)
        stopped = True
        for queue in queues:
            if not queue.stop(timeout=max(0.0, deadline - time.monotonic())):
                stopped = False
                record_error(
                    "player-lifecycle",
                    f"{queue.name} did not stop before the deadline",
                    with_trace=False,
                )
        return stopped

    def shutdown(self, *, timeout: float = JOB_STOP_TIMEOUT_SECONDS) -> bool:
        """Bound queue joins; retain the store while any callback still uses it."""
        with self._lifecycle_lock:
            if self._shutdown_complete:
                return True
            self.jobs.request_stop()
            self.ai_jobs.request_stop()
            self.tracker.flush()
            if not self._stop_queues(timeout=timeout):
                return False
            # Synchronous HTTP writers are outside these queues and can outlive
            # ASGI cancellation. Keep the process-owned connection until a safe
            # configure replaces it, or until the backend process exits.
            self._shutdown_complete = True
            return True

    # --- GSI ------------------------------------------------------------------

    def observe_gsi(self, payload: dict[str, Any]) -> None:
        player: dict[str, Any] = (
            payload["player"] if isinstance(payload.get("player"), dict) else {}
        )
        account_id, steam64 = account_from_gsi(player)
        if account_id:
            # Broken GSI can send anything as the name; only text is stored.
            name = player.get("name")
            self._note_detected(
                account_id, steam64, name.strip()[:64] or None if isinstance(name, str) else None
            )
        self.tracker.observe(payload)

    def _note_detected(self, account_id: int, steam64: str | None, name: Any) -> None:
        if self._detected and self._detected["account_id"] == account_id:
            return
        self._detected = {"account_id": account_id, "steam_id64": steam64, "persona_name": name}
        self.store.upsert_player(account_id, source="gsi", steam_id64=steam64, persona_name=name)
        if self.store.primary_account_id() is None:
            self.store.set_primary(account_id, source="gsi")
            self.request_sync()

    def note_live_advice(
        self, clock: Any, decision_point: str, action: str, reason: str, mode: str
    ) -> None:
        self.tracker.note_advice(clock, decision_point, action, reason, mode)

    def advice_count(self, decision_points: set[str]) -> int:
        """How many live advice cards of these decision points this match has had."""
        return self.tracker.advice_count(decision_points)

    def recent_death(self, clock: Any, within: int = 90) -> dict[str, Any] | None:
        """A death of the last `within` seconds of match clock, for the live
        death advice (live_tools.py): the rescue items left unpressed, how fast
        it came and where it happened, with how many deaths of the last PLACE_WINDOW seconds were
        in the same place (zone and map half)."""
        death = self.tracker.last_death()
        if not death or not isinstance(clock, int) or not isinstance(death.get("t"), int):
            return None
        if not 0 <= clock - death["t"] <= within:
            return None
        return {
            "items": death["usable"],
            "place": _death_place(death),
            "recent": _recent_deaths(self.tracker.death_moments(), death["t"]),
            # Seconds from high HP to death (last_moments `burst_s`), None when slower.
            "burst": death.get("burst_s") if isinstance(death.get("burst_s"), int) else None,
        }

    def death_screen(
        self,
        state: dict[str, Any],
        lang: str,
        *,
        next_item_for_hero: bool,
        within: int = DEATH_SCREEN_WINDOW,
        role: str | None = None,
    ) -> dict[str, Any] | None:
        """The overlay card while the player waits to respawn (death_screen.py),
        from the death just recorded and the live state."""
        raw = state.get("extra_context")
        extra: dict[str, Any] = raw if isinstance(raw, dict) else {}
        clock = extra.get("clock_time")
        death = self.tracker.last_death()
        if (
            not death
            or not isinstance(clock, int)
            or not isinstance(death.get("t"), int)
            or not 0 <= clock - death["t"] <= within
        ):
            return None
        item = (
            self.next_item(
                str(state.get("hero") or ""),
                owned_items(extra),
                enemies=extra.get("enemy_heroes")
                if isinstance(extra.get("enemy_heroes"), list)
                else None,
                minute=state.get("minute"),
                gold=state.get("gold"),
                role=role,
            )
            if next_item_for_hero
            else None
        )
        inputs: dict[str, Any] = {
            "death": death,
            "place": _death_place(death),
            "respawn": extra.get("respawn_seconds"),
            "gold": extra.get("available_gold", state.get("gold")),
            "buyback_cost": extra.get("buyback_cost"),
            "buyback_cooldown": extra.get("buyback_cooldown"),
            "danger": extra.get("base_danger"),
            "minute": state.get("minute"),
            "next_item": item,
        }
        card = build_death_screen(**inputs, lang=lang)
        if card is not None and lang != "en":
            # Spoken in English when Windows has no Ukrainian voice (overlay/voice.js).
            english = build_death_screen(**inputs, lang="en")
            if english is not None:
                card["lines_en"] = english["lines"]
        if card is not None:
            # Stable per death (the lines change with the gold): the overlay reads it once.
            card["id"] = f"{death.get('match_id') or ''}:{death['t']}"
        return card

    def check_stale(self) -> None:
        self.tracker.check_stale()

    def game_plan(self, hero: str, lang: str, role: str | None = None) -> dict[str, Any] | None:
        """The overlay's plan for the first 1:30 (app/game_plan.py); polled every
        second, so it is cached for a minute per account, hero, language and the
        live role (the high-rank build is the one of the player's position)."""
        primary = self.store.primary_account_id()
        hero_id = hero_id_from_name(hero)
        if primary is None or hero_id is None:
            return None
        key = (primary, hero_id, lang, role)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        focus = self._focus(primary)
        # Extra rows so that matches without a result do not shorten the record.
        on_hero = self.store.matches_for_career(primary, limit=40, hero_id=hero_id)
        plan = build_game_plan(
            focus=focus_summary(focus, [], lang)["title"] if focus else None,
            hero=hero_name(hero_id),
            history=on_hero[:20],
            record_history=on_hero,
            all_recent=self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT),
            meta=self._live_meta(hero_id),
            lang=lang,
            skills=self.skill_build(hero),
            high_build=stratz_builds.build(hero_id, hero, role),
        )
        self._plans[key] = (now, plan)
        return plan

    def lane_records(self) -> dict[str, dict[str, int]]:
        """The player's past lanes per enemy core (lane_duel.lane_records over
        the reviewed matches), for the live «hard lane» tip; cached a minute."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {}
        key = ("lane_records", primary)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        records = lane_records(self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT))
        self._plans[key] = (now, records)
        return records

    def key_item(self, hero: str) -> dict[str, Any] | None:
        """The hero's most bought mid/early item and its typical finish time
        (cached OpenDota meta, app/game_plan.key_item) for the live timing tip;
        None without cached meta or a timing. Polled every second: cached."""
        hero_id = hero_id_from_name(hero)
        if hero_id is None:
            return None
        key = ("key_item", hero_id)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        item = key_item(self._live_meta(hero_id))
        result = item if item and item.get("typical_t") else None
        self._plans[key] = (now, result)
        return result

    def skill_build(self, hero: str, enemies: list[str] | None = None) -> dict[str, Any] | None:
        """How pro players level the hero (app/skill_build.skill_order) for the live
        skill tip and the game plan; read once a minute, fetched on the job thread
        when missing or a week old (stale data is used meanwhile)."""
        hero_id = hero_id_from_name(hero)
        if hero_id is None:
            return None
        key = ("skills", hero_id)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return self._planned_skills(hero, cached[1], enemies)
        store_key = f"{SKILLS_KEY}:{hero_id}"
        client = self.client
        stored = self.store.cache_get(store_key)
        # Cached before the talent rows were kept (0.23): fetched again.
        old = isinstance(stored, dict) and "talents" not in stored
        if client is not None and (
            old or self.store.cache_get(store_key, max_age=META_TTL_SECONDS) is None
        ):
            self.jobs.submit(
                f"skills:{hero_id}",
                lambda: self._refresh(
                    store_key,
                    META_TTL_SECONDS,
                    lambda: client.pro_skill_orders(hero_id),
                    force=old,
                ),
            )
        build = skill_order(stored)
        self._plans[key] = (now, build)
        return self._planned_skills(hero, build, enemies)

    @staticmethod
    def _planned_skills(
        hero: str, build: dict[str, Any] | None, enemies: list[str] | None
    ) -> dict[str, Any] | None:
        """A hero plan's skill build (high-rank games, its talents for the enemy
        lineup) over the few pro games; their ability names stay for the texts
        (the ultimate's too), with the plan's own names over them."""
        planned = plan_skills(plan_for(hero, get_hero_position(hero)), enemies)
        if planned is None:
            return build
        # The pro games also name the ultimate; the plan names its own order.
        return {**planned, "names": {**((build or {}).get("names") or {}), **planned["names"]}}

    def next_item(
        self,
        hero: str,
        owned: list[str] | None,
        *,
        enemies: list[str] | None = None,
        minute: Any = None,
        gold: Any = None,
        role: str | None = None,
    ) -> dict[str, Any] | None:
        """The next item of the hero's usual build and the gold its missing parts
        cost (app/next_item.py) for a core's live farm advice; None when unknown.
        `gold`: the gold carried, for the net worth a hero plan's tempo build
        reads (next_item.net_worth). `role`: the live role (live_role.py); a hero
        plan applies only in its own position, else the hero's usual one."""
        hero_id = hero_id_from_name(hero)
        if hero_id is None or owned is None:
            return None
        meta = self._live_meta(hero_id)
        position = role or get_hero_position(hero)
        # How this match's deaths went and the enemy heroes seen pick the item
        # first (BKB after deaths under stuns, Linken's against Primal Roar),
        # then the hero's usual build.
        situational = situational_item(
            self.tracker.death_moments(),
            owned,
            meta,
            enemies=enemies,
            position=position,
            minute=minute if isinstance(minute, int) else None,
            hero=hero,
            net_worth=net_worth(owned, gold, (meta or {}).get("constants")),
        )
        if situational is not None:
            return situational
        # The hero plan's usual order (high-rank won games), else the popular build.
        plan = plan_for(hero, position)
        listed = (
            next_listed_item(plan["build"], meta, owned) if plan and plan.get("build") else None
        )
        return listed or next_build_item(meta, owned)

    def buy_now(
        self, hero: str, item_key: str, owned: list[str] | None, gold: int | None
    ) -> dict[str, Any] | None:
        """The part of `item_key` the player's gold buys now (next_item.buy_now) for
        the «gold unspent» card; None when unknown or nothing fits."""
        hero_id = hero_id_from_name(hero)
        if hero_id is None or owned is None or gold is None:
            return None
        constants = (self._live_meta(hero_id) or {}).get("constants") or {}
        if not has_components(constants):
            return None
        return buy_now(item_key, owned, constants, gold)

    def draft_item(
        self,
        hero: str,
        owned: list[str] | None,
        enemies: list[str] | None,
        position: str | None = None,
    ) -> dict[str, Any] | None:
        """The counter item to plan for against the enemy heroes seen, for a core
        early in the match (situational_items.draft_item); `position` is the live
        role, else the hero's usual one."""
        hero_id = hero_id_from_name(hero)
        if hero_id is None or owned is None:
            return None
        position = position or get_hero_position(hero)
        return draft_counter_item(enemies, owned, self._live_meta(hero_id), position, hero)

    def fight_abilities(self, hero: str, position: str | None) -> dict[str, Any] | None:
        """The hero plan's abilities for the fight summary (hero_items.plan_fight)."""
        return plan_fight(plan_for(hero, position or get_hero_position(hero)))

    def plan_note(
        self, hero: str, enemies: list[str] | None, minute: int | None, position: str | None
    ) -> dict[str, Any] | None:
        """The hero plan's advice with no item for the enemy lineup seen
        (hero_items.plan_note): {id, enemy, reason}; None otherwise."""
        return plan_note(plan_for(hero, position or get_hero_position(hero)), enemies, minute)

    def save_item(
        self, hero: str, owned: list[str] | None, enemies: list[str] | None = None
    ) -> dict[str, Any] | None:
        """The save item for the support's «no save item» tip: the one against
        the enemy lineup seen (situational_items.lineup_save_item), else the one
        most bought on the hero, with the gold its missing parts cost; None
        when unknown."""
        hero_id = hero_id_from_name(hero)
        if owned is None:
            return None
        meta = self._live_meta(hero_id) if hero_id is not None else None
        lineup = lineup_save_item(enemies, owned, meta)
        if lineup is not None:
            return lineup
        if hero_id is None:
            return None
        return save_build_item(meta, owned, SAVE_ITEMS)

    def start_items(self, hero: str, role: str | None = None) -> list[dict[str, Any]]:
        """The hero's usual starting purchase for the empty-bag and strategy-time
        cards: high-rank players in the player's position (app/stratz_builds.py),
        else OpenDota's popularity (app/hero_meta.start_items); [] when unknown.
        Polled every second: cached."""
        hero_id = hero_id_from_name(hero)
        if hero_id is None:
            return []
        high = stratz_builds.start_items(hero_id, hero, role)
        if high:
            return high
        key = ("start_items", hero_id)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        meta = self._live_meta(hero_id) or {}
        items = start_items(meta.get("popularity"), meta.get("constants"))
        self._plans[key] = (now, items)
        return items

    def _live_meta(self, hero_id: int) -> dict[str, Any] | None:
        """The hero's cached build data for live tips, read once a minute (they
        are polled every second). A hero with nothing cached yet (never reviewed)
        gets it fetched on the job thread, so the next read has it."""
        key = ("meta", hero_id)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        meta = self._hero_meta(hero_id)
        if self.client is not None and (
            not meta or meta.get("popularity") is None or not has_components(meta["constants"])
        ):
            self.jobs.submit(f"meta:{hero_id}", lambda: self._ensure_hero_meta(hero_id))
        self._plans[key] = (now, meta)
        return meta

    def summary(self, lang: str) -> dict[str, Any] | None:
        """The card at the top of Home (app/home_summary.py): the last reviewed
        match, the day, the goals and the focus; cached a minute like the week."""
        primary = self.store.primary_account_id()
        if primary is None:
            return None
        key = ("summary", primary, lang, self.store.get_meta(f"last_review:{primary}"))
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        summary = home_summary(
            self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT),
            lang,
            today=self._today(primary),
            focus=self._focus(primary),
            **self._goals_and_tilt(primary),
        )
        self._plans[key] = (now, summary)
        return summary

    def profile(self, lang: str) -> dict[str, Any] | None:
        """The «Профіль» tab (app/player_profile.py): rating graph, level,
        achievements and sparks, from the whole match table."""
        primary = self.store.primary_account_id()
        if primary is None:
            return None
        rows = self.store.profile_rows(primary, limit=PROFILE_MATCHES_LIMIT)
        return build_profile(
            rows,
            player=self.store.get_player(primary),
            mmr_raw=self.store.get_meta(f"mmr:{primary}"),
            cosmetics_raw=self.store.get_meta(f"cosmetics:{primary}"),
            lang=lang,
            now=time.time(),
        )

    def shop_action(self, action: str, item_id: str, lang: str) -> dict[str, Any]:
        """Buy or wear a profile look (cosmetics.py); ValueError(code) when not
        possible. The balance and the unlocks come from the profile itself."""
        primary = self.store.primary_account_id()
        if primary is None:
            raise ValueError("not_linked")
        with self._shop_lock:
            profile = self.profile(lang) or {}
            key = f"cosmetics:{primary}"
            state = cosmetics.load(self.store.get_meta(key))
            level = int((profile.get("level") or {}).get("level") or 1)
            tiers = {b["id"]: b["tier"] for b in profile.get("achievements") or []}
            if action == "buy":
                balance = int((profile.get("sparks") or {}).get("balance") or 0)
                state = cosmetics.buy(state, item_id, balance=balance, level=level, tiers=tiers)
            else:
                state = cosmetics.equip(state, item_id, level=level, tiers=tiers)
            self.store.set_meta(key, cosmetics.dump(state))
        return self.profile(lang) or {}

    def set_mmr(self, mmr: int) -> None:
        """The player's MMR now: a new anchor of the rating graph."""
        primary = self.store.primary_account_id()
        if primary is None:
            raise ValueError("not_linked")
        if not MMR_MIN <= int(mmr) <= MMR_MAX:
            raise ValueError("bad_mmr")
        key = f"mmr:{primary}"
        self.store.set_meta(key, add_anchor(self.store.get_meta(key), int(mmr), time.time()))

    def clear_mmr(self) -> None:
        primary = self.store.primary_account_id()
        if primary is not None:
            self.store.set_meta(f"mmr:{primary}", None)

    def week(
        self, lang: str, until: float | None = None, since: float | None = None
    ) -> dict[str, Any] | None:
        """The home screen's last seven days (app/weekly_summary.py); cached a
        minute like the game plan, since Home asks for it on every visit.
        `since` / `until`: another period (the launcher's weekly Discord post
        asks for the local calendar week that just ended)."""
        primary = self.store.primary_account_id()
        if primary is None:
            return None
        key = ("week", primary, lang, until, since)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        summary = weekly_summary(
            self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT),
            time.time() if until is None else until,
            lang,
            focus=self._focus(primary),
            since=since,
        )
        self._plans[key] = (now, summary)
        return summary

    def session(self, lang: str) -> dict[str, Any] | None:
        """The latest sitting of 2+ games with a text to share (app/session_summary.py);
        cached a minute like the week."""
        primary = self.store.primary_account_id()
        if primary is None:
            return None
        key = ("session", primary, lang)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        summary = session_summary(
            self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT),
            time.time(),
            lang,
            focus=self._focus(primary),
        )
        self._plans[key] = (now, summary)
        return summary

    def usage(self, since: int, until: int) -> dict[str, Any]:
        """Advice counts for the opt-in anonymous statistics (usage_stats.py)."""
        primary = self.store.primary_account_id()
        matches = (
            self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT) if primary else []
        )
        return usage_stats(matches, since, until)

    def role_prior(self, hero: str) -> dict[str, Any] | None:
        """The position to assume before the lane is known (app/live_role.py): the
        usual one of the player's reviews on this hero (2+), else OpenDota's role
        tags of the hero. Polled every second, so cached like the game plan."""
        hero_id = hero_id_from_name(hero)
        if hero_id is None:
            return None
        primary = self.store.primary_account_id()
        key = ("role", primary, hero_id)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        prior = _role_prior(
            self.store.matches_for_career(primary, limit=20, hero_id=hero_id)
            if primary is not None
            else [],
            next(
                (
                    row.get("roles") or []
                    for row in self.store.cache_get(HERO_STATS_KEY) or []
                    if isinstance(row, dict) and row.get("hero_id") == hero_id
                ),
                [],
            ),
            hero_name(hero_id),
        )
        self._plans[key] = (now, prior)
        return prior

    def diagnostics(self) -> dict[str, Any]:
        """For the problem report: no key, no match data, just the state."""
        status = self.status()
        ai = self.ai_status()
        with self._coach_lock:
            coach_jobs = {key: dict(value) for key, value in self._coach_jobs.items()}
        return {
            "linked": status["linked"],
            "account_id": status["account_id"],
            "source": status["source"],
            "opendota": status["opendota"],
            "sync": status["sync"],
            "matches": status["matches"],
            "match_sources": self.store.source_counts(status["account_id"])
            if status["account_id"]
            else {},
            "live_match": status["live_match"],
            "pending_match_finishes": self.tracker.pending_count(),
            "last_recorded_match": self._last_recorded(status["account_id"]),
            "jobs": self.jobs.pending(),
            "ai_jobs": self.ai_jobs.pending(),
            "coach_jobs": coach_jobs,
            "ai": {key: ai.get(key) for key in ("configured", "provider", "model", "source")},
            "opendota_key": {
                key: value for key, value in self.opendota_status().items() if key != "key_hint"
            },
            "analysis_version": ANALYSIS_VERSION,
            "secrets": self.secrets_status(),
            # Verdict counts per decision point only, never the advice text.
            "advice_feedback": self.advice_feedback_summary(),
        }

    def operations(self) -> dict[str, Any]:
        """Queue and match-finish health for operations_health.build."""
        with self._sync_lock:
            sync = {key: self._sync.get(key) for key in ("state", "at")}
        return {
            "jobs": self.jobs.health(),
            "ai_jobs": self.ai_jobs.health(),
            "match_finish": self.tracker.health(),
            "sync": sync,
        }

    def _last_recorded(self, account_id: Any) -> dict[str, Any] | None:
        """The newest match the app recorded from live GSI, in counts only: a
        problem report then says whether the last game was recorded at all."""
        if not account_id:
            return None
        rows = self.store.list_matches(int(account_id), limit=10)
        row = next((r for r in rows if r.get("has_timeline")), None)
        if row is None:
            return None
        match = self.store.get_match(int(account_id), int(row["match_id"])) or {}
        timeline = match.get("timeline") if isinstance(match.get("timeline"), dict) else {}
        deaths = [d for d in timeline.get("deaths") or [] if isinstance(d, dict)]
        return {
            "match_id": row["match_id"],
            "hero": row.get("hero"),
            "start_time": row.get("start_time"),
            "duration": row.get("duration"),
            "samples": len(timeline.get("samples") or []),
            "deaths": len(deaths),
            "deaths_with_last_seconds": sum(1 for d in deaths if d.get("last")),
            "advice": len(timeline.get("advice") or []),
            "analysed": bool(row.get("has_analysis")),
            "score": row.get("score"),
        }

    # --- account --------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        primary = self.store.primary_account_id()
        player = self.store.get_player(primary) if primary else None
        detected = self._detected
        return {
            "linked": primary is not None,
            "account_id": primary,
            "source": self.store.primary_source(),
            "player": _public_player(player, primary),
            "detected": detected if detected and detected["account_id"] != primary else None,
            "opendota": self.client is not None,
            "sync": dict(self._sync),
            "matches": self.store.count_matches(primary) if primary else 0,
            "live_match": self.tracker.current(),
            "last_review": self._last_review(),
            "pending_jobs": len(self.jobs.pending()),
            "ai": {"configured": self.ai_configured()},
            "opendota_key": bool(self._opendota_key()[0]),
            "today": self._today(primary) if primary else None,
            **self._goals_and_tilt(primary),
        }

    def _goals_and_tilt(self, account_id: int | None) -> dict[str, Any]:
        """Streak goals and the tilt warning (player_goals.py) from the match table."""
        if account_id is None:
            return {"goals": [], "tilt": None}
        rows = self.store.list_matches(account_id, limit=GOAL_MATCHES)
        return {"goals": goal_streaks(rows), "tilt": tilt(rows, int(time.time()))}

    def _today(self, account_id: int) -> dict[str, Any] | None:
        """Tonight's session on the home screen: matches since local midnight."""
        midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        since = int(midnight.timestamp())
        rows = [
            m
            for m in self.store.list_matches(account_id, limit=TODAY_MAX_MATCHES)
            if (m.get("start_time") or 0) >= since
        ]
        if not rows:
            return None
        decided = [m for m in rows if m.get("win") is not None]
        wins = sum(1 for m in decided if m["win"])
        scores = [m["score"] for m in rows if isinstance(m.get("score"), (int, float))]
        today: dict[str, Any] = {
            "games": len(rows),
            "wins": wins,
            "losses": len(decided) - wins,
            "avg_score": round(sum(scores) / len(scores)) if scores else None,
        }
        focus = self._focus(account_id)
        if focus is not None:
            # Only now the reviews are read (the status is polled every few seconds).
            results = [
                match_result(m.get("analysis"), focus)
                for m in self.store.matches_for_career(account_id, limit=len(rows))
                if (m.get("start_time") or 0) >= since and played_after(m, focus)
            ]
            results = [r for r in results if r is not None]
            if results:
                today["focus_met"] = sum(1 for r in results if r)
                today["focus_total"] = len(results)
        return today

    def link(self, value: Any) -> dict[str, Any]:
        account_id = parse_account_id(value)
        self.store.upsert_player(
            account_id, source="manual", steam_id64=str(steam64_from_account_id(account_id))
        )
        self.store.set_primary(account_id, source="manual")
        self.request_sync()
        return self.status()

    def unlink(self) -> dict[str, Any]:
        self.store.clear_primary()
        return self.status()

    # --- history --------------------------------------------------------------

    def list_matches(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        hero_id: int | None = None,
        win: bool | None = None,
        sort: str = "date",
        ascending: bool = False,
    ) -> dict[str, Any]:
        """The match table; hero_id / win filter it (totals and stats follow the
        filter), sort / ascending order it (newest first by default)."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"linked": False, "items": [], "total": 0}
        rows = self.store.list_matches(
            primary,
            limit=limit,
            offset=offset,
            hero_id=hero_id,
            win=win,
            sort=sort,
            ascending=ascending,
        )
        self._backfill_items(primary, rows)
        return {
            "linked": True,
            "items": rows,
            "total": self.store.count_matches(primary, hero_id=hero_id, win=win),
            "stats": self.store.match_stats(primary, hero_id=hero_id, win=win),
            "heroes": self.store.hero_counts(primary),
            "filters": {"hero_id": hero_id, "win": win, "sort": sort, "ascending": ascending},
            "sync": dict(self._sync),
            "skipped": self.skipped_modes(primary),
        }

    def match_detail(
        self, match_id: int, lang: str, *, force_coach: bool = False
    ) -> dict[str, Any] | None:
        primary = self.store.primary_account_id()
        if primary is None:
            return None
        record = self.store.get_match(primary, match_id)
        if record is None:
            return None
        analysis = record.get("analysis")
        if analysis is not None and (
            analysis.get("version") != ANALYSIS_VERSION or not analysis_core_valid(analysis)
        ):
            analysis = None  # rules changed since it was stored
        if analysis is None and (record.get("opendota") or record.get("timeline")):
            analysis = self._rebuild_analysis(primary, match_id)
        if analysis is None and self.client is not None:
            self.fetch_match(match_id, request_parse=False)
        elif self.client is not None and _trim_is_old(record):
            # Stored before trim_match kept what the review now reads (the skill
            # order): shown as it is now, fetched again and rebuilt in the background.
            self.fetch_match(match_id, request_parse=False)
        if record.get("items") is None and analysis is not None:
            # A review stored before 0.50: its final items for the header.
            record["items"] = self._record_items(primary, record)
        detail = {
            "match_id": match_id,
            "summary": {key: record.get(key) for key in _SUMMARY_KEYS},
            "sources": record.get("sources"),
            "parse_status": record.get("parse_status") or "",
            "analysis": render_analysis(analysis, lang) if analysis else None,
            "scoreboard": _scoreboard(
                record.get("opendota"),
                (self.store.cache_get(ITEM_CONSTANTS_KEY) or {}).get("by_id") or {},
            ),
            "loading": analysis is None and self.client is not None,
        }
        # Before the coach: the AI review mentions the player's focus when there is one,
        # and the mistakes that keep coming back.
        detail["focus"] = self._match_focus(primary, record, analysis, lang)
        detail["repeats"] = self._repeats(primary, record, analysis)
        detail["coach"] = self._match_coach(primary, match_id, detail, lang, force=force_coach)
        detail["baseline"] = self._baseline(primary, record, analysis)
        detail["best_on_hero"] = self._best_on_hero(primary, record, analysis)
        detail["questions"] = _shown_questions(
            self._questions(primary, match_id, facts=match_facts(detail))
        )
        current = self._focus(primary)
        detail["focus_id"] = current["id"] if current else None
        # The review's top problems that can become the player's focus.
        detail["focusable"] = [
            finding_id
            for finding_id in (analysis or {}).get("focus") or []
            if can_focus(finding_id)
        ]
        # «Корисно / не до речі / повторювалося» on the live advice cards (local).
        verdicts = advice_feedback.load(self.store, primary, match_id)
        detail["advice_feedback"] = verdicts
        rendered = detail["analysis"] if isinstance(detail["analysis"], dict) else {}
        for item in rendered.get("advice") or []:
            if isinstance(item, dict):
                item["key"] = advice_feedback.advice_key(item)
                item["feedback"] = verdicts.get(item["key"] or "")
        return detail

    def set_advice_feedback(self, match_id: int, key: str, verdict: str | None) -> dict[str, Any]:
        """The player's verdict on one live advice card of a match (advice_feedback.py)."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"status": "error", "code": "unlinked"}
        if self.store.get_match(primary, int(match_id)) is None:
            return {"status": "error", "code": "match_not_found"}
        try:
            feedback = advice_feedback.set_verdict(self.store, primary, int(match_id), key, verdict)
        except ValueError:
            return {"status": "error", "code": "bad_feedback"}
        return {"status": "ok", "feedback": feedback}

    def advice_feedback_summary(self) -> dict[str, Any]:
        primary = self.store.primary_account_id()
        if primary is None:
            return {"matches": 0, "totals": {}, "by_decision_point": {}, "quieter": []}
        return advice_feedback.summary(self.store, primary)

    def _repeats(
        self, account_id: int, record: dict[str, Any], analysis: dict[str, Any] | None
    ) -> dict[str, dict[str, int]]:
        """The problems of this match that the player's earlier matches had too."""
        start = record.get("start_time")
        if not analysis or not isinstance(start, (int, float)):
            return {}
        earlier = self.store.matches_for_career(account_id, limit=REPEATS_LOOKUP, before=int(start))
        return finding_history(record, analysis, earlier)

    def _best_on_hero(
        self, account_id: int, record: dict[str, Any], analysis: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """The player's best other match on this hero (highest review score), with
        its last hits / gold / XP curves for the review chart; `self_best` when
        this match is the best one."""
        hero_id = record.get("hero_id")
        score = ((analysis or {}).get("headline") or {}).get("score")
        if not hero_id or not isinstance(score, (int, float)):
            return None
        others = [
            row
            for row in self.store.matches_for_career(
                account_id, limit=BEST_ON_HERO_LOOKUP, hero_id=int(hero_id)
            )
            if row.get("match_id") != record.get("match_id")
            and isinstance(
                ((row.get("analysis") or {}).get("headline") or {}).get("score"), (int, float)
            )
        ]
        if len(others) < BEST_ON_HERO_MIN:
            return None
        best = max(others, key=lambda row: row["analysis"]["headline"]["score"])
        best_score = best["analysis"]["headline"]["score"]
        if best_score <= score:
            return {"self_best": True, "of": len(others) + 1}
        series = best["analysis"].get("series") or {}
        return {
            "match_id": best.get("match_id"),
            "score": best_score,
            "start_time": best.get("start_time"),
            "win": best.get("win"),
            "series": {key: series.get(key) for key in ("last_hits", "gold", "xp")},
        }

    def _baseline(
        self, account_id: int, record: dict[str, Any], analysis: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """This match against the player's other matches on the same hero."""
        hero_id = record.get("hero_id")
        if not hero_id:
            return None
        others = self.store.matches_for_career(
            account_id, limit=MAX_BASELINE_GAMES + 1, hero_id=int(hero_id)
        )
        return personal_baseline({**record, "analysis": analysis}, others)

    # --- share a review (share_review.py) -----------------------------------------------

    def share_payload(
        self, match_id: int, lang: str, *, with_coach: bool = False
    ) -> dict[str, Any] | None:
        """The public part of a review; the AI coach is not asked to write one."""
        primary = self.store.primary_account_id()
        if primary is None or self.store.get_match(primary, match_id) is None:
            return None
        detail = self.match_detail(match_id, lang)
        return public_review(detail, lang, with_coach=with_coach) if detail else None

    def share_progress_payload(
        self, lang: str, *, with_coach: bool = False
    ) -> dict[str, Any] | None:
        """The public part of Progress (all heroes); None before a reviewed match."""
        career = self.career(lang)
        return public_progress(career, lang, with_coach=with_coach)

    # --- history backup (history_backup.py) ---------------------------------------------

    def export_backup(self, app_version: str) -> dict[str, Any]:
        self.tracker.flush()
        return export_backup(self.store, app_version)

    def import_backup(self, data: Any) -> dict[str, Any]:
        result = import_backup(self.store, data)
        self._plans.clear()  # plans, week and today read the matches again
        if result["linked"]:
            self.request_sync()
        return result

    # --- automatic local copies (auto_backup.py) ----------------------------------------

    def backups_status(self) -> dict[str, Any]:
        return {
            "enabled": self.store.get_meta(AUTO_BACKUP_META) != "off",
            "every_days": AUTO_BACKUP_EVERY_SECONDS // 86400,
            "keep": AUTO_BACKUP_KEEP,
            "budget_mb": AUTO_BACKUP_BUDGET // (1024 * 1024),
            "items": self.backups.items(),
        }

    def set_backups_enabled(self, enabled: bool) -> dict[str, Any]:
        self.store.set_meta(AUTO_BACKUP_META, None if enabled else "off")
        return self.backups_status()

    def make_backup(self, app_version: str, kind: str = "manual") -> dict[str, Any]:
        """A copy now (the launcher's «Зробити копію зараз», or a due automatic one)."""
        item = self.backups.write(self.export_backup(app_version), kind)
        self.store.set_meta(AUTO_BACKUP_VERSION_META, app_version)
        return item

    def auto_backup(self, app_version: str) -> dict[str, Any]:
        """Called by the launcher once a day: a copy when the newest is a week old,
        or the first time a new app version runs (the history before an update)."""
        if self.store.get_meta(AUTO_BACKUP_META) == "off":
            return {"made": None, "reason": "off"}
        last_version = self.store.get_meta(AUTO_BACKUP_VERSION_META)
        age = self.backups.newest_age()
        if last_version and last_version != app_version:
            kind = "update"
        elif age is None or age >= AUTO_BACKUP_EVERY_SECONDS:
            kind = "weekly"
        else:
            return {"made": None, "reason": "recent"}
        data = self.export_backup(app_version)
        if not (data.get("counts") or {}).get("matches"):
            # Nothing to keep yet; the version is remembered for the next update.
            self.store.set_meta(AUTO_BACKUP_VERSION_META, app_version)
            return {"made": None, "reason": "empty"}
        item = self.backups.write(data, kind)
        self.store.set_meta(AUTO_BACKUP_VERSION_META, app_version)
        return {"made": item, "reason": kind}

    def preview_backup_copy(self, backup_id: str) -> dict[str, Any]:
        return preview_backup(self.store, self.backups.read(backup_id))

    def restore_backup_copy(self, backup_id: str) -> dict[str, Any]:
        return self.import_backup(self.backups.read(backup_id))

    # --- compare with a friend (friend_compare.py) --------------------------------------

    def _friend_id(self, account_id: int) -> int | None:
        raw = self.store.get_meta(f"{FRIEND_META}:{account_id}")
        with contextlib.suppress(ValueError, TypeError):
            return int(json.loads(raw)["account_id"]) if raw else None
        return None

    def set_friend(self, value: Any, lang: str) -> dict[str, Any]:
        """Remember the friend to compare with and fetch their matches."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"state": "unlinked"}
        friend_id = parse_account_id(value)
        if friend_id == primary:
            return {"state": "self"}
        self.store.set_meta(
            f"{FRIEND_META}:{primary}",
            json.dumps({"account_id": friend_id, "added_at": _now_iso()}),
        )
        self._request_friend(friend_id)
        return self.friend(lang)

    def remove_friend(self) -> dict[str, Any]:
        primary = self.store.primary_account_id()
        if primary is not None:
            self.store.set_meta(f"{FRIEND_META}:{primary}", None)
        return {"state": "none"}

    def refresh_friend(self, lang: str) -> dict[str, Any]:
        primary = self.store.primary_account_id()
        friend_id = self._friend_id(primary) if primary is not None else None
        if friend_id is not None:
            self._request_friend(friend_id)
        return self.friend(lang)

    def _request_friend(self, friend_id: int) -> None:
        if self.client is None:
            return
        self._friend_errors.pop(friend_id, None)
        self.jobs.submit(f"friend:{friend_id}", lambda: self._job_fetch_friend(friend_id))

    def _job_fetch_friend(self, friend_id: int) -> None:
        client = self.client
        if client is None:
            return
        try:
            profile: dict[str, Any] | None = None
            try:
                profile = client.player(friend_id)
            except OpenDotaError as error:
                if error.code != "private":
                    raise
            rows = client.recent_matches(friend_id, limit=RECENT_MATCHES_LIMIT)
        except OpenDotaError as error:
            self._friend_errors[friend_id] = error.code or "error"
            return
        matches = [row for row in rows if is_reviewable_match(row)]
        self.store.cache_set(
            f"{FRIEND_CACHE}:{friend_id}",
            {"profile": profile, "matches": matches, "fetched_at": time.time()},
        )

    def friend(self, lang: str, group: str = "all") -> dict[str, Any]:
        """The comparison with the saved friend (state none / loading / ready / ...)."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"state": "unlinked"}
        friend_id = self._friend_id(primary)
        if friend_id is None:
            return {"state": "none"}
        result: dict[str, Any] = {"friend": {"account_id": friend_id}}
        cached = self.store.cache_get(f"{FRIEND_CACHE}:{friend_id}")
        loading = f"friend:{friend_id}" in self.jobs.pending()
        if cached is None:
            if self.client is None:
                return {**result, "state": "offline"}
            if friend_id in self._friend_errors:
                return {**result, "state": "error", "code": self._friend_errors[friend_id]}
            if not loading:
                self._request_friend(friend_id)
            return {**result, "state": "loading"}
        profile = cached.get("profile") or {}
        result["friend"].update(
            name=profile.get("persona_name"),
            avatar_url=profile.get("avatar_url"),
            rank=rank_label(profile.get("rank_tier"), lang),
        )
        me = self.store.get_player(primary) or {}
        result["me"] = {
            "name": me.get("persona_name"),
            "rank": rank_label(me.get("rank_tier"), lang),
        }
        result["fetched_at"] = cached.get("fetched_at")
        result["refreshing"] = loading
        if friend_id in self._friend_errors:
            result["error"] = self._friend_errors[friend_id]
        theirs = cached.get("matches") or []
        if not theirs:
            # OpenDota shows no matches of an account that hides its match data.
            return {**result, "state": "private"}
        mine = [
            row
            for row in self.store.list_matches(primary, limit=RECENT_MATCHES_LIMIT)
            if is_reviewable_match(row)
        ]
        return {**result, "state": "ready", **compare(mine, theirs, group)}

    # --- focus goal (focus_goal.py) ---------------------------------------------------

    def _focus(self, account_id: int) -> dict[str, Any] | None:
        raw = self.store.get_meta(f"{FOCUS_META}:{account_id}")
        if not raw:
            return None
        with contextlib.suppress(ValueError, TypeError):
            focus = json.loads(raw)
            if isinstance(focus, dict) and can_focus(str(focus.get("id"))):
                return focus
        return None

    def set_focus(self, finding_id: str) -> dict[str, Any]:
        """Work on one problem from now on; its wording comes from its latest occurrence."""
        primary = self.store.primary_account_id()
        if primary is None:
            raise ValueError("not_linked")
        finding_id = str(finding_id or "")
        if not can_focus(finding_id) or finding_id in NOT_RECURRING:
            raise ValueError("bad_focus")
        latest: dict[str, Any] = {}
        for match in self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT):
            found = next(
                (
                    f
                    for f in (match.get("analysis") or {}).get("improvements") or []
                    if f.get("id") == finding_id
                ),
                None,
            )
            if found:
                latest = found
                break
        focus = new_focus(finding_id, latest.get("section"), latest.get("params"))
        self.store.set_meta(f"{FOCUS_META}:{primary}", json.dumps(focus))
        self._plans.clear()
        return focus

    def focus_status(self, lang: str) -> dict[str, Any] | None:
        primary = self.store.primary_account_id()
        if primary is None:
            return None
        focus = self._focus(primary)
        if focus is None:
            return None
        matches = self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT)
        return focus_summary(focus, matches, lang)

    def clear_focus(self) -> None:
        primary = self.store.primary_account_id()
        if primary is not None:
            self.store.set_meta(f"{FOCUS_META}:{primary}", None)
        self._plans.clear()

    def _match_focus(
        self, account_id: int, record: dict[str, Any], analysis: dict[str, Any] | None, lang: str
    ) -> dict[str, Any] | None:
        focus = self._focus(account_id)
        if focus is None or not played_after(record, focus):
            return None
        met = match_result(analysis, focus)
        if met is None:
            return None
        summary = focus_summary(focus, [], lang)
        return {"id": focus["id"], "title": summary["title"], "met": met}

    def career(
        self, lang: str, *, force_coach: bool = False, hero_id: int | None = None
    ) -> dict[str, Any]:
        """Progress over the recent matches; `hero_id` narrows it to one hero."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"linked": False}
        result, recent = self._career_result(primary, lang, hero_id)
        if hero_id is not None:
            # The AI career review covers all heroes; one per hero would spend
            # the player's free quota on every switch.
            result["coach"] = {"state": "none"}
            return result
        result["coach"] = self._career_coach(primary, result, recent, lang, force=force_coach)
        # The player's marks on live advice and what they made quieter (Progress).
        result["advice_feedback"] = advice_feedback.summary(self.store, primary)
        result["questions"] = _shown_questions(
            self.store.cache_get(f"{ASK_CACHE_KEY}:{primary}:career") or []
        )
        return result

    def _career_result(
        self, primary: int, lang: str, hero_id: int | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The career numbers and the recent review lines (the AI coach's facts)."""
        player = self.store.get_player(primary) or {}
        matches = self.store.matches_for_career(
            primary, limit=RECENT_MATCHES_LIMIT, hero_id=hero_id
        )
        for match in matches:
            stale = match.get("analysis")
            if stale is not None and (
                stale.get("version") != ANALYSIS_VERSION or not analysis_core_valid(stale)
            ):
                match["analysis"] = self._rebuild_analysis(primary, match["match_id"])
        result = analyze_career(
            matches,
            lang,
            rank_tier=player.get("rank_tier"),
            hero_stats=self.store.cache_get(HERO_STATS_KEY),
        )
        # Whether the averages compare like with like (review_basis.py).
        result["basis"] = review_basis.career_basis(
            [m.get("analysis") for m in matches], ANALYSIS_VERSION
        )
        result["linked"] = True
        result["hero_filter"] = hero_id
        focus = self._focus(primary)
        if focus is not None:
            # The goal is the same on every hero: judged over all recent matches.
            source = (
                matches
                if hero_id is None
                else self.store.matches_for_career(primary, limit=RECENT_MATCHES_LIMIT)
            )
            result["focus"] = focus_summary(focus, source, lang)
        else:
            result["focus"] = None
        # "heroes" is the career's own hero table; the filter's choices go apart.
        result["hero_choices"] = self.store.hero_counts(primary)
        result["rank_history"] = rank_history.summary(
            self.store.get_meta(f"rank_history:{primary}"), lang
        )
        recent = [
            recent_match_line(render_analysis(m["analysis"], lang))
            for m in matches
            if m.get("analysis")
        ]
        return result, recent

    def ask_career(
        self, question: str, lang: str, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """A free question about the recent matches (heroes, enemies, habits), answered
        from the career facts with the same fact check; nothing else is generated."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"ok": False, "code": "not_linked"}
        return self.asks.run(
            f"career:{primary}:{lang}",
            question,
            request_id,
            lambda: self._ask_career(primary, question, lang),
            wait_s=ASK_JOIN_WAIT_SECONDS,
        )

    def _ask_career(self, primary: int, question: str, lang: str) -> dict[str, Any]:
        if not self.ai_configured():
            return {"ok": False, "code": "off"}
        result, recent = self._career_result(primary, lang)
        facts = career_facts(result, recent)
        if facts is None:
            return {"ok": False, "code": "not_enough"}
        client = self.llm if self.llm is not None else self._coach_client_with(ASK_TIMEOUT_SECONDS)
        if client is None:
            return {"ok": False, "code": "off"}
        try:
            answer = answer_question(
                client,
                facts,
                question,
                lang,
                known_items=self._known_items(),
                about="career",
                deadline=time.monotonic() + ASK_DEADLINE_SECONDS,
            )
        except CoachLLMError as error:
            if error.code not in {"empty_question", "unverified"}:
                record_error("coach-ai", f"career question: {error.code}", with_trace=False)
            return {"ok": False, "code": error.code}
        except Exception as error:  # noqa: BLE001 - a bad answer must not become a 500
            record_error("coach-ai", error)
            return {"ok": False, "code": "bad_response"}
        entry = {
            "question": " ".join(str(question).split())[:QUESTION_LIMIT],
            "answer": answer["review"]["answer"],
            "at": _now_iso(),
            "lang": lang,
        }
        key = f"{ASK_CACHE_KEY}:{primary}:career"
        with self._ask_history_lock:
            history = [entry, *(self.store.cache_get(key) or [])][:ASK_HISTORY]
            self.store.cache_set(key, history)
        return {"ok": True, "answer": entry, "history": _shown_questions(history)}

    # --- OpenDota key --------------------------------------------------------------

    def _opendota_key(self) -> tuple[str, str | None]:
        stored = self.secrets.open(self.store.get_meta(OPENDOTA_KEY_META)) or ""
        if stored:
            return stored, "app"
        if self._env_opendota_key:
            return self._env_opendota_key, "env"
        return "", None

    def _apply_opendota_key(self) -> None:
        setter = getattr(self.client, "set_api_key", None)
        if callable(setter):
            setter(self._opendota_key()[0])

    def opendota_status(self) -> dict[str, Any]:
        """Never includes the key itself."""
        key, source = self._opendota_key()
        return {
            "enabled": self.client is not None,
            "configured": bool(key),
            "source": source,
            "key_hint": f"…{key[-4:]}" if len(key) >= 8 else "",
        }

    def set_opendota_key(self, api_key: str) -> dict[str, Any]:
        key = str(api_key or "").strip()
        if not OPENDOTA_KEY_RE.fullmatch(key):
            raise ValueError("bad_opendota_key")
        self.store.set_meta(OPENDOTA_KEY_META, self.secrets.seal(key))
        self._apply_opendota_key()
        return self.opendota_status()

    def clear_opendota_key(self) -> dict[str, Any]:
        self.store.set_meta(OPENDOTA_KEY_META, None)
        self._apply_opendota_key()
        return self.opendota_status()

    # --- stored keys (secret_box.py) ------------------------------------------------

    SECRET_METAS = (OPENDOTA_KEY_META, AI_SETTINGS_KEY)

    def _seal_stored_secrets(self) -> None:
        if not self.secrets.available:
            return
        for key in self.SECRET_METAS:
            raw = self.store.get_meta(key)
            if raw and not self.secrets.is_sealed(raw):
                sealed = self.secrets.seal(raw)
                if self.secrets.is_sealed(sealed):
                    self.store.set_meta(key, sealed)

    def secrets_status(self) -> dict[str, Any]:
        """How the stored keys are kept, in counts (for the problem report)."""
        counts = {"sealed": 0, "plain": 0, "locked": 0}
        for key in self.SECRET_METAS:
            raw = self.store.get_meta(key)
            if not raw:
                continue
            if not self.secrets.is_sealed(raw):
                counts["plain"] += 1
            elif self.secrets.open(raw) is None:
                counts["locked"] += 1
            else:
                counts["sealed"] += 1
        return {"sealing": self.secrets.kind, **counts}

    # --- AI coach ----------------------------------------------------------------

    def ai_settings(self) -> AISettings | None:
        raw = self.secrets.open(self.store.get_meta(AI_SETTINGS_KEY))
        stored = None
        if raw:
            with contextlib.suppress(ValueError):
                stored = settings_from(json.loads(raw), source="app")
        return stored or self.env_ai

    def ai_status(self) -> dict[str, Any]:
        settings = self.ai_settings()
        base = settings.public() if settings else {"configured": self.llm is not None}
        return {
            **base,
            "providers": [
                {"id": key, "label": value["label"], "model": value["model"]}
                for key, value in PROVIDERS.items()
            ],
        }

    def set_ai(self, provider: str, api_key: str, model: str | None = None) -> dict[str, Any]:
        settings = settings_from(
            {"provider": provider, "api_key": api_key, "model": model}, source="app"
        )
        if settings is None:
            raise ValueError("bad_ai_settings")
        self.store.set_meta(
            AI_SETTINGS_KEY,
            self.secrets.seal(
                json.dumps(
                    {"provider": settings.provider, "api_key": settings.api_key, "model": model}
                )
            ),
        )
        with self._coach_lock:
            # A new key may fix earlier errors (bad key, rate limit).
            self._coach_jobs = {k: v for k, v in self._coach_jobs.items() if v["state"] != "error"}
        return self.ai_status()

    def clear_ai(self) -> dict[str, Any]:
        self.store.set_meta(AI_SETTINGS_KEY, None)
        return self.ai_status()

    def check_ai(self) -> dict[str, Any]:
        """One small request with the current settings (runs in the request thread)."""
        client = self._coach_client(check=True)
        if client is None:
            return {"ok": False, "code": "no_key"}
        try:
            client.check()
        except CoachLLMError as error:
            return {"ok": False, "code": error.code}
        return {"ok": True}

    def ai_configured(self) -> bool:
        return self.llm is not None or self.ai_settings() is not None

    def _coach_client(self, *, check: bool = False) -> Any:
        if self.llm is not None:
            return self.llm
        settings = self.ai_settings()
        if settings is None:
            return None
        return CoachLLM(settings, timeout=30.0) if check else CoachLLM(settings)

    def ask_match(
        self, match_id: int, question: str, lang: str, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """A free question about one reviewed match, answered by the AI coach with the
        same fact check as the reviews (synchronous: the player waits for it)."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"ok": False, "code": "not_linked"}
        return self.asks.run(
            f"match:{primary}:{match_id}:{lang}",
            question,
            request_id,
            lambda: self._ask_match(primary, match_id, question, lang),
            wait_s=ASK_JOIN_WAIT_SECONDS,
        )

    def ask_status(self, request_id: str) -> dict[str, Any]:
        """A question's run by its id: unknown, running or done with its result."""
        return self.asks.status(request_id)

    def _ask_match(self, primary: int, match_id: int, question: str, lang: str) -> dict[str, Any]:
        if not self.ai_configured():
            return {"ok": False, "code": "off"}
        detail = self.match_detail(match_id, lang)
        facts = match_facts(detail) if detail else None
        if facts is None:
            return {"ok": False, "code": "no_review"}
        client = self.llm if self.llm is not None else self._coach_client_with(ASK_TIMEOUT_SECONDS)
        if client is None:
            return {"ok": False, "code": "off"}
        try:
            result = answer_question(
                client,
                facts,
                question,
                lang,
                known_items=self._known_items(),
                deadline=time.monotonic() + ASK_DEADLINE_SECONDS,
            )
        except CoachLLMError as error:
            if error.code not in {"empty_question", "unverified"}:
                record_error("coach-ai", f"question: {error.code}", with_trace=False)
            return {"ok": False, "code": error.code}
        except Exception as error:  # noqa: BLE001 - a bad answer must not become a 500
            record_error("coach-ai", error)
            return {"ok": False, "code": "bad_response"}
        entry = {
            "question": " ".join(str(question).split())[:QUESTION_LIMIT],
            "answer": result["review"]["answer"],
            "counter_evidence": result["review"].get("counter_evidence", []),
            "rate_evidence": result["review"].get("rate_evidence", []),
            "farm_evidence": result["review"].get("farm_evidence", []),
            "farm_slice_evidence": result["review"].get("farm_slice_evidence", []),
            "finding_evidence": result["review"].get("finding_evidence", []),
            "at": _now_iso(),
            "lang": lang,
        }
        key = f"{ASK_CACHE_KEY}:{primary}:{match_id}"
        with self._ask_history_lock:
            history = [entry, *self._questions(primary, match_id, facts=facts)][:ASK_HISTORY]
            self.store.cache_set(key, history)
        return {"ok": True, "answer": entry, "history": _shown_questions(history)}

    def _questions(
        self, account_id: int, match_id: int, *, facts: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        history = self.store.cache_get(f"{ASK_CACHE_KEY}:{account_id}:{match_id}") or []
        if facts is None:
            return []
        checker = FactChecker(json.dumps(facts, ensure_ascii=False), self._known_items())
        # Old Q&A has no verification version. Recheck the returned view without
        # deleting stored questions or calling the provider during reads.
        returned = []
        for entry in history:
            cleaned, _, _, _ = checker.scrub({"answer": entry.get("answer") or ""})
            if cleaned and cleaned.get("answer"):
                returned.append(
                    {
                        **entry,
                        "answer": cleaned["answer"],
                        "counter_evidence": list(checker.counter_bindings.evidence.values()),
                        "rate_evidence": list(checker.rate_bindings.evidence.values()),
                        "farm_evidence": list(checker.farm_bindings.evidence.values()),
                        "farm_slice_evidence": checker.farm_bindings.slice_evidence,
                        "finding_evidence": checker.finding_bindings.evidence,
                    }
                )
        return returned

    def _coach_client_with(self, timeout: float) -> Any:
        settings = self.ai_settings()
        return CoachLLM(settings, timeout=timeout) if settings is not None else None

    def _known_items(self) -> list[str]:
        constants = self.store.cache_get(ITEM_CONSTANTS_KEY) or {}
        return [str(info.get("name")) for info in (constants.get("items") or {}).values()]

    def _match_coach(
        self,
        account_id: int,
        match_id: int,
        detail: dict[str, Any],
        lang: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        facts = match_facts(detail)
        if facts is None:
            return {"state": "none"}
        waiting = detail.get("parse_status") in COACH_WAITS_FOR
        return self._coach_state(
            f"coach:match:{account_id}:{match_id}:{lang}",
            facts,
            lang,
            kind="match",
            force=force,
            hold="waiting" if waiting and not force else None,
        )

    def _career_coach(
        self,
        account_id: int,
        career: dict[str, Any],
        recent: list[dict[str, Any]],
        lang: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        facts = career_facts(career, recent)
        if facts is None or len(recent) < COACH_MIN_CAREER_MATCHES:
            # Off first: Progress is where a new player turns the AI coach on.
            if not self.ai_configured():
                return {"state": "off"}
            return {"state": "not_enough", "need": COACH_MIN_CAREER_MATCHES}
        return self._coach_state(
            f"coach:career:{account_id}:{lang}", facts, lang, kind="career", force=force
        )

    def _coach_state(
        self,
        key: str,
        facts: dict[str, Any],
        lang: str,
        *,
        kind: str,
        force: bool,
        hold: str | None = None,
    ) -> dict[str, Any]:
        """Cached review, or queue a new one: off / waiting / pending / ready / error."""
        digest = facts_hash(facts, lang)
        cached = self.store.cache_get(key)
        if kind == "match" and cached and cached.get("verification_version") != COACH_VERSION:
            # A policy upgrade must not display unverified legacy prose while
            # regenerating (including when AI is disabled). Keep the stored copy.
            cached = None
        shown = _coach_public(cached, stale=bool(cached) and cached.get("hash") != digest)
        if not self.ai_configured():
            return {"state": "off", **shown}
        if cached and cached.get("hash") == digest and not force:
            return {"state": "ready", **shown}
        with self._coach_lock:
            job = self._coach_jobs.get(key)
            if job and job["hash"] == digest:
                if job["state"] == "pending":
                    return {"state": "pending", **shown}
                if job["state"] == "error" and not force:
                    return {"state": "error", "error": job["error"], **shown}
            if hold:
                return {"state": "ready" if cached else hold, **shown}
            self._coach_jobs[key] = {"state": "pending", "hash": digest}
        self.ai_jobs.submit(
            f"{key}:{digest}", lambda: self._job_coach(key, facts, digest, lang, kind)
        )
        return {"state": "pending", **shown}

    def _job_coach(
        self, key: str, facts: dict[str, Any], digest: str, lang: str, kind: str, attempt: int = 0
    ) -> None:
        client = self._coach_client()
        if client is None:
            with self._coach_lock:
                self._coach_jobs.pop(key, None)
            return
        generate = review_match if kind == "match" else review_career
        try:
            result = generate(client, facts, lang, known_items=self._known_items())
        except CoachLLMError as error:
            if error.code == "busy" and attempt < len(COACH_BUSY_RETRY_SECONDS):
                # Stays "pending" for the UI; the next try goes on the same AI thread.
                self.ai_jobs.submit(
                    f"{key}:{digest}:retry{attempt + 1}",
                    lambda: self._job_coach(key, facts, digest, lang, kind, attempt + 1),
                    delay=COACH_BUSY_RETRY_SECONDS[attempt],
                )
                return
            record_error("coach-ai", f"{kind} review: {error.code}", with_trace=False)
            with self._coach_lock:
                self._coach_jobs[key] = {"state": "error", "hash": digest, "error": error.code}
            return
        except Exception as error:  # noqa: BLE001 - a bad answer must not kill the worker
            record_error("coach-ai", error)
            with self._coach_lock:
                self._coach_jobs[key] = {"state": "error", "hash": digest, "error": "bad_response"}
            return
        label = getattr(client, "label", {}) or {}
        self.store.cache_set(
            key,
            {
                "hash": digest,
                "verification_version": COACH_VERSION,
                "review": result["review"],
                "provider": label.get("provider"),
                "model": label.get("model"),
                "generated_at": _now_iso(),
            },
        )
        with self._coach_lock:
            self._coach_jobs.pop(key, None)

    # --- jobs -------------------------------------------------------------------

    def request_sync(self) -> dict[str, Any]:
        primary = self.store.primary_account_id()
        if primary is None or self.client is None:
            return dict(self._sync)
        with self._sync_lock:
            key = f"sync:{primary}"
            if key in self.jobs.pending():
                return dict(self._sync)
            previous = self._sync
            self._sync = {**previous, "state": "queued"}
            if not self.jobs.submit(key, lambda: self._job_sync(primary)):
                self._sync = previous
            return dict(self._sync)

    def fetch_match(self, match_id: int, *, request_parse: bool = True, delay: float = 0.0) -> None:
        primary = self.store.primary_account_id()
        if primary is None or self.client is None:
            return
        self.jobs.submit(
            f"match:{match_id}",
            lambda: self._job_fetch_match(
                primary, match_id, request_parse=request_parse, attempt=0
            ),
            delay=delay,
        )

    def _job_sync(self, account_id: int) -> None:
        client = self.client
        if client is None:
            return
        with self._sync_lock:
            self._sync = {**self._sync, "state": "running", "error": None, "error_code": None}
        try:
            self._ensure_hero_stats()
            try:
                profile = client.player(account_id)
                self.store.upsert_player(
                    account_id,
                    source="opendota",
                    persona_name=profile.get("persona_name"),
                    avatar_url=profile.get("avatar_url"),
                    steam_id64=profile.get("steam_id64"),
                    rank_tier=profile.get("rank_tier"),
                )
                key = f"rank_history:{account_id}"
                updated = rank_history.note(self.store.get_meta(key), profile.get("rank_tier"))
                if updated is not None:
                    self.store.set_meta(key, updated)
            except OpenDotaError as error:
                if error.code != "private":
                    raise
            # Bot games, practice, custom lobbies, Turbo and other modes with their
            # own rules would skew win rate, trends and the norms of the reviews.
            rows = client.recent_matches(account_id, limit=RECENT_MATCHES_LIMIT)
            recent = [row for row in rows if is_reviewable_match(row)]
            skipped = [row for row in rows if not is_reviewable_match(row)]
            for row in recent:
                match_id = row.pop("match_id", None)
                if match_id:
                    self.store.upsert_match(account_id, match_id, source="opendota", fields=row)
            self._drop_unreviewable(account_id)
            self.store.set_meta(
                f"{SKIPPED_MODES_META}:{account_id}",
                json.dumps(
                    {
                        "count": len(skipped),
                        "turbo": sum(r.get("game_mode") == TURBO_GAME_MODE for r in skipped),
                        "of": len(rows),
                    }
                ),
            )
            # Review the latest matches (one request each, well under the rate limit);
            # the newest unparsed ones are also sent to OpenDota's replay parser.
            now = time.time()
            for index, row in enumerate(
                self.store.list_matches(account_id, limit=REVIEW_RECENT_MATCHES)
            ):
                parse = (
                    index < PARSE_RECENT_MATCHES
                    and row.get("parse_status") in (None, "", "basic")
                    and now - float(row.get("start_time") or 0) < PARSE_MAX_AGE_SECONDS
                )
                if (
                    parse
                    or not row.get("has_analysis")
                    or ("opendota" not in row["sources"])
                    or self._trim_outdated(account_id, row)
                ):
                    mid = row["match_id"]
                    self.jobs.submit(
                        f"match:{mid}",
                        lambda mid=mid, parse=parse: self._job_fetch_match(
                            account_id, mid, request_parse=parse, attempt=0
                        ),
                    )
            # Reviews built above come newest first, before the older matches
            # tell which role the player plays each pool hero in (the draft's
            # better pick): rebuild them once all of these jobs have run.
            self.jobs.submit(f"rebuild:{account_id}", lambda: self._rebuild_recent(account_id))
            with self._sync_lock:
                self._sync = {
                    "state": "done",
                    "at": _now_iso(),
                    "error": None,
                    "error_code": None,
                    "fetched": len(recent),
                }
        except OpenDotaError as error:
            record_error("sync", f"OpenDota: {error.code}", with_trace=False)
            with self._sync_lock:
                self._sync = {
                    "state": "error",
                    "at": _now_iso(),
                    "error": str(error),
                    "error_code": error.code,
                }
        except Exception as error:  # noqa: BLE001 - never leave the UI stuck on "updating"
            record_error("sync", error)
            with self._sync_lock:
                self._sync = {
                    "state": "error",
                    "at": _now_iso(),
                    "error": str(error),
                    "error_code": "internal",
                }

    def _job_fetch_match(
        self, account_id: int, match_id: int, *, request_parse: bool, attempt: int
    ) -> None:
        client = self.client
        if client is None:
            return
        try:
            match = client.match(match_id)
        except OpenDotaError as error:
            if (
                error.code in {"not_found", "offline", "rate_limited"}
                and attempt < PARSE_POLL_ATTEMPTS
                and request_parse
            ):
                self._retry(account_id, match_id, request_parse, attempt)
            else:
                self.store.upsert_match(
                    account_id,
                    match_id,
                    source=None,
                    parse_status=f"error:{error.code}",
                )
            return
        trimmed = trim_match(match, account_id)
        if not trimmed.get("found_player"):
            self.store.upsert_match(account_id, match_id, source="opendota", parse_status="private")
            return
        if not is_reviewable_match(trimmed):
            # A live match recorded from GSI that turns out to be Turbo, a bot
            # game or another mode with its own rules: not part of the history.
            self.store.delete_matches(account_id, [match_id])
            last = (self.store.get_meta(f"last_review:{account_id}") or "").split("|")[0]
            if last == str(match_id):
                # The "review ready" banner must not open a deleted match.
                self.store.set_meta(f"last_review:{account_id}", None)
            return
        self._store_fetched(
            account_id, match_id, trimmed, request_parse=request_parse, attempt=attempt
        )

    def _store_fetched(
        self,
        account_id: int,
        match_id: int,
        trimmed: dict[str, Any],
        *,
        request_parse: bool,
        attempt: int,
    ) -> None:
        """A fetched match of the player: stored, reviewed, its replay asked for."""
        client = self.client
        if client is None:
            return
        parsed = bool(trimmed.get("parsed"))
        status = "parsed" if parsed else "basic"
        if not parsed and request_parse:
            if attempt == 0:
                with contextlib.suppress(OpenDotaError):
                    client.request_parse(match_id)
            status = "parsing" if attempt < PARSE_POLL_ATTEMPTS else "not_parsed"
        self.store.upsert_match(
            account_id,
            match_id,
            source="opendota",
            fields=summary_from_match(trimmed),
            opendota=trimmed,
            parse_status=status,
        )
        me = my_player(trimmed) or {}
        self._ensure_hero_meta(me.get("hero_id"))
        self._ensure_matchups([me.get("hero_id"), *self._pool(account_id)])
        self._rebuild_analysis(account_id, match_id)
        if status == "parsing":
            self._retry(account_id, match_id, request_parse, attempt)

    # --- a match by its number (older than the synced history) -----------------

    def add_match(self, match_id: int) -> dict[str, Any]:
        """Fetch a match the table does not hold (older than the last 50) and
        review it, on the job thread. Never stores a match without the player."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"state": "unlinked"}
        if self.store.get_match(primary, match_id) is not None:
            return {"state": "ready"}
        if self.client is None:
            return {"state": "offline"}
        if self._adding.get(match_id) != "pending":
            self._adding[match_id] = "pending"
            self.jobs.submit(f"add:{match_id}", lambda: self._job_add_match(primary, match_id))
        return {"state": "pending"}

    def set_note(self, match_id: int, text: Any) -> dict[str, Any]:
        """«Нотатка»: the player's own words on a match (lag, a new build, played
        with a friend…), shown in the table and the review. Plain text, one line,
        NOTE_MAX characters; empty removes it. Never sent anywhere (not to the AI
        coach, not in a shared review); a history backup carries it."""
        primary = self.store.primary_account_id()
        if primary is None:
            return {"status": "error", "code": "unlinked"}
        note = " ".join(str(text or "").split())[:NOTE_MAX]
        if not self.store.set_note(primary, int(match_id), note):
            return {"status": "error", "code": "match_not_found"}
        return {"status": "ok", "note": note or None}

    def add_status(self, match_id: int) -> dict[str, Any]:
        primary = self.store.primary_account_id()
        if primary is None:
            return {"state": "unlinked"}
        if self.store.get_match(primary, match_id) is not None:
            return {"state": "ready"}
        return {"state": self._adding.get(match_id, "none")}

    def _job_add_match(self, account_id: int, match_id: int) -> None:
        client = self.client
        if client is None:
            self._adding[match_id] = "offline"
            return
        try:
            match = client.match(match_id)
        except OpenDotaError as error:
            self._adding[match_id] = error.code or "error"
            return
        trimmed = trim_match(match, account_id)
        if not trimmed.get("found_player"):
            self._adding[match_id] = "not_player"
            return
        if not is_reviewable_match(trimmed):
            self._adding[match_id] = "mode"
            return
        self._store_fetched(account_id, match_id, trimmed, request_parse=True, attempt=0)
        self._adding[match_id] = "ready"

    def _rebuild_recent(self, account_id: int) -> None:
        for row in self.store.list_matches(account_id, limit=REVIEW_RECENT_MATCHES):
            if row.get("has_analysis"):
                self._rebuild_analysis(account_id, row["match_id"])

    def _drop_unreviewable(self, account_id: int) -> None:
        """Matches stored before a mode was excluded (older versions kept Turbo)."""
        drop = [
            row["match_id"]
            for row in self.store.mode_rows(account_id)
            if not is_reviewable_match(row)
        ]
        self.store.delete_matches(account_id, drop)

    def skipped_modes(self, account_id: int) -> dict[str, int] | None:
        raw = self.store.get_meta(f"{SKIPPED_MODES_META}:{account_id}")
        if not raw:
            return None
        with contextlib.suppress(ValueError, TypeError):
            data = json.loads(raw)
            if isinstance(data, dict) and int(data.get("count") or 0) > 0:
                return {key: int(data.get(key) or 0) for key in ("count", "turbo", "of")}
        return None

    def _retry(self, account_id: int, match_id: int, request_parse: bool, attempt: int) -> None:
        self.jobs.submit(
            f"match:{match_id}",
            lambda: self._job_fetch_match(
                account_id, match_id, request_parse=request_parse, attempt=attempt + 1
            ),
            delay=PARSE_POLL_SECONDS,
        )

    # --- reviews ---------------------------------------------------------------

    def _on_match_finished(self, timeline: dict[str, Any]) -> None:
        account_id = timeline.get("account_id") or self.store.primary_account_id()
        match_id = timeline.get("match_id")
        if not account_id or not match_id:
            raise ValueError("Finished match needs an account and match id before acknowledgement")
        facts = facts_from_timeline(timeline)
        fields = {
            "hero_id": facts.get("hero_id"),
            "hero": facts.get("hero"),
            "duration": facts.get("duration"),
            "is_radiant": facts.get("is_radiant"),
            "win": facts.get("win"),
            "kills": facts.get("kills"),
            "deaths": facts.get("deaths"),
            "assists": facts.get("assists"),
            "gpm": facts.get("gpm"),
            "xpm": facts.get("xpm"),
            "last_hits": facts.get("last_hits"),
            "denies": facts.get("denies"),
            "start_time": _start_time(timeline),
        }
        existing = self.store.get_match(account_id, match_id)
        if existing is None or existing.get("timeline") != timeline:
            self.store.upsert_match(
                account_id,
                match_id,
                source="gsi",
                fields=fields,
                timeline=timeline,
                parse_status="waiting_opendota" if self.client is not None else "gsi_only",
            )
        analysis = self._rebuild_analysis(account_id, match_id)
        # Per account: a match of another (detected, not linked) account must not
        # replace the linked player's "review ready" banner.
        focus = self._focus(account_id)
        focus_met = (
            match_result(analysis, focus)
            if focus is not None and played_after({"start_time": fields["start_time"]}, focus)
            else None
        )
        self.store.set_meta(
            f"last_review:{account_id}",
            f"{match_id}|{_now_iso()}|{(analysis or {}).get('headline', {}).get('score') or ''}"
            f"|{'' if focus_met is None else int(focus_met)}",
        )
        if account_id == self.store.primary_account_id():
            self.fetch_match(match_id, request_parse=True, delay=FIRST_FETCH_DELAY_SECONDS)

    def _rebuild_analysis(self, account_id: int, match_id: int) -> dict[str, Any] | None:
        record = self.store.get_match(account_id, match_id)
        if record is None:
            return None
        od = facts_from_opendota(record["opendota"]) if record.get("opendota") else None
        gsi = facts_from_timeline(record["timeline"]) if record.get("timeline") else None
        facts = merge_facts(od, gsi)
        if facts is None:
            return None
        analysis = analyze_match(
            facts,
            meta=self._hero_meta(facts.get("hero_id")),
            opendota=record.get("opendota"),
            draft=self._draft_meta(account_id, facts.get("hero_id")),
        )
        # «На чому ґрунтується розбір?»: rules, patch, data and why it was (re)built.
        analysis["basis"] = review_basis.stamp(
            rules=ANALYSIS_VERSION,
            trim=TRIM_VERSION,
            opendota=record.get("opendota"),
            sources=record.get("sources"),
            parsed=bool(facts.get("parsed")),
            has_timeline=bool(record.get("timeline")),
            previous=record.get("analysis") if isinstance(record.get("analysis"), dict) else None,
        )
        lh_t = facts.get("lh_t") or []
        items = self._inventory_keys(facts)
        self.store.upsert_match(
            account_id,
            match_id,
            source=record["sources"][0] if record["sources"] else "analysis",
            fields={
                "score": analysis["headline"]["score"],
                "lh_10": lh_t[10] if len(lh_t) > 10 else None,
                "items": None if items is None else json.dumps(items),
            },
            analysis=analysis,
        )
        return analysis

    def _inventory_keys(self, facts: Mapping[str, Any]) -> list[str] | None:
        """The final inventory as item keys for the match table's icons: GSI
        names directly, OpenDota ids through the cached item constants. None
        when it cannot be read yet (ids without constants), [] when empty."""
        raw = facts.get("inventory") or []
        if not raw:
            return [] if facts.get("sources") else None
        by_id = (self.store.cache_get(ITEM_CONSTANTS_KEY) or {}).get("by_id") or {}
        keys = []
        for value in raw:
            if isinstance(value, bool):
                continue
            if isinstance(value, int) or str(value).isdigit():
                key = by_id.get(str(value))
                if key is None:
                    return None  # constants missing or stale: try again later
            else:
                key = item_key(value)
            if key:
                keys.append(key)
        return keys[:6]

    def _backfill_items(self, account_id: int, rows: list[dict[str, Any]]) -> None:
        """Reviews stored before 0.50 have no items column: read it from their
        stored match, a few rows per call (the table asks every 15 s)."""
        missing = [row for row in rows if row.get("has_analysis") and row.get("items") is None]
        for row in missing[:BACKFILL_ITEMS_PER_CALL]:
            record = self.store.get_match(account_id, row["match_id"])
            if record is not None:
                row["items"] = self._record_items(account_id, record)

    def _record_items(self, account_id: int, record: dict[str, Any]) -> list[str] | None:
        """The final items of a stored match, kept in its items column once read."""
        od = facts_from_opendota(record["opendota"]) if record.get("opendota") else None
        gsi = facts_from_timeline(record["timeline"]) if record.get("timeline") else None
        facts = merge_facts(od, gsi)
        items = self._inventory_keys(facts) if facts else None
        if items is not None:
            self.store.upsert_match(
                account_id, record["match_id"], source=None, fields={"items": json.dumps(items)}
            )
        return items

    # --- OpenDota meta data (cached; fetched on the job thread only) -----------

    def _hero_meta(self, hero_id: Any) -> dict[str, Any] | None:
        """Cached build data for a hero (stale is fine: reviews must work offline)."""
        constants = self.store.cache_get(ITEM_CONSTANTS_KEY)
        if not constants or not hero_id:
            return None
        return {
            "constants": constants,
            "popularity": self.store.cache_get(f"{POPULARITY_KEY}:{int(hero_id)}"),
            "timings": self.store.cache_get(f"{TIMINGS_KEY}:{int(hero_id)}"),
            "skills": self.store.cache_get(f"{SKILLS_KEY}:{int(hero_id)}"),
        }

    def _refresh(
        self, key: str, ttl: float, fetch: Callable[[], Any], *, force: bool = False
    ) -> None:
        if self.client is None or (
            not force and self.store.cache_get(key, max_age=ttl) is not None
        ):
            return
        with contextlib.suppress(OpenDotaError):
            self.store.cache_set(key, fetch())

    def _trim_outdated(self, account_id: int, row: dict[str, Any]) -> bool:
        """A match stored before trim_match kept what the review now uses (team
        fight death positions, the skill order): fetched again, one request."""
        return _trim_is_old(self.store.get_match(account_id, row["match_id"]))

    def _pool(self, account_id: int) -> list[int]:
        return pool_heroes(self.store.list_matches(account_id, limit=RECENT_MATCHES_LIMIT))

    def _draft_meta(self, account_id: int, hero_id: Any) -> dict[str, Any] | None:
        """Cached matchups of the played hero and the player's pool (stale is fine)."""
        heroes = [int(hero_id)] if hero_id else []
        heroes += [h for h in self._pool(account_id) if h not in heroes]
        matchups = {}
        for hero in heroes:
            cached = self.store.cache_get(f"{MATCHUPS_KEY}:{hero}")
            if cached:
                matchups[str(hero)] = cached
        # The position (else review role) the player plays each pool hero in, and
        # OpenDota's role tags for the rest: the better pick keeps the role.
        played: dict[str, dict[str, int]] = {}
        for row in self.store.matches_for_career(account_id, limit=RECENT_MATCHES_LIMIT):
            analysis = row.get("analysis") or {}
            role = analysis.get("position") or analysis.get("role")
            if row.get("hero_id") and role:
                counts = played.setdefault(str(int(row["hero_id"])), {})
                counts[role] = counts.get(role, 0) + 1
        tags = {
            str(row["hero_id"]): row.get("roles") or []
            for row in self.store.cache_get(HERO_STATS_KEY) or []
            if isinstance(row, dict) and row.get("hero_id")
        }
        return {
            "matchups": matchups,
            "pool": heroes[1:],
            "pool_roles": played,
            "hero_roles": tags,
            "constants": self.store.cache_get(ITEM_CONSTANTS_KEY),
        }

    def _ensure_matchups(self, hero_ids: list[Any]) -> None:
        client = self.client
        if client is None:
            return
        for hero_id in dict.fromkeys(int(h) for h in hero_ids if h):
            self._refresh(
                f"{MATCHUPS_KEY}:{hero_id}",
                META_TTL_SECONDS,
                lambda hero=hero_id: client.hero_matchups(hero),
            )

    def _ensure_hero_meta(self, hero_id: Any) -> None:
        client = self.client
        if client is None or not hero_id:
            return
        hero = int(hero_id)
        constants = self.store.cache_get(ITEM_CONSTANTS_KEY)
        self._refresh(
            ITEM_CONSTANTS_KEY,
            META_TTL_SECONDS,
            client.item_constants,
            # Cached before the components were kept: the live next-item advice needs them.
            force=constants is not None and not has_components(constants),
        )
        self._refresh(
            f"{POPULARITY_KEY}:{hero}", META_TTL_SECONDS, lambda: client.item_popularity(hero)
        )
        self._refresh(f"{TIMINGS_KEY}:{hero}", META_TTL_SECONDS, lambda: client.item_timings(hero))
        self._refresh(
            f"{SKILLS_KEY}:{hero}", META_TTL_SECONDS, lambda: client.pro_skill_orders(hero)
        )

    def _ensure_hero_stats(self) -> None:
        client = self.client
        if client is not None:
            self._refresh(HERO_STATS_KEY, HERO_STATS_TTL_SECONDS, client.hero_stats)

    def rebuild_all(self) -> int:
        """Re-run analyses (after the rules changed)."""
        primary = self.store.primary_account_id()
        if primary is None:
            return 0
        count = 0
        for row in self.store.list_matches(primary, limit=500):
            if self._rebuild_analysis(primary, row["match_id"]) is not None:
                count += 1
        return count

    def post_game_card(self, match_id: int | None, lang: str) -> dict[str, Any] | None:
        """The overlay's summary while Dota shows the score screen of `match_id`:
        the result, the review score and the top tip, for POST_GAME_CARD_SECONDS
        after the review was written (the live-recorded match, reviewed at once)."""
        primary = self.store.primary_account_id()
        last = self._last_review()
        if primary is None or last is None or match_id is None or last["match_id"] != match_id:
            return None
        try:
            written = datetime.fromisoformat(last["at"])
        except (TypeError, ValueError):
            return None
        if (datetime.now(UTC) - written).total_seconds() > POST_GAME_CARD_SECONDS:
            return None
        key = ("post_game", primary, match_id, lang)
        cached = self._plans.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < GAME_PLAN_CACHE_SECONDS:
            return cached[1]
        record = self.store.get_match(primary, match_id)
        analysis = (record or {}).get("analysis")
        card = post_game_card(analysis, lang, focus_met=last.get("focus_met")) if analysis else None
        self._plans[key] = (now, card)
        return card

    def _last_review(self) -> dict[str, Any] | None:
        primary = self.store.primary_account_id()
        if primary is None:
            return None
        raw = self.store.get_meta(f"last_review:{primary}")
        if not raw:
            return None
        match_id, at, score, focus_met = (raw.split("|") + ["", "", "", ""])[:4]
        return {
            "match_id": int(match_id),
            "at": at,
            "score": int(score) if score else None,
            # Did the match avoid the player's focus problem (None: no focus / can't tell).
            "focus_met": bool(int(focus_met)) if focus_met else None,
        }


# The longest note on a match (characters).
NOTE_MAX = 200

_SUMMARY_KEYS = (
    "note",
    "start_time",
    "duration",
    "hero_id",
    "hero",
    "is_radiant",
    "win",
    "kills",
    "deaths",
    "assists",
    "gpm",
    "xpm",
    "last_hits",
    "denies",
    "lh_10",
    "net_worth",
    "hero_damage",
    "lane_role",
    "game_mode",
    "lobby_type",
    "parsed",
    "score",
    "items",
)


def _public_player(player: dict[str, Any] | None, account_id: int | None) -> dict[str, Any] | None:
    if account_id is None:
        return None
    player = player or {}
    return {
        "account_id": account_id,
        "steam_id64": player.get("steam_id64") or str(steam64_from_account_id(account_id)),
        "persona_name": player.get("persona_name"),
        "avatar_url": player.get("avatar_url"),
        "rank_tier": player.get("rank_tier"),
    }


def _shown_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [q for q in questions if q.get("lang") != RETIRED_COACH_LANG]


def _coach_public(cached: dict[str, Any] | None, *, stale: bool) -> dict[str, Any]:
    if not cached or not cached.get("review"):
        return {}
    provider = cached.get("provider")
    return {
        "review": cached["review"],
        "provider_label": PROVIDERS[provider]["label"] if provider in PROVIDERS else provider,
        "model": cached.get("model"),
        "generated_at": cached.get("generated_at"),
        "stale": stale,
    }


def _scoreboard(
    trimmed: dict[str, Any] | None, by_id: dict[str, str] | None = None
) -> list[dict[str, Any]] | None:
    """Both teams of an OpenDota match; `by_id` (the cached item constants)
    names the items of every player's inventory (ids without it are left out)."""
    if not trimmed:
        return None
    rows = []
    for player in trimmed.get("players") or []:
        items = []
        for slot in range(6):
            raw = player.get(f"item_{slot}")
            if not raw or isinstance(raw, bool):
                continue
            key = (by_id or {}).get(str(raw)) if str(raw).isdigit() else item_key(raw)
            if key:
                items.append(key)
        rows.append(
            {
                "me": bool(player.get("me")),
                "is_radiant": bool(player.get("isRadiant", True)),
                "hero": player.get("hero"),
                "hero_id": player.get("hero_id"),
                "name": player.get("personaname"),
                "kills": player.get("kills"),
                "deaths": player.get("deaths"),
                "assists": player.get("assists"),
                "net_worth": player.get("net_worth"),
                "gpm": player.get("gold_per_min"),
                "xpm": player.get("xp_per_min"),
                "last_hits": player.get("last_hits"),
                "hero_damage": player.get("hero_damage"),
                "items": items,
            }
        )
    return rows


def _role_prior(history: list[dict[str, Any]], tags: list[str], hero: str) -> dict[str, Any] | None:
    positions = Counter(
        (row.get("analysis") or {}).get("position")
        for row in history
        if (row.get("analysis") or {}).get("position")
    )
    if positions:
        position, games = positions.most_common(1)[0]
        if games >= 2:
            return {"role": position, "source": "history"}
    if "Support" in tags and "Carry" not in tags:
        return {"role": "support", "source": "hero"}
    if is_supported_hero(hero):
        # A profiled core: its usual position (carry, mid or offlane).
        return {"role": get_hero_position(hero) or "carry", "source": "hero"}
    if "Carry" in tags:
        return {"role": "carry", "source": "hero"}
    return None


def _start_time(timeline: dict[str, Any]) -> int | None:
    started = timeline.get("started_at")
    try:
        return int(datetime.fromisoformat(str(started)).timestamp()) if started else None
    except ValueError:
        return None


def _trim_is_old(record: dict[str, Any] | None) -> bool:
    """The stored OpenDota match was trimmed by an older trim_match."""
    stored = (record or {}).get("opendota")
    if not isinstance(stored, dict) or not stored:
        return False
    return int(stored.get("trim_version") or 1) < TRIM_VERSION
