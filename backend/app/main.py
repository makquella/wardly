"""
main.py — FastAPI application entry point for Wardly (formerly Dota AI Coach) (MVP-1).
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from app import operations_health, stratz_builds
from app.advice_i18n import (
    advice_messages,
    localize_advice_items,
    localize_overlay_response,
    normalize_lang,
)
from app.advice_scheduler import ADVICE_SCHEDULER, ScheduledAdvice
from app.advice_why import why
from app.coach_summary import COACH_SESSION_HISTORY
from app.config import (
    ADVICE_ROLE,
    BACKEND_PORT,
    GSI_STALE_SECONDS,
    IS_FROZEN,
    LIVE_CONSERVATIVE_MODE,
    LLM_PROVIDER,
    MAP_HINTS,
    MATCH_RECORDS_ENABLED,
    OPENDOTA_ENABLED,
    PLAYER_DATA_DIR,
    RESOURCE_ROOT,
    USE_LLM,
    WRITABLE_DIR,
)
from app.decision_points import detect_decision_point
from app.demo_overlay_cache import DemoOverlayCache, DemoToken
from app.diagnostics import recent_errors, record_error, runtime_info
from app.game_plan import SHOW_FROM_CLOCK as GAME_PLAN_SHOW_FROM_CLOCK
from app.game_plan import SHOW_UNTIL_CLOCK as GAME_PLAN_SHOW_UNTIL_CLOCK
from app.gsi_census import CENSUS_FILE, GSI_CENSUS, load_previous
from app.gsi_state import (
    PRE_SPAWN_STATES,
    get_current_state,
    get_gsi_debug_fields,
    get_gsi_debug_latest,
    get_gsi_status_snapshot,
    hero_from_gsi,
    post_game_match_id,
    reset_latest_gsi,
    update_latest_gsi,
)
from app.lane_duel import lane_record_for
from app.live_hints import GoldHintInputs, LiveHintInputs
from app.live_operation import live_operation
from app.live_path_metrics import LIVE_PATH_METRICS
from app.live_role import SETTINGS as ROLE_SETTINGS
from app.live_role import lane_of, role_setting, set_role_setting
from app.live_session_recorder import LIVE_SESSION_RECORDER
from app.live_tools import disabled_copy
from app.llm_provider import generate_llm_recommendation, is_llm_provider_enabled
from app.local_api_auth import LOCAL_API_AUTH
from app.local_api_security import LocalApiSecurity, local_origins
from app.logger import log_recommendation, prune_logs
from app.map_hints import DRAFT_UNTIL, timers
from app.match_memory import MATCH_MEMORY
from app.match_records import KEEP_DAYS, MATCH_RECORDS
from app.next_item import owned_items
from app.player_api import PLAYER_SERVICE, refresh_quieter_advice
from app.player_api import router as player_router
from app.rag import KNOWLEDGE_BASE, retrieve_context
from app.recommender import generate_recommendation
from app.scheduler.frequency import FREQUENCIES
from app.schemas import GameSituationRequest, RecommendationResponse, hero_coverage


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    prune_logs()
    await run_in_threadpool(KNOWLEDGE_BASE.paragraphs)
    try:
        await run_in_threadpool(refresh_quieter_advice)
    except Exception as error:  # noqa: BLE001 - feedback never blocks startup
        record_error("advice-feedback", error)
    yield
    # Keeps an in-progress match timeline across a restart of the app.
    PLAYER_SERVICE.shutdown()


class LocalApiApp(FastAPI):
    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema is None:
            schema = get_openapi(
                title=self.title,
                description=self.description,
                version=self.version,
                routes=self.routes,
            )
            schema.setdefault("components", {}).setdefault("securitySchemes", {})[
                "LocalControl"
            ] = {
                "type": "http",
                "scheme": "bearer",
            }
            for path, operations in schema["paths"].items():
                for method, operation in operations.items():
                    if method in {"get", "post", "put", "patch", "delete", "head", "options"}:
                        operation["security"] = (
                            [] if path in {"/", "/health"} else [{"LocalControl": []}]
                        )
            self.openapi_schema = schema
        return self.openapi_schema


app = LocalApiApp(
    lifespan=_lifespan,
    title="Wardly",
    description="MVP-1: rule-based carry coach with local knowledge-base RAG.",
    version="0.57.0",
)
app.include_router(player_router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=local_origins(BACKEND_PORT),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(LocalApiSecurity, auth=LOCAL_API_AUTH, port=BACKEND_PORT)

# Legacy browser pages (a scenario form and a plain overlay) kept for developers
# only: served at /debug/ from a source checkout, never from the frozen app and
# never the rest of frontend/ (the launcher's sources and node_modules).
DEBUG_PAGES_DIR = RESOURCE_ROOT / "frontend" / "debug"


def debug_pages_dir(frozen: bool = IS_FROZEN, directory: Path = DEBUG_PAGES_DIR) -> Path | None:
    """The developer pages to serve at /debug/, or None in the installed app."""
    return None if frozen or not directory.is_dir() else directory


_DEMO_CACHE_SECONDS = 8
_DEMO_OVERLAY_CACHE = DemoOverlayCache(ttl_seconds=_DEMO_CACHE_SECONDS)

_DEBUG_PAGES = debug_pages_dir()
if _DEBUG_PAGES is not None:
    app.mount("/debug", StaticFiles(directory=_DEBUG_PAGES, html=True), name="debug-pages")


@app.get("/", summary="Health check")
def root():
    """Simple health-check endpoint."""
    return {"status": "ok", "service": "Wardly", "version": "0.57.0"}


@app.get("/health", summary="Health check")
def health():
    """Compact health-check endpoint for local launchers and demos."""
    return {"status": "ok"}


def _recommendation_log_filename(
    request: GameSituationRequest,
    rag_context: list[str],
    response: RecommendationResponse,
    decision_point: str | None = None,
    provider: str = "fallback",
    model: str | None = None,
    llm_error: str | None = None,
    fallback_reason: str | None = None,
) -> str | None:
    """A failed diagnostic write must not discard an already computed advice."""
    try:
        return log_recommendation(
            request=request,
            rag_context=rag_context,
            response=response,
            decision_point=decision_point,
            provider=provider,
            model=model,
            llm_error=llm_error,
            fallback_reason=fallback_reason,
        ).name
    except OSError as error:
        record_error("recommendation-log", error)
        return None


def _build_recommendation(
    request: GameSituationRequest,
    decision_point: str | None = None,
) -> tuple[RecommendationResponse, str | None]:
    decision_point = decision_point or detect_decision_point(request.model_dump())

    rag_context = _retrieve_rag_context(request)

    if decision_point not in {"NO_ADVICE", "SOFT_STATUS"} and USE_LLM and is_llm_provider_enabled():
        llm_result = generate_llm_recommendation(request, decision_point, rag_context)
        if llm_result.recommendation is not None:
            log_filename = _recommendation_log_filename(
                request=request,
                rag_context=rag_context,
                response=llm_result.recommendation,
                decision_point=decision_point,
                provider=llm_result.provider,
                model=llm_result.model,
            )
            return llm_result.recommendation, log_filename

        fallback = generate_recommendation(request, rag_context)
        log_filename = _recommendation_log_filename(
            request=request,
            rag_context=rag_context,
            response=fallback,
            decision_point=decision_point,
            provider=llm_result.provider,
            model=llm_result.model,
            llm_error=llm_result.error,
            fallback_reason="llm_unavailable_or_invalid",
        )
        return fallback, log_filename

    recommendation = generate_recommendation(request, rag_context)
    log_filename = _recommendation_log_filename(
        request=request,
        rag_context=rag_context,
        response=recommendation,
        decision_point=decision_point,
        provider="fallback",
        fallback_reason=(
            "llm_disabled"
            if decision_point not in {"NO_ADVICE", "SOFT_STATUS"}
            and (not USE_LLM or not is_llm_provider_enabled())
            else None
        ),
    )
    return recommendation, log_filename


def _retrieve_rag_context(request: GameSituationRequest) -> list[str]:
    query = (
        f"{request.hero} {request.role} {request.game_state} "
        f"{request.team_status} {request.event_context} {request.item_timing_category or ''} "
        f"{request.selected_team} {request.teamfight_result} {request.objective_context} "
        f"{request.objective_type or ''} {request.objective_team or ''} "
        f"mana {request.extra_context.get('mana_percent', '')} "
        f"gpm {request.extra_context.get('gpm', '')} "
        f"last_hits {request.extra_context.get('last_hits', '')} "
        f"status {' '.join(request.extra_context.get('status_effects', [])) if isinstance(request.extra_context.get('status_effects'), list) else ''} "
        f"hero_safety {request.extra_context.get('hero_risk_level', '')} "
        f"{request.extra_context.get('hero_safety_reason', '')} "
        f"{request.extra_context.get('recommended_constraint', '')} "
        f"death_context {request.extra_context.get('last_death_context', '')} "
        f"death_pattern {request.extra_context.get('recent_death_pattern', '')} "
        f"minute {request.minute} level {request.level} "
        f"hp {request.hp_percent} gold {request.gold} " + " ".join(request.items)
    )

    rag_context = retrieve_context(
        query,
        hero=request.hero,
        game_state=request.game_state,
        owned_items=request.items,
    )
    return rag_context


@app.post("/recommend", response_model=RecommendationResponse, summary="Get a carry recommendation")
def recommend(request: GameSituationRequest):
    """
    Accept a structured game-situation description and return a carry recommendation.

    Steps:
    1. Build a query string from the request for RAG retrieval.
    2. Retrieve relevant knowledge-base paragraphs.
    3. Generate a rule-based fallback recommendation.
    4. Log the full request/context/response to disk.
    5. Return the recommendation.
    """
    recommendation, log_filename = _build_recommendation(request)
    # Attach the log filename as a response header for easy debugging
    response = JSONResponse(content=recommendation.model_dump())
    if log_filename is not None:
        response.headers["X-Log-File"] = log_filename
    return response


@app.post("/gsi", summary="Receive Dota 2 Game State Integration data")
async def receive_gsi(request: Request):
    """Accept raw Dota 2 GSI JSON and keep the latest normalized state in memory."""
    payload = request.scope["wardly.gsi_payload"]
    # Role history/cache can read SQLite. Prepare it before the GSI writer and
    # core memory owners; the callback uses the lane read after observation.
    return await run_in_threadpool(_process_gsi, payload)


def _process_gsi(payload: dict[str, Any]) -> dict[str, Any]:
    with LIVE_PATH_METRICS.measure("gsi.total"):
        return _receive_gsi_payload(payload)


def _receive_gsi_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # This entire path (including census, SQLite and recording) runs off ASGI.
    with LIVE_PATH_METRICS.measure("gsi.prepare"):
        prior = _prepare_gsi_prior(payload)
    with LIVE_PATH_METRICS.measure("gsi.policy"), live_operation():
        result = update_latest_gsi(
            payload, enrich=lambda state: _observe_live_gsi(state, prior=prior)
        )
    with LIVE_PATH_METRICS.measure("gsi.persistence"):
        GSI_CENSUS.observe(payload)
        GSI_CENSUS.save_due(PLAYER_SERVICE.data_dir / CENSUS_FILE)
        MATCH_RECORDS.record_gsi(payload)
        # Whole-match recording + Steam account detection (never breaks the live path).
        try:
            PLAYER_SERVICE.observe_gsi(payload)
        except Exception as error:  # noqa: BLE001
            print(f"[player] GSI observe failed: {error}")
            record_error("gsi-player", error)
        state = result.get("state")
        if isinstance(state, dict):
            LIVE_SESSION_RECORDER.record_gsi(payload, state)
    return result


def _prepare_gsi_prior(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Cold timer/profile/role lookups stay off the ASGI loop and state owners."""
    timers()
    hero = hero_from_gsi(payload)
    return PLAYER_SERVICE.role_prior(hero) if hero_coverage(hero) == "full" else None


def _observe_live_gsi(state: dict[str, Any], *, prior: dict[str, Any] | None) -> None:
    """In-memory enrichment completes before the packet/state is published."""
    MATCH_MEMORY.observe_state(state)
    coverage = hero_coverage(str(state.get("hero") or ""))
    if coverage == "full" and _role_is_support(MATCH_MEMORY.role_snapshot(prior)):
        coverage = "support"
    if coverage:
        decision_point = _covered_decision_point(detect_decision_point(state), coverage)
        MATCH_MEMORY.note_advice(decision_point)
        ADVICE_SCHEDULER.observe_state(state, decision_point)
    else:
        ADVICE_SCHEDULER.observe_state(state, "NO_ADVICE")


@app.get("/state/current", summary="Get latest normalized GSI state")
def current_state():
    return get_current_state()


@app.post("/session/reset", summary="Reset in-memory match session")
def reset_session():
    def reset_context() -> None:
        MATCH_MEMORY.reset()
        ADVICE_SCHEDULER.reset()
        COACH_SESSION_HISTORY.reset()

    with live_operation(), _DEMO_OVERLAY_CACHE.resetting():
        reset_latest_gsi(reset_context)
    return {
        "status": "ok",
        "detail": "Live GSI, match memory, overlay scheduler, and coach summary reset.",
    }


@app.get("/session/memory", summary="Inspect safe match memory summary")
def session_memory():
    return MATCH_MEMORY.summary()


@app.get("/gsi/debug/latest", summary="Inspect latest raw and normalized GSI payload")
def gsi_debug_latest():
    return get_gsi_debug_latest()


@app.get("/gsi/census", summary="Which GSI fields the game sent (names and counts only)")
def gsi_census():
    return _census_for_report()


@app.get("/gsi/debug/fields", summary="Inspect available GSI payload fields")
def gsi_debug_fields():
    return get_gsi_debug_fields()


@app.get("/gsi/status", summary="Get live GSI readiness status")
def gsi_status():
    # Polled every second by the launcher: a cheap place to close a match whose GSI stopped.
    PLAYER_SERVICE.check_stale()
    return _gsi_status_response()


@app.post("/session-recording/start", summary="Start live GSI session recording")
def start_session_recording():
    return LIVE_SESSION_RECORDER.start()


@app.post("/session-recording/stop", summary="Stop live GSI session recording")
def stop_session_recording():
    return LIVE_SESSION_RECORDER.stop()


@app.get("/session-recording/status", summary="Inspect live GSI session recording status")
def session_recording_status():
    return LIVE_SESSION_RECORDER.status()


@app.get("/overlay/recommendation", summary="Get overlay-friendly recommendation")
def overlay_recommendation(lang: str = "en"):
    """`lang=uk` returns the visible text in Ukrainian (see app/advice_i18n.py)."""
    lang = normalize_lang(lang)
    response = localize_overlay_response(_overlay_recommendation_payload(), lang)
    plan = _game_plan_for_overlay(response, lang)
    if plan is not None:
        response = {**response, "game_plan": plan}
    post_game = _post_game_for_overlay(response, lang)
    if post_game is not None:
        response = {**response, "post_game": post_game}
    death_screen = _death_screen_for_overlay(response, lang)
    if death_screen is not None:
        response = {**response, "death_screen": death_screen}
    try:
        response = {**response, **_live_role_and_hint(response, lang)}
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("map-hint", error)
    return response


def _advisor_coverage(state: Mapping[str, object]) -> str | None:
    """hero_coverage of the live hero, with a core played as a support advised as
    a support: farm and item advice assume a core (_plays_support)."""
    coverage = hero_coverage(str(state.get("hero") or ""))
    if coverage == "full" and _plays_support(state):
        return "support"
    return coverage


def _lane_record(opponents: list[str]) -> dict[str, Any] | None:
    """The player's past lanes against the enemy now in their lane
    (lane_duel.lane_record_for over PlayerService.lane_records)."""
    if not opponents:
        return None
    return lane_record_for(opponents, PLAYER_SERVICE.lane_records())


def _player_lane(extra: dict[str, Any]) -> str | None:
    """The player's observed lane; unknown coordinates stay unknown."""
    x, y = extra.get("xpos"), extra.get("ypos")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return lane_of(float(x), float(y))


def _plays_support(state: Mapping[str, object] | None) -> bool:
    state = state or {}
    raw_extra = state.get("extra_context")
    extra: Mapping[str, object] = raw_extra if isinstance(raw_extra, dict) else {}
    if extra.get("source_type") != "live_gsi":
        return False
    return _role_is_support(_live_role(state))


def _role_is_support(role: dict[str, Any] | None) -> bool:
    return role is not None and role.get("role") == "support" and role.get("source") != "hero"


def _live_role(state: Mapping[str, object] | None) -> dict[str, Any] | None:
    state = state or {}
    hero = str(state.get("hero") or "")
    prior = PLAYER_SERVICE.role_prior(hero) if hero else None
    return MATCH_MEMORY.role_snapshot(prior)


def _live_role_and_hint(response: dict[str, object], lang: str) -> dict[str, object]:
    """The player's position and the map hint (timer or role tip), live GSI only."""
    if response.get("demo_mode") or response.get("status") in {"waiting_for_gsi", "stale_gsi"}:
        return {}
    current = get_current_state()
    raw_state = current.get("state")
    state = raw_state if isinstance(raw_state, dict) else {}
    raw_extra = state.get("extra_context")
    extra = raw_extra if isinstance(raw_extra, dict) else {}
    if extra.get("source_type") != "live_gsi":
        return {}
    role = _live_role(state)
    clock = extra.get("clock_time")
    trackers = MATCH_MEMORY.tracker_snapshot(
        clock=clock if isinstance(clock, int) else None,
        lane=_player_lane(extra),
        alive=extra.get("alive") is not False,
        lang=lang,
    )
    gold = _gold_hint_inputs(state, extra, role)
    map_enabled = _map_hints["enabled"]
    hero = str(state.get("hero") or "")
    names = extra.get("item_names") if isinstance(extra.get("item_names"), list) else None
    carry_advisor = map_enabled and hero_coverage(hero) == "full" and not _plays_support(state)
    key_item = (
        PLAYER_SERVICE.key_item(hero)
        if map_enabled and role and role.get("role") != "support"
        else None
    )
    save_item = (
        PLAYER_SERVICE.save_item(hero, names, trackers.enemies or None)
        if map_enabled and role and role.get("role") == "support"
        else None
    )
    lane_record = _lane_record(trackers.opponents) if map_enabled else None
    draft = (
        PLAYER_SERVICE.draft_item(hero, names, trackers.enemies or None, role.get("role"))
        if map_enabled
        and role
        and role.get("role") != "support"
        and isinstance(clock, int)
        and clock <= DRAFT_UNTIL
        else None
    )
    note = (
        PLAYER_SERVICE.plan_note(hero, trackers.enemies or None, clock // 60, role.get("role"))
        if map_enabled and role and role.get("role") != "support" and isinstance(clock, int)
        else None
    )
    inputs = LiveHintInputs(
        role=role,
        gold=gold,
        map_enabled=map_enabled,
        carry_advisor=carry_advisor,
        key_item=key_item,
        save_item=save_item,
        lane_record=lane_record,
        draft_item=draft,
        plan_note=note,
        fight_abilities=PLAYER_SERVICE.fight_abilities(hero, (role or {}).get("role"))
        if map_enabled
        else None,
        skill_build=PLAYER_SERVICE.skill_build(hero, trackers.enemies or None),
    )
    return MATCH_MEMORY.live_hints(state, extra, trackers, inputs, lang)


def _gold_hint_inputs(
    state: Mapping[str, object], extra: Mapping[str, object], role: dict[str, Any] | None
) -> GoldHintInputs:
    """Prepare item metadata before acquiring tip ownership."""
    clock = extra.get("clock_time")
    gold = state.get("gold")
    role_name = role.get("role") if role else None
    hero = str(state.get("hero") or "")
    names = owned_items(extra)
    next_item = None
    part = None
    if role_name != "support" and isinstance(clock, int) and clock >= 3 * 60:
        try:
            item = PLAYER_SERVICE.next_item(hero, names, minute=state.get("minute"), role=role_name)
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                next_item = item
                # The quick-buy step: the part the gold already buys.
                part = PLAYER_SERVICE.buy_now(
                    hero, item["key"], names, gold if isinstance(gold, int) else None
                )
        except Exception as error:  # noqa: BLE001 - never breaks the live path
            record_error("gold-hint", error)
    return GoldHintInputs(
        next_item=next_item,
        buy_now=part,
        start_items=_start_items(state, role_name)
        if isinstance(clock, int) and clock < 3 * 60
        else None,
        pre_spawn=state.get("game_state") in PRE_SPAWN_STATES,
    )


def _start_items(state: Mapping[str, object], role: str | None) -> list[dict[str, Any]] | None:
    """The usual start on the hero in the player's role (high-rank data, else OpenDota)."""
    try:
        return PLAYER_SERVICE.start_items(str(state.get("hero") or ""), role) or None
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("start-items", error)
        return None


GAME_PLAN_STATUSES = {"no_advice", "monitoring", "unsupported_hero"}


def _game_plan_for_overlay(response: dict[str, object], lang: str) -> dict[str, object] | None:
    """The plan for this game while nothing else is on the card (-0:20 to 1:30)."""
    if response.get("status") not in GAME_PLAN_STATUSES or response.get("demo_mode"):
        return None
    current = get_current_state()
    state = current.get("state") if isinstance(current.get("state"), dict) else {}
    extra = state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
    if extra.get("source_type") != "live_gsi":
        return None
    clock = extra.get("clock_time")
    if not isinstance(clock, int) or not (
        GAME_PLAN_SHOW_FROM_CLOCK <= clock < GAME_PLAN_SHOW_UNTIL_CLOCK
    ):
        return None
    try:
        role = _live_role(state)
        hero, role_name = str(state.get("hero") or ""), role.get("role") if role else None
        plan = PLAYER_SERVICE.game_plan(hero, lang, role_name)
        if plan is not None and lang != "en":
            # Spoken in English when Windows has no Ukrainian voice (overlay/voice.js).
            english = PLAYER_SERVICE.game_plan(hero, "en", role_name)
            if english is not None:
                plan = {**plan, "lines_en": english["lines"]}
        return plan
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("game-plan", error)
        return None


def _death_screen_for_overlay(response: dict[str, object], lang: str) -> dict[str, object] | None:
    """While the player is dead (live GSI): how it happened and what to do now."""
    # A frozen "dead" snapshot must not hide the lost-connection status.
    if response.get("demo_mode") or response.get("status") in {"waiting_for_gsi", "stale_gsi"}:
        return None
    current = get_current_state()
    state = current.get("state") if isinstance(current.get("state"), dict) else {}
    extra = state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
    if extra.get("source_type") != "live_gsi" or extra.get("alive") is not False:
        return None
    carry = hero_coverage(str(state.get("hero") or "")) == "full" and not _plays_support(state)
    try:
        return PLAYER_SERVICE.death_screen(
            _with_enemies(state),
            lang,
            next_item_for_hero=carry,
            role=(_live_role(state) or {}).get("role"),
        )
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("death-screen", error)
        return None


def _post_game_for_overlay(response: dict[str, object], lang: str) -> dict[str, object] | None:
    """The match summary while Dota shows the score screen (post_game.py)."""
    if response.get("demo_mode"):
        return None
    try:
        return PLAYER_SERVICE.post_game_card(post_game_match_id(), lang)
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("post-game", error)
        return None


def _overlay_recommendation_payload() -> dict[str, object]:
    # The decision runs whole against one snapshot and its MatchMemory/scheduler
    # (live_operation.py); the advice log and the review note are written after.
    with live_operation():
        decided = _overlay_decision()
        if isinstance(decided, dict):
            return decided
        current, state, request, decision_point, scheduled, rag_context = decided
        response = _overlay_response(
            scheduled, current["timestamp"], None, state, record_history=False
        )
        COACH_SESSION_HISTORY.record_overlay_advice(response, state)
    if scheduled.new_advice and scheduled.recommendation is not None:
        log_filename = _recommendation_log_filename(
            request=request,
            rag_context=rag_context,
            response=scheduled.recommendation,
            decision_point=decision_point,
            provider=scheduled.source,
            fallback_reason="overlay_fallback_first" if scheduled.source == "fallback" else None,
        )
        # The post-match review lists the advice given in this match.
        try:
            extra = (
                state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
            )
            PLAYER_SERVICE.note_live_advice(
                extra.get("clock_time"),
                decision_point,
                scheduled.recommendation.action,
                scheduled.recommendation.reason,
                scheduled.advice_mode,
            )
        except Exception as error:  # noqa: BLE001 - never breaks the live path
            record_error("advice-note", error)
        if log_filename:
            response["log_file"] = log_filename
    _record_advice_files(response, state)
    return response


def _record_advice_files(response: dict[str, object], state: dict[str, object]) -> None:
    """The debug session recording and the match recording (disk; outside the
    live operation)."""
    LIVE_SESSION_RECORDER.record_advice(response, state)
    extra = state.get("extra_context")
    MATCH_RECORDS.record_advice(
        {**response, "clock_time": extra.get("clock_time") if isinstance(extra, dict) else None}
    )


def _overlay_decision() -> dict[str, object] | tuple[Any, ...]:
    """An early status response, or what the scheduler decided and its inputs."""
    demo_response = _get_demo_overlay_response()
    if demo_response is not None:
        return demo_response

    current = get_current_state()
    if current["status"] == "waiting_for_gsi":
        return _overlay_status(
            "waiting_for_gsi",
            {},
            last_updated=None,
            suppressed_reason="no_advice",
        )

    if _is_live_gsi_stale(current):
        stale_state = current.get("state")
        state = stale_state if isinstance(stale_state, dict) else {}
        return _overlay_status(
            "stale_gsi",
            state,
            last_updated=current.get("timestamp"),
            suppressed_reason="stale_gsi",
            message="Waiting for live GSI...",
            gsi_stale=True,
            seconds_since_last_gsi=_seconds_since_timestamp(current.get("timestamp")),
        )

    state = _with_hero_gameplay(current["state"] or {})
    coverage = _advisor_coverage(state)
    if not coverage:
        ADVICE_SCHEDULER.observe_state(state, "NO_ADVICE")
        return _overlay_status(
            "unsupported_hero",
            state,
            last_updated=current["timestamp"],
            suppressed_reason="unsupported_hero",
            message="Current hero is not supported by carry advisor yet.",
        )

    decision_point = _covered_decision_point(
        _useful_disable(
            _live_conservative_decision_point(detect_decision_point(state), state), state
        ),
        coverage,
    )

    if decision_point == "NO_ADVICE":
        ADVICE_SCHEDULER.observe_state(state, decision_point)
        active = ADVICE_SCHEDULER.active_advice_for_state(state, decision_point)
        if active is not None:
            return _overlay_response(active, current["timestamp"], state=state)
        return _overlay_status(
            "no_advice",
            state,
            last_updated=current["timestamp"],
            suppressed_reason="no_advice",
            decision_point=decision_point,
        )

    if decision_point == "SOFT_STATUS":
        ADVICE_SCHEDULER.observe_state(state, decision_point)
        active = ADVICE_SCHEDULER.active_advice_for_state(state, decision_point)
        if active is not None:
            return _overlay_response(active, current["timestamp"], state=state)
        return _overlay_status(
            "monitoring",
            state,
            last_updated=current["timestamp"],
            suppressed_reason=None,
            decision_point=decision_point,
            message="Monitoring lane — no urgent advice.",
        )

    state = _with_enemies(state)
    state = _with_next_item(state, coverage, decision_point)
    state = _with_death_items(state, decision_point)
    state = _with_low_hp_repeats(state, decision_point)
    state = _with_coverage(state, coverage)
    try:
        request = GameSituationRequest(**state)
    except ValidationError as exc:
        return _overlay_status(
            "invalid_state",
            state,
            last_updated=current["timestamp"],
            suppressed_reason=None,
            decision_point=decision_point,
            detail=exc.errors(include_context=False),
        )

    rag_context: list[str] = []

    def context() -> list[str]:
        rag_context.extend(_retrieve_rag_context(request))
        return rag_context

    scheduled = ADVICE_SCHEDULER.evaluate(request, decision_point, context)
    if scheduled.new_advice and scheduled.hero_gameplay is not None:
        MATCH_MEMORY.note_gameplay_advice(state, scheduled.hero_gameplay)
    return current, state, request, decision_point, scheduled, rag_context


def _with_hero_gameplay(state: dict[str, Any]) -> dict[str, Any]:
    """Read the owned pending episode while the live operation owns this snapshot."""
    extra = state.get("extra_context")
    if not isinstance(extra, dict):
        return state
    context = MATCH_MEMORY.gameplay_context(state)
    return {**state, "extra_context": {**extra, "hero_gameplay": context}}


@app.post("/demo/replay-state", summary="Inject one replay-derived state for overlay demo")
async def demo_replay_state(request: Request):
    """Accept one GSI-like replay state and update the overlay through the real advice path."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "Request body must be valid JSON."},
        )

    if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "Payload must contain a state object."},
        )

    return await run_in_threadpool(_process_demo, payload)


def _process_demo(payload: dict[str, Any]) -> dict[str, Any]:
    with LIVE_PATH_METRICS.measure("demo.total"):
        return _demo_replay_payload(payload)


def _demo_replay_payload(payload: dict[str, Any]) -> dict[str, Any]:
    token = _DEMO_OVERLAY_CACHE.reserve()
    timestamp_seconds = _safe_int(payload.get("timestamp_seconds"), 0)
    state = dict(payload["state"])
    extra_context = (
        state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
    )
    state["extra_context"] = {
        **extra_context,
        "demo_replay_mode": True,
        "demo_simulation_file": str(payload.get("simulation_file") or ""),
        "demo_speed": payload.get("speed"),
    }
    demo_now = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=timestamp_seconds)
    timestamp = demo_now.isoformat()

    with live_operation():
        MATCH_MEMORY.observe_state(state)
        response = _overlay_response_for_state(state, timestamp=timestamp, now=demo_now)
    response.update(
        {
            "demo_mode": True,
            "simulated_timestamp_seconds": timestamp_seconds,
            "simulated_time_label": _format_game_time(timestamp_seconds),
        }
    )
    COACH_SESSION_HISTORY.record_overlay_advice(response, state)
    _set_demo_overlay_response(response, token)
    return {"status": "ok", "overlay": response}


@app.get("/demo/session-summary", summary="Get coach-style summary for the current demo/session")
def demo_session_summary():
    return COACH_SESSION_HISTORY.build_summary(ADVICE_SCHEDULER.stats())


@app.get("/advice/recent", summary="Get the most recent advice shown in this session")
def recent_advice(limit: int = 5, lang: str = "en"):
    """Newest first; used by the launcher's "Recent advice" card."""
    limit = max(1, min(int(limit), 20))
    records = COACH_SESSION_HISTORY.records(limit)
    return {
        "items": localize_advice_items(
            [
                {
                    "id": record.get("id"),
                    "timestamp": record.get("timestamp"),
                    "game_time": record.get("game_time") or None,
                    "hero": record.get("hero"),
                    "action": record.get("action"),
                    "reason": record.get("reason"),
                    "action_message": record.get("action_message"),
                    "reason_message": record.get("reason_message"),
                    "priority": record.get("priority"),
                    "advice_mode": record.get("advice_mode"),
                    "why": why(record.get("decision_point"), normalize_lang(lang)),
                }
                for record in reversed(records)
            ],
            normalize_lang(lang),
        )
    }


class AdviceSettings(BaseModel):
    frequency: str | None = None
    role: str | None = None
    map_hints: bool | None = None
    match_records: bool | None = None


# Map hints (timers, role tips) on the overlay; the launcher switches them.
_map_hints = {"enabled": MAP_HINTS}
MATCH_RECORDS.set_enabled(MATCH_RECORDS_ENABLED)
set_role_setting(ADVICE_ROLE)


def _advice_settings() -> dict[str, object]:
    return {
        "frequency": ADVICE_SCHEDULER.frequency,
        "options": list(FREQUENCIES),
        "role": role_setting(),
        "role_options": list(ROLE_SETTINGS),
        "map_hints": _map_hints["enabled"],
        "match_records": MATCH_RECORDS.enabled,
    }


@app.get("/settings/advice", summary="Live advice preferences")
def get_advice_settings():
    return _advice_settings()


@app.post("/settings/advice", summary="Change live advice preferences")
def set_advice_settings(settings: AdviceSettings):
    if settings.frequency is not None:
        ADVICE_SCHEDULER.set_frequency(settings.frequency)
    if settings.role is not None:
        set_role_setting(settings.role)
    if settings.map_hints is not None:
        _map_hints["enabled"] = bool(settings.map_hints)
    if settings.match_records is not None:
        MATCH_RECORDS.set_enabled(bool(settings.match_records))
    return _advice_settings()


@app.get("/match-records", summary="Match recordings of the last week kept on this computer")
def match_records():
    return {
        "enabled": MATCH_RECORDS.enabled,
        "keep_days": KEEP_DAYS,
        "records": MATCH_RECORDS.list(),
    }


@app.get("/match-records/{record_id}", summary="One match recording (gzip JSON lines)")
def match_record_file(record_id: str):
    path = MATCH_RECORDS.path_of(record_id)
    if path is None:
        return JSONResponse(status_code=404, content={"detail": "No such recording."})
    return FileResponse(path, media_type="application/gzip", filename=path.name)


def _census_for_report() -> dict[str, object]:
    """This run's GSI census; before any in-game data, the one saved by the last
    run as `previous_run` (a report sent after a restart still shows the match)."""
    summary: dict[str, object] = dict(GSI_CENSUS.summary())
    if not summary.get("in_game_payloads"):
        previous = load_previous(PLAYER_SERVICE.data_dir / CENSUS_FILE)
        if previous is not None:
            summary["previous_run"] = previous
    return summary


def _operations_health() -> dict[str, Any]:
    seconds = _gsi_status_response().get("seconds_since_last_gsi")
    return operations_health.build(
        **PLAYER_SERVICE.operations(),
        live_path=LIVE_PATH_METRICS.snapshot(),
        gsi_seconds_since=float(seconds) if isinstance(seconds, (int, float)) else None,
        builds_generated=stratz_builds.generated(),
        error_counts=recent_errors()["counts"],
    )


@app.get("/operations/health", summary="Queues, match saving and data freshness")
def operations_health_endpoint():
    """The developer section's health block: counts, ages and times only."""
    return _operations_health()


@app.get("/diagnostics", summary="State and recent errors for a problem report")
def diagnostics():
    """No keys and no raw GSI: what a tester can safely send to the developer."""
    records = COACH_SESSION_HISTORY.records()[-10:]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "runtime": runtime_info(),
        "live_path": LIVE_PATH_METRICS.snapshot(),
        "recording_health": {
            "live_session": LIVE_SESSION_RECORDER.health(),
            "match_records": MATCH_RECORDS.health(),
        },
        "knowledge_base": KNOWLEDGE_BASE.health(),
        "config": {
            "use_llm": USE_LLM,
            "llm_provider": LLM_PROVIDER,
            "live_conservative_mode": LIVE_CONSERVATIVE_MODE,
            "gsi_stale_seconds": GSI_STALE_SECONDS,
            "opendota_enabled": OPENDOTA_ENABLED,
            "writable_dir": str(WRITABLE_DIR),
            "player_data_dir": str(PLAYER_DATA_DIR),
        },
        "gsi": _gsi_status_response(),
        # Field names and counts only (gsi_census.py): what GSI really sends.
        "gsi_census": _census_for_report(),
        "scheduler": {**ADVICE_SCHEDULER.stats(), "frequency": ADVICE_SCHEDULER.frequency},
        "recent_advice": [
            {
                key: record.get(key)
                for key in ("timestamp", "game_time", "hero", "action", "priority", "advice_mode")
            }
            for record in reversed(records)
        ],
        "player": PLAYER_SERVICE.diagnostics(),
        "operations": _operations_health(),
        "errors": recent_errors(),
    }


@app.get("/overlay/stats", summary="Get overlay advice scheduler telemetry")
def overlay_stats():
    return ADVICE_SCHEDULER.stats()


@app.get("/overlay/debug/state_machine", summary="Inspect live overlay advice state machine")
def overlay_state_machine_debug():
    current = get_current_state()
    state = current.get("state") if isinstance(current.get("state"), dict) else {}
    decision_point = detect_decision_point(state) if state else "NO_ADVICE"
    return ADVICE_SCHEDULER.state_machine_debug(
        current_decision_point=decision_point,
        state=state,
    )


def _overlay_response(
    scheduled: ScheduledAdvice,
    gsi_timestamp: str | None,
    log_filename: str | None = None,
    state: dict[str, object] | None = None,
    record_history: bool = True,
) -> dict[str, object]:
    recommendation = (
        advice_messages(scheduled.recommendation.model_dump())
        if scheduled.recommendation is not None
        else None
    )
    response: dict[str, object] = {
        "status": scheduled.status,
        "decision_point": scheduled.decision_point,
        "recommendation": recommendation,
        "advice_count": scheduled.advice_count,
        "llm_used": scheduled.llm_used,
        "source": scheduled.source,
        "last_updated": scheduled.last_updated or gsi_timestamp,
        "next_allowed_advice_in_seconds": scheduled.next_allowed_advice_in_seconds,
        "advice_mode": scheduled.advice_mode,
        "suppressed_reason": scheduled.suppressed_reason,
        "message": _overlay_status_message(scheduled),
        "active_advice_until": scheduled.active_advice_until,
        "last_visible_advice": advice_messages(scheduled.last_visible_advice),
        "is_pinned": scheduled.is_pinned,
        "new_advice": scheduled.new_advice,
        "game_time_gap_since_previous_advice": scheduled.game_time_gap_since_previous_advice,
        "suppressed_by_game_time_spacing": scheduled.suppressed_by_game_time_spacing,
        "timestamp": gsi_timestamp,
        "event": scheduled.decision_point,
        "hero_gameplay": scheduled.hero_gameplay,
        **_overlay_live_context(state or {}),
    }
    if log_filename:
        response["log_file"] = log_filename
    if record_history:
        COACH_SESSION_HISTORY.record_overlay_advice(response, state or {})
        _record_advice_files(response, state or {})
    return {
        **response,
    }


def _overlay_response_for_state(
    state: dict[str, object],
    *,
    timestamp: str | None,
    now: datetime | None = None,
) -> dict[str, object]:
    coverage = hero_coverage(str(state.get("hero") or ""))
    if not coverage:
        ADVICE_SCHEDULER.observe_state(state, "NO_ADVICE", now=now)
        return _overlay_status(
            "unsupported_hero",
            state,
            last_updated=timestamp,
            suppressed_reason="unsupported_hero",
            message="Current hero is not supported by carry advisor yet.",
            now=now,
        )

    decision_point = _covered_decision_point(detect_decision_point(state), coverage)

    if decision_point == "NO_ADVICE":
        ADVICE_SCHEDULER.observe_state(state, decision_point, now=now)
        active = ADVICE_SCHEDULER.active_advice_for_state(state, decision_point, now=now)
        if active is not None:
            return _overlay_response(active, timestamp, state=state, record_history=False)
        return _overlay_status(
            "no_advice",
            state,
            last_updated=timestamp,
            suppressed_reason="no_advice",
            decision_point=decision_point,
            now=now,
        )

    if decision_point == "SOFT_STATUS":
        ADVICE_SCHEDULER.observe_state(state, decision_point, now=now)
        active = ADVICE_SCHEDULER.active_advice_for_state(state, decision_point, now=now)
        if active is not None:
            return _overlay_response(active, timestamp, state=state, record_history=False)
        return _overlay_status(
            "monitoring",
            state,
            last_updated=timestamp,
            suppressed_reason=None,
            decision_point=decision_point,
            message="Monitoring lane — no urgent advice.",
            now=now,
        )

    state = _with_enemies(state)
    state = _with_next_item(state, coverage, decision_point)
    state = _with_death_items(state, decision_point)
    state = _with_low_hp_repeats(state, decision_point)
    state = _with_coverage(state, coverage)
    try:
        game_request = GameSituationRequest(**state)
    except ValidationError as exc:
        return _overlay_status(
            "invalid_state",
            state,
            last_updated=timestamp,
            suppressed_reason=None,
            decision_point=decision_point,
            now=now,
            detail=exc.errors(include_context=False),
        )

    rag_context: list[str] = []

    def context() -> list[str]:
        rag_context.extend(_retrieve_rag_context(game_request))
        return rag_context

    scheduled = ADVICE_SCHEDULER.evaluate(game_request, decision_point, context, now=now)
    log_filename = None
    if scheduled.new_advice and scheduled.recommendation is not None:
        log_filename = _recommendation_log_filename(
            request=game_request,
            rag_context=rag_context,
            response=scheduled.recommendation,
            decision_point=decision_point,
            provider=scheduled.source,
            fallback_reason="overlay_demo_fallback_first"
            if scheduled.source == "fallback"
            else None,
        )

    return _overlay_response(scheduled, timestamp, log_filename, state, record_history=False)


# Decisions that can become the post-laning "safe farm route" advice.
FARM_ROUTE_DECISIONS = {"SAFE_FARMING", "LANING_FARM_CHECK", "FARMING_PHASE_PRESSURE"}


def _with_next_item(
    state: dict[str, object], coverage: str | None, decision_point: str
) -> dict[str, object]:
    """A core's farm advice names the next item of the hero's usual build and the
    gold it still needs (app/next_item.py, post_laning_coach._next_item_copy)."""
    raw_extra = state.get("extra_context")
    if (
        decision_point not in FARM_ROUTE_DECISIONS
        or coverage != "full"
        or not isinstance(raw_extra, dict)
        or _plays_support(state)
    ):
        return state
    # Aghanim's Shard is consumed on purchase: GSI says so on the hero instead.
    owned = owned_items(raw_extra)
    try:
        enemies = raw_extra.get("enemy_heroes")
        item = PLAYER_SERVICE.next_item(
            str(state.get("hero") or ""),
            owned,
            enemies=enemies if isinstance(enemies, list) else None,
            minute=state.get("minute"),
            gold=state.get("gold"),
            role=(_live_role(state) or {}).get("role"),
        )
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("next-item", error)
        return state
    if item is None:
        return state
    return {**state, "extra_context": {**raw_extra, "next_item": item}}


def _with_coverage(state: dict[str, object], coverage: str | None) -> dict[str, object]:
    """The advisor coverage for the scheduler: its heartbeat names the farm pace
    and the kill score only for a core (post_laning_coach._situational_farm_copy)."""
    raw_extra = state.get("extra_context")
    if not isinstance(raw_extra, dict):
        return state
    return {**state, "extra_context": {**raw_extra, "advisor_coverage": coverage}}


# Death reviews: the advice after a death names the rescue item left unpressed.
DEATH_DECISIONS = {
    "DEATH_REVIEW",
    "REPEATED_DEATH_PATTERN",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN",
    "DEATH_LOW_RESOURCE",
    "DEAD_WAIT",
}


def _with_enemies(state: dict[str, object]) -> dict[str, object]:
    """The enemy heroes seen on the minimap this match (enemy_heroes.py), for the
    counter items; the state unchanged when none is known."""
    raw_extra = state.get("extra_context")
    enemies = MATCH_MEMORY.enemy_heroes()
    if not enemies or not isinstance(raw_extra, dict) or raw_extra.get("source_type") != "live_gsi":
        return state
    return {**state, "extra_context": {**raw_extra, "enemy_heroes": enemies}}


LOW_HP_REPEAT_DECISIONS = {"LOW_HP", "LOW_HP_WARNING"}


def _with_low_hp_repeats(state: dict[str, object], decision_point: str) -> dict[str, object]:
    """How many low-HP cards this match has had before this one, so a repeat
    says something new (live_tools.low_hp_repeat_reason)."""
    raw_extra = state.get("extra_context")
    if decision_point not in LOW_HP_REPEAT_DECISIONS or not isinstance(raw_extra, dict):
        return state
    try:
        before = PLAYER_SERVICE.advice_count(LOW_HP_REPEAT_DECISIONS)
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("low-hp-repeats", error)
        return state
    return {**state, "extra_context": {**raw_extra, "low_hp_before": before}}


def _with_death_items(state: dict[str, object], decision_point: str) -> dict[str, object]:
    """The rescue items ready in the last seconds before this death (the match
    recording's last_moments) and where it happened, for live_tools.death_copy."""
    raw_extra = state.get("extra_context")
    if decision_point not in DEATH_DECISIONS or not isinstance(raw_extra, dict):
        return state
    try:
        death = PLAYER_SERVICE.recent_death(raw_extra.get("clock_time"))
    except Exception as error:  # noqa: BLE001 - never breaks the live path
        record_error("death-items", error)
        return state
    if not death:
        return state
    added = {
        "death_items": death["items"],
        "death_place": death["place"],
        "recent_deaths": death.get("recent"),
        "death_burst": death.get("burst"),
        # The game's own counter: the recording misses deaths before the app
        # started or during a gap in GSI.
        "match_deaths": raw_extra.get("deaths")
        if isinstance(raw_extra.get("deaths"), int)
        else None,
    }
    return {**state, "extra_context": {**raw_extra, **added}}


def _overlay_status_message(scheduled: ScheduledAdvice) -> str | None:
    if scheduled.status == "active_advice":
        return None
    if scheduled.status == "cooldown":
        return "Monitoring..."
    if scheduled.status == "no_advice":
        return "Monitoring lane — no urgent advice."
    return None


def _gsi_status_response() -> dict[str, object]:
    demo_response = _get_demo_overlay_response()
    if demo_response is not None:
        return {
            "gsi_connected": False,
            "in_match": False,
            "last_gsi_received_at": None,
            "seconds_since_last_gsi": None,
            "hero": demo_response.get("hero"),
            "game_time": demo_response.get("simulated_time_label") or demo_response.get("minute"),
            "clock_time": None,
            "stage": demo_response.get("stage", "unknown"),
            "received_fields": [],
            "missing_important_fields": [],
            "last_advice_time": demo_response.get("last_updated"),
            "current_mode": "demo_replay",
        }

    current = get_gsi_status_snapshot()
    timestamp = current.get("timestamp")
    state = current.get("state") if isinstance(current.get("state"), dict) else {}
    seconds_since = _seconds_since_timestamp(timestamp)
    connected = seconds_since is not None and seconds_since <= GSI_STALE_SECONDS
    fields = current["fields_summary"]
    latest_advice = ADVICE_SCHEDULER.latest_advice_snapshot()
    latest_recommendation = latest_advice.get("recommendation")
    extra_context = (
        state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
    )
    return {
        "gsi_connected": connected,
        "in_match": connected and current["in_match"],
        # The score screen with a fresh review: the overlay shows the summary card.
        "post_game": connected and _post_game_for_overlay({}, "en") is not None,
        "last_gsi_received_at": timestamp,
        "seconds_since_last_gsi": round(seconds_since, 2) if seconds_since is not None else None,
        "hero": state.get("hero"),
        "hero_coverage": _advisor_coverage(state) if state else None,
        "game_time": extra_context.get("game_time") or state.get("minute"),
        # The in-game clock as the player sees it (negative before the horn).
        "clock_time": extra_context.get("clock_time"),
        "stage": _stage_label(state) if state else "unknown",
        "received_fields": _received_gsi_fields(fields),
        "missing_important_fields": _missing_important_fields(state, fields),
        "last_advice_time": latest_advice.get("last_updated"),
        "current_advice": latest_recommendation.get("action")
        if isinstance(latest_recommendation, dict)
        else None,
        "current_mode": "live_gsi" if state else "idle",
        "live_role": _live_role(state) if extra_context.get("source_type") == "live_gsi" else None,
    }


def _is_live_gsi_stale(current: dict[str, object]) -> bool:
    seconds_since = _seconds_since_timestamp(current.get("timestamp"))
    return seconds_since is not None and seconds_since > GSI_STALE_SECONDS


def _seconds_since_timestamp(timestamp: object) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def _received_gsi_fields(fields: dict[str, object]) -> list[str]:
    received: list[str] = []
    for name in ("map", "player", "hero", "items", "abilities", "buildings", "draft"):
        if fields.get(f"has_{name}"):
            received.append(name)
    for block_name, field_name in (
        ("map", "available_map_fields"),
        ("player", "available_player_fields"),
        ("hero", "available_hero_fields"),
    ):
        values = fields.get(field_name)
        if isinstance(values, list):
            received.extend(f"{block_name}.{value}" for value in values)
    return sorted(set(received))


def _missing_important_fields(state: dict[str, object], fields: dict[str, object]) -> list[str]:
    missing: list[str] = []
    for name in ("map", "player", "hero", "items"):
        if not fields.get(f"has_{name}"):
            missing.append(name)
    extra_context = (
        state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
    )
    important_context = {
        "hero.health": state.get("hp_percent"),
        "hero.mana": extra_context.get("mana_percent"),
        "player.last_hits": extra_context.get("last_hits"),
        "hero.alive": extra_context.get("alive"),
        "map.game_time": extra_context.get("game_time"),
        "abilities": extra_context.get("abilities") if extra_context.get("has_abilities") else None,
    }
    missing.extend(name for name, value in important_context.items() if value is None)
    return sorted(set(missing))


def _live_conservative_decision_point(decision_point: str, state: dict[str, object]) -> str:
    # Intentional trade-off (do not "fix"): in live GSI mode we deliberately
    # downgrade OBJECTIVE_FIGHT_CHECK to SOFT_STATUS whenever the local GSI
    # payload is missing nearby_allies_enemies / enemy_positions /
    # exact_teamfight_context, or context_confidence != "high" - even if the
    # team appears fully alive. Live GSI cannot confirm team readiness, so we
    # refuse to escalate toward an objective call without those signals. This is
    # intentional conservatism (under-advice over wrong objective calls),
    # documented in AGENTS.md. Phase 3 records the trade-off without changing it.
    if not LIVE_CONSERVATIVE_MODE:
        return decision_point
    extra_context = (
        state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
    )
    if extra_context.get("source_type") != "live_gsi":
        return decision_point
    if decision_point != "OBJECTIVE_FIGHT_CHECK":
        return decision_point
    missing_signals = extra_context.get("missing_signals")
    if not isinstance(missing_signals, list):
        missing_signals = []
    if (
        "nearby_allies_enemies" in missing_signals
        or "enemy_positions" in missing_signals
        or "exact_teamfight_context" in missing_signals
        or extra_context.get("context_confidence") != "high"
    ):
        return "SOFT_STATUS"
    return decision_point


def _useful_disable(decision_point: str, state: dict[str, object]) -> str:
    """Live GSI: a disable card only when something can be pressed as it ends (or
    now, when only silenced or muted) — live_tools.disabled_copy. «Wait out the
    disable» alone was up to 40 % of the urgent cards and changes nothing."""
    if decision_point != "DISABLED_STATUS":
        return decision_point
    raw_extra = state.get("extra_context")
    extra: dict[str, object] = raw_extra if isinstance(raw_extra, dict) else {}
    if extra.get("source_type") != "live_gsi":
        return decision_point
    if disabled_copy(extra, state.get("hero")) is None:
        return "NO_ADVICE"
    return decision_point


# Heroes outside the advisor get only what is true for any hero: survival,
# deaths, disables, mana, buyback. Farm, item, objective and hero-ability advice
# assume a core (or a hero profile) and stay off for them.
SAFETY_ONLY_DECISIONS = {
    "LOW_HP",
    "LOW_HP_WARNING",
    "RECENT_DAMAGE_WARNING",
    "OVERSTAY_WARNING",
    "DEATH_REVIEW",
    "REPEATED_DEATH_PATTERN",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN",
    "DEATH_LOW_RESOURCE",
    "DISABLED_STATUS",
    "DEAD_WAIT",
    "LOW_MANA",
    "BUYBACK_AVAILABLE",
    "SMOKED_STATUS",
    "NO_ADVICE",
    "SOFT_STATUS",
}


# A support (a profiled one, or a core played as a support) also gets its own
# saves (hero safety, ability cooldowns), fights and objectives and the lane regen
# check; farm pace and items stay off — a support's gold and last hits are the
# map tips' business (stacks, pulls, wards, save items).
SUPPORT_DECISIONS = SAFETY_ONLY_DECISIONS | {
    "HERO_SURVIVABILITY_RISK",
    "HERO_GAMEPLAY",
    "ABILITY_SAFETY_COOLDOWN",
    "OBJECTIVE_FIGHT_CHECK",
    "BAD_FIGHT_RISK",
    "LANING_REGEN_CHECK",
}


def _covered_decision_point(decision_point: str, coverage: str | None) -> str:
    if coverage == "safety" and decision_point not in SAFETY_ONLY_DECISIONS:
        return "NO_ADVICE"
    if coverage == "support" and decision_point not in SUPPORT_DECISIONS:
        return "NO_ADVICE"
    return decision_point


def _overlay_status(
    status: str,
    state: dict[str, object],
    *,
    last_updated: str | None,
    suppressed_reason: str | None,
    decision_point: str = "NO_ADVICE",
    message: str | None = None,
    now: datetime | None = None,
    **extra: object,
) -> dict[str, object]:
    """An overlay answer without advice; each caller keeps its own status and reason."""
    response: dict[str, object] = {
        "status": status,
        "decision_point": decision_point,
        "recommendation": None,
    }
    if message is not None:
        response["message"] = message
    response.update(
        {
            "advice_count": ADVICE_SCHEDULER.stats(now=now)["advice_count"],
            "llm_used": False,
            "source": "none",
            "last_updated": last_updated,
            "next_allowed_advice_in_seconds": 0,
            "advice_mode": "status",
            "suppressed_reason": suppressed_reason,
            "active_advice_until": None,
            "last_visible_advice": None,
            "is_pinned": False,
        }
    )
    return {**response, **extra, **_overlay_live_context(state)}


def _overlay_live_context(state: dict[str, object]) -> dict[str, object]:
    extra_context = (
        state.get("extra_context") if isinstance(state.get("extra_context"), dict) else {}
    )
    status_effects = extra_context.get("status_effects")
    if not isinstance(status_effects, list):
        status_effects = []
    hero_safety_flags = extra_context.get("hero_safety_flags")
    if not isinstance(hero_safety_flags, list):
        hero_safety_flags = []
    return {
        "current_mode": "live_gsi" if extra_context.get("source_type") == "live_gsi" else "idle",
        "live_conservative_mode": LIVE_CONSERVATIVE_MODE,
        "hero": state.get("hero"),
        "hero_coverage": _advisor_coverage(state),
        "minute": state.get("minute"),
        "stage": _stage_label(state),
        "game_state": state.get("game_state"),
        "hp_percent": state.get("hp_percent"),
        "mana_percent": extra_context.get("mana_percent"),
        "alive": extra_context.get("alive"),
        "respawn_seconds": extra_context.get("respawn_seconds"),
        "gpm": extra_context.get("gpm"),
        "xpm": extra_context.get("xpm"),
        "last_hits": extra_context.get("last_hits"),
        "status_effects": status_effects,
        "smoked": extra_context.get("smoked", False),
        "buyback_available": extra_context.get("buyback_available", False),
        "hero_safety_flags": hero_safety_flags,
        "hero_risk_level": extra_context.get("hero_risk_level", "low"),
        "hero_safety_reason": extra_context.get("hero_safety_reason", ""),
        "capability_source": extra_context.get("capability_source"),
        "source_type": extra_context.get("source_type"),
        "context_confidence": extra_context.get("context_confidence"),
        "farm_quality": extra_context.get("farm_quality"),
        "hp_pressure_state": extra_context.get("hp_pressure_state"),
        "position_zone": extra_context.get("position_zone"),
        "position_risk": extra_context.get("position_risk"),
        "laning_category": extra_context.get("laning_category"),
        "post_laning_category": extra_context.get("post_laning_category"),
        "available_signals": extra_context.get("available_signals", []),
        "missing_signals": extra_context.get("missing_signals", []),
        "partial_signals": extra_context.get("partial_signals", []),
        **MATCH_MEMORY.overlay_context(),
    }


def _stage_label(state: dict[str, object]) -> str:
    minute = _safe_int(state.get("minute"), 0)
    if minute < 10:
        return "laning"
    if minute < 20:
        return "post-laning"
    return "macro"


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_game_time(timestamp_seconds: int) -> str:
    timestamp_seconds = max(0, int(timestamp_seconds))
    return f"{timestamp_seconds // 60:02d}:{timestamp_seconds % 60:02d}"


def _set_demo_overlay_response(response: dict[str, object], token: DemoToken) -> bool:
    return _DEMO_OVERLAY_CACHE.publish(response, token, now=monotonic())


def _get_demo_overlay_response() -> dict[str, object] | None:
    return _DEMO_OVERLAY_CACHE.capture(now=monotonic())


def _clear_demo_overlay_response() -> None:
    _DEMO_OVERLAY_CACHE.clear()
