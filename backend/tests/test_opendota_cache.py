"""Shared OpenDota cache: reference data is read from Wardly's server first and
from OpenDota when the cache has nothing fresh. No network: a fake session."""

from __future__ import annotations

import importlib.util
import time

import pytest
import requests

from app import config
from app.opendota import (
    CACHE_MAX_AGE_SECONDS,
    CACHE_TIMEOUT_SECONDS,
    OpenDotaClient,
    OpenDotaError,
)

CACHE = "https://cache.example/v1/opendota"
OPENDOTA = "https://od.example/api"
KEY = "00000000-aaaa-bbbb-cccc-1234567890ab"


def _now_ms(age_seconds: float = 0) -> str:
    return str(int((time.time() - age_seconds) * 1000))


class _Response:
    def __init__(self, status=200, body=None, headers=None, bad_json=False):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._body


class _Session:
    """Answers by host: cache calls and OpenDota calls are recorded apart."""

    def __init__(self, cache=None, opendota=None):
        self.cache = cache  # a _Response, an Exception or None (= 404)
        self.opendota = opendota
        self.calls: list[dict] = []

    def request(self, method, url, params=None, timeout=None, **kwargs):
        self.calls.append(
            {"url": url, "params": dict(params or []), "timeout": timeout, "kwargs": kwargs}
        )
        answer = self.cache if url.startswith(CACHE) else self.opendota
        if isinstance(answer, Exception):
            raise answer
        return answer or _Response(404)

    def cache_calls(self):
        return [c for c in self.calls if c["url"].startswith(CACHE)]

    def opendota_calls(self):
        return [c for c in self.calls if c["url"].startswith(OPENDOTA)]


def _client(session, *, cache_url=CACHE, api_key=""):
    return OpenDotaClient(
        OPENDOTA, api_key=api_key, session=session, min_interval=0, cache_url=cache_url
    )


ITEMS = {"blink": {"id": 1, "dname": "Blink Dagger", "cost": 2250}}
STATS = [{"id": 1, "roles": ["Carry"], "1_pick": 5, "1_win": 2}]
MATCHUPS = [{"hero_id": 2, "games_played": 10, "wins": 6}]
POPULARITY = {"start_game_items": {"44": 3}}
TIMINGS = [{"item": "blink", "time": 900, "games": 10, "wins": 6}]


def test_fresh_cache_hit_does_not_call_opendota():
    session = _Session(cache=_Response(body=ITEMS, headers={"x-fetched-at": _now_ms(3600)}))
    items = _client(session).item_constants()
    assert items["items"]["blink"]["name"] == "Blink Dagger"
    assert session.opendota_calls() == []
    call = session.cache_calls()[0]
    assert call["url"] == f"{CACHE}/constants/items"
    assert call["timeout"] == CACHE_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("call", "path", "params", "body"),
    [
        (lambda c: c.item_constants(), "/constants/items", {}, ITEMS),
        (lambda c: c.hero_stats(), "/heroStats", {}, STATS),
        (lambda c: c.item_popularity(7), "/heroes/7/itemPopularity", {}, POPULARITY),
        (lambda c: c.hero_matchups(7), "/heroes/7/matchups", {}, MATCHUPS),
        (lambda c: c.item_timings(7), "/scenarios/itemTimings", {"hero_id": 7}, TIMINGS),
    ],
)
def test_five_reference_endpoints_use_the_cache_with_only_path_and_hero(call, path, params, body):
    session = _Session(cache=_Response(body=body, headers={"x-fetched-at": _now_ms()}))
    call(_client(session, api_key=KEY))
    assert session.opendota_calls() == []
    (cache_call,) = session.cache_calls()
    assert cache_call["url"] == f"{CACHE}{path}"
    assert cache_call["params"] == params
    assert cache_call["kwargs"] == {"allow_redirects": False}


def test_cache_and_opendota_give_the_same_shaping():
    fresh = {"x-fetched-at": _now_ms()}
    cached = _client(_Session(cache=_Response(body=MATCHUPS, headers=fresh))).hero_matchups(1)
    direct = _client(_Session(opendota=_Response(body=MATCHUPS)), cache_url="").hero_matchups(1)
    assert cached == direct == {"2": [10, 6]}


def test_stale_cache_goes_to_opendota():
    stale = _Response(body=[], headers={"x-fetched-at": _now_ms(CACHE_MAX_AGE_SECONDS + 60)})
    session = _Session(cache=stale, opendota=_Response(body=MATCHUPS))
    assert _client(session).hero_matchups(1) == {"2": [10, 6]}
    assert len(session.opendota_calls()) == 1


@pytest.mark.parametrize(
    "cache",
    [
        None,  # 404 not_cached
        _Response(503, {"ok": False}),
        _Response(bad_json=True, headers={"x-fetched-at": "1"}),
        _Response(body={"not": "a list"}, headers={"x-fetched-at": "9999999999999"}),
        _Response(body=MATCHUPS),  # no x-fetched-at: age unknown
        _Response(body=MATCHUPS, headers={"x-fetched-at": "soon"}),
        requests.ConnectionError("down"),
        requests.Timeout("slow"),
    ],
)
def test_unusable_cache_goes_to_opendota(cache):
    session = _Session(cache=cache, opendota=_Response(body=MATCHUPS))
    assert _client(session).hero_matchups(1) == {"2": [10, 6]}
    assert len(session.cache_calls()) == 1  # no retries on the cache
    assert len(session.opendota_calls()) == 1


def test_both_down_uses_the_stale_body():
    stale = _Response(body=MATCHUPS, headers={"x-fetched-at": _now_ms(30 * 24 * 3600)})
    session = _Session(cache=stale, opendota=requests.ConnectionError("offline"))
    assert _client(session).hero_matchups(1) == {"2": [10, 6]}


def test_opendota_error_codes_also_fall_back_to_the_stale_body():
    stale = _Response(body=STATS, headers={"x-fetched-at": _now_ms(10 * 24 * 3600)})
    session = _Session(cache=stale, opendota=_Response(429))
    assert _client(session).hero_stats()[0]["hero_id"] == 1


def test_both_down_without_a_body_raises_as_before():
    session = _Session(cache=requests.ConnectionError("down"), opendota=_Response(429))
    with pytest.raises(OpenDotaError) as error:
        _client(session).hero_matchups(1)
    assert error.value.code == "rate_limited"
    session = _Session(cache=None, opendota=requests.ConnectionError("offline"))
    with pytest.raises(OpenDotaError) as error:
        _client(session).hero_stats()
    assert error.value.code == "offline"


def test_cache_disabled_never_asks_it():
    session = _Session(cache=_Response(body=MATCHUPS), opendota=_Response(body=MATCHUPS))
    _client(session, cache_url="").hero_matchups(1)
    assert session.cache_calls() == []
    # The default of the client itself is off, so code and tests that build one are unaffected.
    plain = _Session(opendota=_Response(body=MATCHUPS))
    OpenDotaClient(OPENDOTA, session=plain, min_interval=0).hero_matchups(1)
    assert plain.cache_calls() == []


def test_api_key_is_never_sent_to_the_cache():
    session = _Session(
        cache=_Response(body=[], headers={"x-fetched-at": _now_ms(CACHE_MAX_AGE_SECONDS + 5)}),
        opendota=_Response(body=MATCHUPS),
    )
    client = _client(session, api_key=KEY)
    client.hero_matchups(1)
    client.set_api_key("11111111-aaaa-bbbb-cccc-1234567890ab")
    client.item_timings(1)
    assert session.cache_calls()
    for call in session.cache_calls():
        assert "api_key" not in call["params"]
        assert KEY not in call["url"] and "1234567890ab" not in call["url"]
    assert all("api_key" in call["params"] for call in session.opendota_calls())


def test_player_and_match_endpoints_never_use_the_cache():
    class _Any(_Session):
        def request(self, method, url, params=None, timeout=None, **kwargs):
            if url.startswith(CACHE):
                raise AssertionError("the cache was asked for player data")
            return _Response(body={"profile": {"personaname": "Me"}, "rank_tier": 54})

    client = _client(_Any())
    client.player(1)
    client._get("/players/1/matches")
    client._get("/matches/1")


def test_pro_skill_orders_stay_direct():
    class _Direct(_Session):
        def request(self, method, url, params=None, timeout=None, **kwargs):
            if url.startswith(CACHE):
                raise AssertionError("pro_skill_orders must not use the cache")
            return _Response(body=[])

    with pytest.raises(OpenDotaError):
        _client(_Direct()).pro_skill_orders(1)


def test_errors_never_carry_the_key():
    session = _Session(
        cache=requests.ConnectionError(f"{CACHE}/x?api_key={KEY}"),
        opendota=requests.ConnectionError(f"{OPENDOTA}/x?api_key={KEY}"),
    )
    with pytest.raises(OpenDotaError) as error:
        _client(session, api_key=KEY).hero_stats()
    assert KEY not in str(error.value)


def _cache_url_from_config(monkeypatch, value):
    """Runs config.py as a throwaway module so the real app.config stays as it is."""
    if value is None:
        monkeypatch.delenv("WARDLY_OPENDOTA_CACHE_URL", raising=False)
    else:
        monkeypatch.setenv("WARDLY_OPENDOTA_CACHE_URL", value)
    spec = importlib.util.spec_from_file_location("config_probe", config.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OPENDOTA_CACHE_URL


def test_config_default_override_and_empty(monkeypatch):
    assert _cache_url_from_config(monkeypatch, None) == "https://api.luhovyimvp.dev/v1/opendota"
    assert (
        _cache_url_from_config(monkeypatch, " https://other.example/v1/opendota/ ")
        == "https://other.example/v1/opendota"
    )
    assert _cache_url_from_config(monkeypatch, "") == ""


def test_tests_run_without_a_client_so_the_real_cache_is_never_reached():
    from app.player_api import PLAYER_SERVICE

    assert PLAYER_SERVICE.client is None
