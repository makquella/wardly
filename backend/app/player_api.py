"""
player_api.py - HTTP endpoints for the linked player, matches and reviews.

GET    /player                   account, sync state, live match, last review
POST   /player/link              {"steam": "<Steam ID / Friend ID / profile link>"}
POST   /player/link-detected     link the account currently seen in GSI
DELETE /player                   forget the linked account (matches stay stored)
POST   /player/sync              pull profile + recent matches from OpenDota
GET    /player/matches           match table (newest first; ?hero_id=&result=win|loss&sort=&order=)
GET    /player/matches/{id}      one match: summary, scoreboard, post-match review
POST   /player/matches/{id}/refresh   fetch again / ask OpenDota to parse the replay
POST   /player/matches/{id}/add       fetch a match by its number (older than the history)
GET    /player/matches/{id}/add       where that stands (pending / ready / an error code)
POST   /player/matches/{id}/note      the player's own note on the match (empty removes it)
GET    /player/career            statistics and advice over the recent matches
POST   /player/matches/{id}/coach     (re)generate the AI coach review of a match
POST   /player/career/coach           (re)generate the AI coach review of recent matches
GET    /player/opendota          OpenDota key status (never returns the key)
POST   /player/opendota          {"api_key": "..."}: faster, higher OpenDota limits
DELETE /player/opendota          forget the OpenDota key
GET    /player/ai                AI coach settings (never returns the key)
POST   /player/ai                {"provider": "groq"|"openrouter", "api_key": "...", "model"?}
DELETE /player/ai                forget the key
POST   /player/ai/check          one small request to validate the key

All review texts follow `lang` (uk/en).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.advice_i18n import normalize_lang
from app.advice_scheduler import ADVICE_SCHEDULER
from app.coach_llm import env_settings
from app.config import (
    OPENDOTA_API_KEY,
    OPENDOTA_API_URL,
    OPENDOTA_CACHE_URL,
    OPENDOTA_ENABLED,
    PLAYER_DATA_DIR,
)
from app.history_backup import BackupError
from app.opendota import OpenDotaClient
from app.player_contracts import (
    CareerResponse,
    MatchDetailResponse,
    MatchListResponse,
    MatchNotFoundResponse,
    PlayerStatusResponse,
    ProfileResponse,
)
from app.player_profile import public_card
from app.player_service import PlayerService
from app.player_store import MATCH_SORTS
from app.steam_ids import SteamIdError

PLAYER_SERVICE = PlayerService(
    PLAYER_DATA_DIR,
    client=(
        OpenDotaClient(OPENDOTA_API_URL, api_key=OPENDOTA_API_KEY, cache_url=OPENDOTA_CACHE_URL)
        if OPENDOTA_ENABLED
        else None
    ),
    env_ai=env_settings(),
)

router = APIRouter(prefix="/player", tags=["player"])

# Match ids are stored as SQLite INTEGER (64-bit): bigger ids are a 422, not a 500.
MatchId = Annotated[int, Path(ge=0, le=2**63 - 1)]
# The launcher's id for one AI question (ask_runs.py).
ASK_REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"
HeroId = Annotated[int | None, Query(ge=0, le=100_000)]
Offset = Annotated[int, Query(ge=0, le=10_000_000)]


class LinkRequest(BaseModel):
    steam: str


class OpenDotaKeyRequest(BaseModel):
    api_key: str


class AskRequest(BaseModel):
    question: str
    # The launcher's id for this question: asking again with it (after a lost
    # response) returns the same run instead of a second provider call.
    request_id: str | None = Field(None, pattern=ASK_REQUEST_ID_PATTERN)


class FocusRequest(BaseModel):
    finding_id: str


class AIRequest(BaseModel):
    provider: str
    api_key: str
    model: str | None = None


@router.get(
    "",
    summary="Linked player and sync status",
    response_model=PlayerStatusResponse,
    response_model_exclude_unset=True,
)
def player_status() -> dict[str, Any]:
    return PLAYER_SERVICE.status()


@router.post("/link", summary="Link a Steam account")
def link_player(request: LinkRequest):
    try:
        result = PLAYER_SERVICE.link(request.steam)
    except SteamIdError as error:
        return JSONResponse(
            status_code=400, content={"status": "error", "code": error.code, "detail": str(error)}
        )
    refresh_quieter_advice()
    return result


@router.post("/link-detected", summary="Link the account currently playing (from GSI)")
def link_detected():
    detected = PLAYER_SERVICE.status().get("detected")
    if not detected:
        return JSONResponse(
            status_code=404, content={"status": "error", "code": "no_detected_account"}
        )
    result = PLAYER_SERVICE.link(str(detected["account_id"]))
    refresh_quieter_advice()
    return result


@router.delete("", summary="Forget the linked account")
def unlink_player():
    result = PLAYER_SERVICE.unlink()
    refresh_quieter_advice()
    return result


def refresh_quieter_advice() -> None:
    """Live advice the linked player mostly marks as not to the point or repeated
    waits longer (advice_feedback.quieter_decisions); at startup and on changes."""
    ADVICE_SCHEDULER.set_quieter(PLAYER_SERVICE.advice_feedback_summary().get("quieter") or [])


# Another person's profile started Dota: their feedback on live advice.
PLAYER_SERVICE.on_account_change = refresh_quieter_advice


class ProfileRequest(BaseModel):
    account_id: int = Field(gt=0)


@router.post("/profiles/switch", summary="Switch to another saved profile")
def switch_profile(request: ProfileRequest):
    try:
        result = PLAYER_SERVICE.switch_profile(request.account_id)
    except KeyError:
        return JSONResponse(status_code=404, content={"status": "error", "code": "no_profile"})
    refresh_quieter_advice()
    return result


@router.post("/profiles/remove", summary="Forget a saved profile (its history stays)")
def remove_profile(request: ProfileRequest):
    result = PLAYER_SERVICE.remove_profile(request.account_id)
    refresh_quieter_advice()
    return result


@router.post("/sync", summary="Pull profile and recent matches from OpenDota")
def sync_player():
    return {"sync": PLAYER_SERVICE.request_sync(), "opendota": PLAYER_SERVICE.client is not None}


@router.get(
    "/matches",
    summary="Match table of the linked player",
    response_model=MatchListResponse,
    response_model_exclude_unset=True,
)
def player_matches(
    limit: int = 50,
    offset: Offset = 0,
    hero_id: HeroId = None,
    result: str | None = None,
    sort: str | None = None,
    order: str | None = None,
) -> dict[str, Any]:
    """`hero_id` and `result` (win | loss) filter the table; `sort` (date | score |
    gpm | lh_10 | duration | kda) and `order` (asc | desc) order it."""
    limit = max(1, min(int(limit), 200))
    win = {"win": True, "loss": False}.get(str(result or "").lower())
    key = str(sort or "date").lower()
    return PLAYER_SERVICE.list_matches(
        limit=limit,
        offset=max(0, int(offset)),
        hero_id=hero_id,
        win=win,
        sort=key if key in MATCH_SORTS else "date",
        ascending=str(order or "").lower() == "asc",
    )


@router.post("/matches/{match_id}/add", summary="Fetch an older match by its number and review it")
def add_match(match_id: MatchId):
    """pending → poll GET; ready (stored); unlinked; offline. Errors come back
    from the poll: not_player, mode (Turbo and the like), not_found, …"""
    return PLAYER_SERVICE.add_match(match_id)


@router.get("/matches/{match_id}/add", summary="Where fetching a match by its number stands")
def add_match_status(match_id: MatchId):
    return PLAYER_SERVICE.add_status(match_id)


@router.get(
    "/matches/{match_id}",
    summary="Post-match review",
    response_model=MatchDetailResponse,
    response_model_exclude_unset=True,
    responses={404: {"model": MatchNotFoundResponse, "description": "Match is not stored"}},
)
def player_match(match_id: MatchId, lang: str = "en") -> dict[str, Any] | JSONResponse:
    detail = PLAYER_SERVICE.match_detail(match_id, normalize_lang(lang))
    if detail is None:
        return JSONResponse(status_code=404, content={"status": "error", "code": "match_not_found"})
    return detail


class NoteRequest(BaseModel):
    note: str = ""


@router.post("/matches/{match_id}/note", summary="The player's own note on a match")
def set_match_note(match_id: MatchId, request: NoteRequest):
    """Plain text, one line, 200 characters at most; empty removes it."""
    result = PLAYER_SERVICE.set_note(match_id, request.note)
    if result.get("status") == "error":
        code = result.get("code")
        return JSONResponse(status_code=404 if code == "match_not_found" else 409, content=result)
    return result


@router.post(
    "/matches/{match_id}/refresh", summary="Fetch the match again and request a replay parse"
)
def refresh_match(match_id: MatchId):
    PLAYER_SERVICE.fetch_match(match_id, request_parse=True)
    return {"status": "queued", "opendota": PLAYER_SERVICE.client is not None}


@router.get("/matches/{match_id}/share", summary="The public part of a review, to share")
def share_payload(match_id: MatchId, lang: str = "en", coach: bool = False):
    review = PLAYER_SERVICE.share_payload(match_id, normalize_lang(lang), with_coach=coach)
    if review is None:
        return JSONResponse(status_code=404, content={"status": "error", "code": "no_review"})
    return {"review": review}


@router.get("/career/share", summary="The public part of Progress, to share")
def share_progress(lang: str = "en", coach: bool = False):
    progress = PLAYER_SERVICE.share_progress_payload(normalize_lang(lang), with_coach=coach)
    if progress is None:
        return JSONResponse(status_code=404, content={"status": "error", "code": "no_progress"})
    return {"progress": progress}


@router.get("/week", summary="The last seven days for the home screen")
def player_week(
    lang: str = "en",
    until: Annotated[float | None, Query(gt=0, lt=1e11)] = None,
    since: Annotated[float | None, Query(gt=0, lt=1e11)] = None,
):
    if since is not None and (until is None or not until - 8 * 86400 <= since < until):
        return JSONResponse(status_code=422, content={"status": "error", "code": "bad_period"})
    return {"week": PLAYER_SERVICE.week(normalize_lang(lang), until, since)}


@router.get("/summary", summary="The card at the top of Home: last match, day, goals, focus")
def player_summary(lang: str = "en"):
    return {"summary": PLAYER_SERVICE.summary(normalize_lang(lang))}


@router.get("/session", summary="The games of the latest sitting («підсумок вечора»)")
def player_session(lang: str = "en"):
    return {"session": PLAYER_SERVICE.session(normalize_lang(lang))}


@router.get("/usage", summary="Advice counts of a period for the opt-in anonymous statistics")
def player_usage(
    since: Annotated[float, Query(gt=0, lt=1e11)],
    until: Annotated[float, Query(gt=0, lt=1e11)],
):
    if not until - 8 * 86400 <= since < until:
        return JSONResponse(status_code=422, content={"status": "error", "code": "bad_period"})
    return {"usage": PLAYER_SERVICE.usage(int(since), int(until))}


@router.get("/backup", summary="The whole history as one backup (no keys)")
def export_history(request: Request):
    return PLAYER_SERVICE.export_backup(str(request.app.version))


@router.post("/backup", summary="Merge a history backup (adds, never overwrites)")
def import_history(data: Annotated[dict, Body()]):
    try:
        result = PLAYER_SERVICE.import_backup(data)
    except BackupError as error:
        return JSONResponse(
            status_code=503 if error.code == "restore_failed" else 400,
            content={"status": "error", "code": error.code, "detail": str(error)},
        )
    # The backup may bring advice marks (or the linked account).
    refresh_quieter_advice()
    return result


# Automatic local copies (auto_backup.py): list, make, preview, restore.
BackupId = Annotated[
    str, Path(pattern=r"^wardly-backup-\d{8}T\d{6}Z-(weekly|update|manual)\.json\.gz$")
]


class BackupSettingsRequest(BaseModel):
    enabled: bool


def _backup_error(error: BackupError) -> JSONResponse:
    return JSONResponse(
        status_code=503 if error.code == "restore_failed" else 400,
        content={"status": "error", "code": error.code, "detail": str(error)},
    )


def _backup_missing() -> JSONResponse:
    return JSONResponse(status_code=404, content={"status": "error", "code": "backup_not_found"})


@router.get("/backups", summary="Automatic local copies of the history")
def list_backups():
    return PLAYER_SERVICE.backups_status()


@router.post("/backups", summary="Make a local copy of the history now")
def make_backup(request: Request):
    return {"ok": True, "item": PLAYER_SERVICE.make_backup(str(request.app.version))}


@router.post("/backups/auto", summary="Make the weekly or update copy when due")
def auto_backup(request: Request):
    return PLAYER_SERVICE.auto_backup(str(request.app.version))


@router.post("/backups/settings", summary="Turn automatic local copies on or off")
def backup_settings(request: BackupSettingsRequest):
    return PLAYER_SERVICE.set_backups_enabled(request.enabled)


@router.get("/backups/{backup_id}/preview", summary="What restoring a copy would add")
def preview_backup(backup_id: BackupId):
    try:
        return PLAYER_SERVICE.preview_backup_copy(backup_id)
    except KeyError:
        return _backup_missing()
    except BackupError as error:
        return _backup_error(error)


@router.post("/backups/{backup_id}/restore", summary="Merge a local copy back (adds only)")
def restore_backup(backup_id: BackupId):
    try:
        result = PLAYER_SERVICE.restore_backup_copy(backup_id)
    except KeyError:
        return _backup_missing()
    except BackupError as error:
        return _backup_error(error)
    refresh_quieter_advice()
    return result


class AdviceFeedbackRequest(BaseModel):
    key: str
    # useful | irrelevant | repeated; null clears the verdict.
    verdict: str | None = None


@router.post("/matches/{match_id}/advice-feedback", summary="Rate one live advice card")
def advice_feedback(match_id: MatchId, request: AdviceFeedbackRequest):
    result = PLAYER_SERVICE.set_advice_feedback(match_id, request.key, request.verdict)
    if result.get("status") == "error":
        status = 404 if result["code"] == "match_not_found" else 400
        return JSONResponse(status_code=status, content=result)
    refresh_quieter_advice()
    return result


@router.get("/advice-feedback", summary="Verdict counts per decision point (local)")
def advice_feedback_summary():
    return PLAYER_SERVICE.advice_feedback_summary()


class FriendRequest(BaseModel):
    steam: str


@router.get("/friend", summary="The player next to a friend (OpenDota)")
def friend_compare(lang: str = "en", group: str = "all"):
    return PLAYER_SERVICE.friend(normalize_lang(lang), group)


@router.post("/friend", summary="Compare with a friend (Steam ID, Friend ID or profile link)")
def set_friend(request: FriendRequest, lang: str = "en"):
    try:
        return PLAYER_SERVICE.set_friend(request.steam, normalize_lang(lang))
    except SteamIdError as error:
        return JSONResponse(
            status_code=400, content={"status": "error", "code": error.code, "detail": str(error)}
        )


@router.post("/friend/refresh", summary="Fetch the friend's matches again")
def refresh_friend(lang: str = "en"):
    return PLAYER_SERVICE.refresh_friend(normalize_lang(lang))


@router.delete("/friend", summary="Stop comparing with the friend")
def remove_friend():
    return PLAYER_SERVICE.remove_friend()


@router.get(
    "/career",
    summary="Statistics and advice over recent matches",
    response_model=CareerResponse,
    response_model_exclude_unset=True,
)
def player_career(lang: str = "en", hero_id: HeroId = None) -> dict[str, Any]:
    """`hero_id` narrows the progress to one hero (no AI review then)."""
    return PLAYER_SERVICE.career(normalize_lang(lang), hero_id=hero_id)


@router.post("/matches/{match_id}/ask", summary="Ask the AI coach a question about a match")
def ask_match(match_id: MatchId, request: AskRequest, lang: str = "en"):
    """Answered synchronously (up to about two minutes); the answer is fact-checked."""
    return PLAYER_SERVICE.ask_match(
        match_id, request.question, normalize_lang(lang), request_id=request.request_id
    )


@router.get("/asks/{request_id}", summary="A question's run by the launcher's request id")
def ask_status(request_id: Annotated[str, Path(pattern=ASK_REQUEST_ID_PATTERN)]):
    """unknown / running / done (with the same result the question returned)."""
    return PLAYER_SERVICE.ask_status(request_id)


class MmrRequest(BaseModel):
    mmr: int


@router.get(
    "/profile",
    response_model=ProfileResponse,
    response_model_exclude_unset=True,
    summary="The profile tab: rating graph, level, achievements, sparks",
)
def player_profile(lang: str = "en") -> dict[str, Any]:
    return {"profile": PLAYER_SERVICE.profile(normalize_lang(lang))}


@router.get("/profile/public", summary="The profile card to show friends (no account id)")
def player_profile_public(lang: str = "en", mmr: bool = True):
    profile = PLAYER_SERVICE.profile(normalize_lang(lang))
    if profile is None:
        return JSONResponse(status_code=409, content={"status": "error", "code": "not_linked"})
    return {"card": public_card(profile, normalize_lang(lang), show_mmr=mmr)}


@router.post(
    "/profile/mmr",
    response_model=ProfileResponse,
    response_model_exclude_unset=True,
    summary="The player's MMR now (an anchor of the rating graph)",
)
def set_mmr(request: MmrRequest, lang: str = "en") -> dict[str, Any] | JSONResponse:
    try:
        PLAYER_SERVICE.set_mmr(request.mmr)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"status": "error", "code": str(error)})
    return {"profile": PLAYER_SERVICE.profile(normalize_lang(lang))}


class ShopRequest(BaseModel):
    id: str


@router.post(
    "/shop/buy",
    response_model=ProfileResponse,
    response_model_exclude_unset=True,
    summary="Buy a profile look with sparks (and wear it)",
)
def shop_buy(request: ShopRequest, lang: str = "en") -> dict[str, Any] | JSONResponse:
    try:
        profile = PLAYER_SERVICE.shop_action("buy", request.id, normalize_lang(lang))
    except ValueError as error:
        return JSONResponse(status_code=400, content={"status": "error", "code": str(error)})
    return {"profile": profile}


@router.post(
    "/shop/equip",
    response_model=ProfileResponse,
    response_model_exclude_unset=True,
    summary="Wear a profile look the player owns",
)
def shop_equip(request: ShopRequest, lang: str = "en") -> dict[str, Any] | JSONResponse:
    try:
        profile = PLAYER_SERVICE.shop_action("equip", request.id, normalize_lang(lang))
    except ValueError as error:
        return JSONResponse(status_code=400, content={"status": "error", "code": str(error)})
    return {"profile": profile}


@router.delete(
    "/profile/mmr",
    response_model=ProfileResponse,
    response_model_exclude_unset=True,
    summary="Forget the typed-in MMR (back to the medal estimate)",
)
def clear_mmr(lang: str = "en") -> dict[str, Any]:
    PLAYER_SERVICE.clear_mmr()
    return {"profile": PLAYER_SERVICE.profile(normalize_lang(lang))}


@router.post("/focus", summary="Work on one recurring problem from now on")
def set_focus(request: FocusRequest, lang: str = "en"):
    try:
        PLAYER_SERVICE.set_focus(request.finding_id)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"status": "error", "code": str(error)})
    return PLAYER_SERVICE.focus_status(normalize_lang(lang))


@router.delete("/focus", summary="Stop tracking the focus problem")
def clear_focus():
    PLAYER_SERVICE.clear_focus()
    return {"status": "ok"}


@router.post("/matches/{match_id}/coach", summary="(Re)generate the AI coach review of a match")
def coach_match(match_id: MatchId, lang: str = "en"):
    detail = PLAYER_SERVICE.match_detail(match_id, normalize_lang(lang), force_coach=True)
    if detail is None:
        return JSONResponse(status_code=404, content={"status": "error", "code": "match_not_found"})
    return detail["coach"]


@router.post("/career/ask", summary="Ask the AI coach a question about the recent matches")
def ask_career(request: AskRequest, lang: str = "en"):
    return PLAYER_SERVICE.ask_career(
        request.question, normalize_lang(lang), request_id=request.request_id
    )


@router.post("/career/coach", summary="(Re)generate the AI coach review of recent matches")
def coach_career(lang: str = "en"):
    return PLAYER_SERVICE.career(normalize_lang(lang), force_coach=True).get("coach")


@router.get("/opendota", summary="OpenDota key status (the key is never returned)")
def opendota_settings():
    return PLAYER_SERVICE.opendota_status()


@router.post("/opendota", summary="Save an OpenDota API key")
def set_opendota_settings(request: OpenDotaKeyRequest):
    try:
        return PLAYER_SERVICE.set_opendota_key(request.api_key)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"status": "error", "code": "bad_opendota_key"}
        )


@router.delete("/opendota", summary="Forget the OpenDota API key")
def clear_opendota_settings():
    return PLAYER_SERVICE.clear_opendota_key()


@router.get("/ai", summary="AI coach settings (the key is never returned)")
def ai_settings():
    return PLAYER_SERVICE.ai_status()


@router.post("/ai", summary="Save the AI coach provider and key")
def set_ai_settings(request: AIRequest):
    try:
        return PLAYER_SERVICE.set_ai(request.provider, request.api_key, request.model)
    except ValueError:
        return JSONResponse(status_code=400, content={"status": "error", "code": "bad_ai_settings"})


@router.delete("/ai", summary="Forget the AI coach key")
def clear_ai_settings():
    return PLAYER_SERVICE.clear_ai()


@router.post("/ai/check", summary="Validate the AI coach key with one small request")
def check_ai_settings():
    return PLAYER_SERVICE.check_ai()
