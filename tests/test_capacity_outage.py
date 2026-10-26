"""The breaker's `outage` kind: an endpoint that keeps giving treg's key no answer (a timeout, a
transport error, a 5xx) with no 2xx in between is skipped by routed plans until it answers again.
It never refuses a direct call, and a team's own key neither strikes it nor is steered by it."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlmodel import select

from treg import ratestore
from treg.application.call import route as call_route
from treg.application.call import service as call_service
from treg.application.call.types import CallFailure, UpstreamResponse
from treg.domain.capacity import marks as capacity_marks
from treg.domain.capacity.marks import LOCK_NS, OUTAGE_LOCK, OUTAGE_MAX_LOCK, Lock, lock_key
from treg.domain.capacity.view import view as capacity_view
from treg.infra.db import session_maker
from treg.models import Hold
from treg.timeutil import utcnow_naive

from test_marketplace_call import EP, _balance, _fake_relay, platform_on  # noqa: F401
from test_routing import ROUTED, enrichment_on  # noqa: F401

TOMBA = "tomba.people.email.find"
ASK = {"full_name": "Patrick Collison", "domain": "stripe.com"}
FINDYMAIL_HIT = {"contact": {"name": "Patrick Collison", "email": "patrick@stripe.com"}}


@pytest.fixture(autouse=True)
def _strikes_seconds_apart(monkeypatch):
    monkeypatch.setattr(capacity_marks, "STRIKE_MIN_GAP", timedelta(0))


async def _row(key: str) -> Lock | None:
    async with session_maker() as db:
        raw = await ratestore.kv_get(db, LOCK_NS, key)
    return Lock.from_json(raw) if raw else None


def _vendors(tomba, seen: list):
    """tomba gives `tomba` (an exception to raise, or a status); findymail always finds."""
    async def relay(request, upstream_url, tool, secrets, client, drop_params=None, force_identity=False):
        vendor = "tomba" if "tomba" in upstream_url else "findymail"
        seen.append(vendor)
        if vendor == "tomba" and isinstance(tomba, Exception):
            raise tomba
        status, doc = (tomba, {"error": "down"}) if vendor == "tomba" else (200, FINDYMAIL_HIT)
        payload = json.dumps(doc).encode()

        async def _s():
            yield payload

        async def _c():
            return None
        return UpstreamResponse(status, ((b"content-type", b"application/json"),), _s(), _c)
    return relay


async def test_a_routed_child_that_keeps_timing_out_is_skipped_until_it_answers(
        clients: AsyncClient, enrichment_on, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(call_service, "relay", _vendors(httpx.ReadTimeout("timed out"), seen))
    before = await _balance(clients)
    for _ in range(capacity_marks.OUTAGE_STRIKES):
        r = await clients.post(f"/call/{ROUTED}", json=ASK)
        assert r.status_code == 200, r.text
        assert [t["outcome"] for t in r.json()["_treg"]["tried"]] == ["error", "hit"]
    assert seen == ["tomba", "findymail"] * capacity_marks.OUTAGE_STRIKES
    assert (await _row(lock_key("tomba", TOMBA, "outage"))).is_active()
    assert await _row("tomba") is None and await _row(TOMBA) is None, "an outage is not a dry account"

    seen.clear()
    r = await clients.post(f"/call/{ROUTED}", json=ASK)
    assert r.status_code == 200, r.text
    d = r.json()["_treg"]
    assert seen == ["findymail"], "the failing child is not asked again"
    assert [t["endpoint_id"] for t in d["tried"]] == ["findymail.search.name"]
    assert {"endpoint_id": TOMBA, "why": call_route.OUTAGE_WHY} in d["dropped"]
    async with session_maker() as db:
        assert (await db.execute(select(Hold))).scalars().all() == [], "every hold closed"
    assert before - await _balance(clients) == 19_800 * (capacity_marks.OUTAGE_STRIKES + 1), \
        "only findymail's hits were charged"

    # The vendor recovers: a direct call is relayed through the lock and its 2xx clears it.
    monkeypatch.setattr(call_service, "relay", _fake_relay(200, json.dumps(
        {"data": {"email": "patrick@stripe.com", "score": 99}}).encode()))
    r = await clients.get(f"/call/{TOMBA}", params=ASK)
    assert r.status_code == 200, r.text
    assert await _row(lock_key("tomba", TOMBA, "outage")) is None
    await capacity_view.load()
    assert not capacity_view.is_down("tomba", TOMBA)


async def test_a_5xx_streak_locks_and_a_2xx_between_resets_it(clients: AsyncClient, platform_on, monkeypatch):
    key = lock_key("tikhub", EP, "outage")
    for status in (502, 500):
        monkeypatch.setattr(call_service, "relay", _fake_relay(status, b"down"))
        assert (await clients.get(f"/call/{EP}?aweme_id=7")).status_code == status
    assert (await _row(key)).strikes == 2 and not (await _row(key)).is_active()
    monkeypatch.setattr(call_service, "relay", _fake_relay(200, b'{"ok":true}'))
    assert (await clients.get(f"/call/{EP}?aweme_id=7")).status_code == 200
    assert await _row(key) is None, "a 2xx in between is an answer"
    for status in (503, 504, 500):
        monkeypatch.setattr(call_service, "relay", _fake_relay(status, b"down"))
        assert (await clients.get(f"/call/{EP}?aweme_id=7")).status_code == status
    lock = await _row(key)
    assert lock.is_active() and lock.until - utcnow_naive() <= OUTAGE_LOCK
    # A direct call is never refused for an outage: the caller asked for this endpoint.
    monkeypatch.setattr(call_service, "relay", _fake_relay(503, b"still down"))
    assert (await clients.get(f"/call/{EP}?aweme_id=7")).status_code == 503
    assert (await _row(key)).lock_id == lock.lock_id, "a strike on an open lock changes nothing"


async def test_a_501_and_a_4xx_are_no_outage(clients: AsyncClient, platform_on, monkeypatch):
    for status in (501, 400, 404, 501):
        monkeypatch.setattr(call_service, "relay", _fake_relay(status, b'{"detail":"no"}'))
        assert (await clients.get(f"/call/{EP}?aweme_id=7")).status_code == status
    assert await _row(lock_key("tikhub", EP, "outage")) is None


async def test_own_key_timeouts_never_strike_treg_key(clients: AsyncClient, platform_on, monkeypatch):
    await clients.post("/secrets", json={"name": "tikhub", "value": "MKKEY"})
    monkeypatch.setattr(call_service, "relay", _fake_relay(200, raises=httpx.ConnectError("refused")))
    for _ in range(capacity_marks.OUTAGE_STRIKES + 1):
        assert (await clients.get(f"/call/{EP}?aweme_id=7")).status_code == 502
    assert await _row(lock_key("tikhub", EP, "outage")) is None


async def test_own_key_child_is_never_skipped_for_treg_key_outage(
        clients: AsyncClient, enrichment_on, monkeypatch):
    for offset in (30, 20, 10):
        await capacity_marks.strike("tomba", endpoint_id=TOMBA, kind="outage", resets_at=None,
                                    now=utcnow_naive() - timedelta(seconds=offset))
    capacity_view.invalidate()
    await clients.post("/secrets", json={"name": "tomba", "value": "OWN-TOMBA"})
    seen: list[str] = []
    monkeypatch.setattr(call_service, "relay", _vendors(200, seen))
    r = await clients.post(f"/call/{ROUTED}", json=ASK)
    assert r.status_code == 200, r.text
    d = r.json()["_treg"]
    assert not any(x["endpoint_id"] == TOMBA for x in d.get("dropped", []))
    assert seen[0] == "tomba", "the team's own key is first, whatever treg's key is going through"


async def test_a_pool_timeout_is_treg_own_and_no_outage():
    def failure(cause: Exception) -> CallFailure:
        exc = CallFailure("connect_failed", status_code=502, detail="x")
        exc.__cause__ = cause
        return exc
    assert call_service._no_answer(failure(httpx.ReadTimeout("t")))
    assert call_service._no_answer(failure(httpx.ConnectError("c")))
    assert call_service._no_answer(failure(httpx.RemoteProtocolError("r")))
    assert not call_service._no_answer(failure(httpx.PoolTimeout("p")))
    assert not call_service._no_answer(failure(httpx.UnsupportedProtocol("u")))
    assert not call_service._no_answer(CallFailure("connect_failed", status_code=502, detail="no cause"))


async def test_an_expired_uncleared_outage_relocks_at_once_for_twice_as_long(clients: AsyncClient, platform_on):
    t0 = utcnow_naive() - timedelta(hours=3)
    kw = dict(endpoint_id=EP, kind="outage", resets_at=None)
    for s in range(capacity_marks.OUTAGE_STRIKES):
        lock = await capacity_marks.strike("tikhub", now=t0 + timedelta(seconds=20 * s), **kw)
    assert lock.is_active(lock.opened_at) and lock.until - lock.opened_at == OUTAGE_LOCK
    holds = []
    now = lock.until
    for _ in range(4):
        now += timedelta(minutes=1)  # the first call the expiry let through fails again
        lock = await capacity_marks.strike("tikhub", now=now, **kw)
        assert lock.opened and lock.is_active(now), "no 2xx since: one strike reopens it"
        holds.append(lock.until - lock.opened_at)
        now = lock.until
    assert holds == [2 * OUTAGE_LOCK, 4 * OUTAGE_LOCK, OUTAGE_MAX_LOCK, OUTAGE_MAX_LOCK]
    late = await capacity_marks.strike("tikhub", now=now + capacity_marks.STRIKE_WINDOW
                                       + timedelta(minutes=1), **kw)
    assert not late.is_active(now + capacity_marks.STRIKE_WINDOW + timedelta(minutes=1)), \
        "long after the expiry it is a new ladder"


async def test_a_direct_call_through_an_outage_lock_is_relayed(
        clients: AsyncClient, platform_on, monkeypatch):
    for offset in (30, 20, 10):
        await capacity_marks.strike("tikhub", endpoint_id=EP, kind="outage", resets_at=None,
                                    now=utcnow_naive() - timedelta(seconds=offset))
    capacity_view.invalidate()
    monkeypatch.setattr(call_service, "relay", _fake_relay(200, raises=httpx.ReadTimeout("t")))
    assert (await clients.get(f"/call/{EP}?aweme_id=7")).status_code == 502, "relayed, not refused"
    key = lock_key("tikhub", EP, "outage")
    assert (await _row(key)).is_active()


async def test_the_routed_quote_says_the_router_skips_a_child_in_an_outage(
        clients: AsyncClient, enrichment_on):
    for offset in (30, 20, 10):
        await capacity_marks.strike("tomba", endpoint_id=TOMBA, kind="outage", resets_at=None,
                                    now=utcnow_naive() - timedelta(seconds=offset))
    capacity_view.invalidate()
    plan = (await clients.get(f"/catalog/endpoints/{ROUTED}")).json()["routing"]["plan"]
    tomba = next(c for c in plan if c["endpoint_id"] == TOMBA)
    assert tomba["skipped"] == call_route.OUTAGE_WHY
    assert plan[-1]["endpoint_id"] == TOMBA or plan[-1].get("skipped")
