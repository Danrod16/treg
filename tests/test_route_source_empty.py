"""A provider's statement that the source itself had nothing ends a routed waterfall."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from treg.application.call import service
from treg.config import get_settings
from treg.domain.catalog import store as catalog_store

from test_marketplace_call import _balance, platform_on  # noqa: F401
from test_routing import _relay_by_provider

FIRST = 'crawl4ai.google.serp.organic'


def _example(eid):
    root = Path(catalog_store.__file__).parents[2] / 'catalog' / 'examples'
    return json.loads((root / f'{eid}.json').read_text())


def _empty(reason):
    doc = _example(FIRST)
    doc.update(results=[], blocks=[], total_results=0, empty_reason=reason)
    return doc


@pytest.fixture
def serp_on(monkeypatch, platform_on):
    monkeypatch.setenv('TREG_PLATFORM_KEY_CRAWL4AI', 'PLATFORM-CRAWL4AI')
    monkeypatch.setenv('TREG_PLATFORM_KEY_ANYAPI', 'PLATFORM-ANYAPI')
    monkeypatch.setenv('TREG_PLATFORM_PROVIDERS', 'crawl4ai,anyapi')
    get_settings.cache_clear()
    adapters = catalog_store.load().adapters
    monkeypatch.setitem(adapters, FIRST, replace(adapters[FIRST], empty="empty_reason == 'google_no_results'"))


@pytest.mark.parametrize('reason,asked,outcome', [
    ('google_no_results', ['crawl4ai'], 'miss'),
    ('rescue_no_results', ['crawl4ai', 'anyapi'], 'hit'),
])
async def test_a_declared_empty_source_stops_the_waterfall(clients, serp_on, monkeypatch, reason, asked, outcome):
    seen = []
    monkeypatch.setattr(service, 'relay', _relay_by_provider({
        'crawl4ai': [(200, _empty(reason))],
        'anyapi': [(200, _example('anyapi.google.serp.organic'))],
    }, seen))
    before = await _balance(clients)
    response = await clients.post('/call/treg.google.serp.organic', json={'q': 'site:example.com nothing'},
                                  headers={'X-Treg-Route-Prefer': 'crawl4ai,anyapi'})
    assert response.status_code == 200, response.text
    assert [p for p, *_ in seen] == asked
    meta = response.json()['_treg']
    assert meta['outcome'] == outcome
    if outcome == 'miss':
        assert meta['served_by'] == FIRST
        assert meta['tried'][0]['detail'] == 'the source has no result'
        assert response.json()['raw']['empty_reason'] == 'google_no_results'
    assert before - await _balance(clients) == meta['charged_micro']
