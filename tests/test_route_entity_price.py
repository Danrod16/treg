"""A routed child priced per keyword is quoted and ranked at the keywords the request names."""

import pytest

from treg.config import get_settings
from treg.domain.catalog import store as catalog_store

from test_marketplace_call import platform_on  # noqa: F401

VOLUME = 'treg.google.keywords.volume'
PER_KEYWORD = 'seranking.google.keywords.volume'
FLAT = 'dataforseo.google.keywords.volume'


@pytest.fixture
def volume_on(monkeypatch, platform_on):
    monkeypatch.setenv('TREG_PLATFORM_KEY_DATAFORSEO', 'login:password')
    monkeypatch.setenv('TREG_PLATFORM_KEY_SERANKING', 'PLATFORM-SERANKING')
    monkeypatch.setenv('TREG_PLATFORM_PROVIDERS', 'dataforseo,seranking')
    get_settings.cache_clear()


async def _plan(clients, body):
    """The ranked plan, read from the unbilled refusal a ceiling below every candidate answers."""
    r = await clients.post('/call/' + VOLUME, json=body, headers={'X-Treg-Route-Max-Cost': '0.000001'})
    assert r.status_code == 402, r.text
    return [(c['endpoint_id'], c['price_micro']) for c in r.json()['detail']['plan']]


@pytest.mark.parametrize('count,first', [(8, PER_KEYWORD), (60, FLAT)])
async def test_a_per_keyword_child_is_priced_at_the_list_it_is_asked(clients, volume_on, count, first):
    cat = catalog_store.load()
    ep = cat.by_id[PER_KEYWORD]
    per_keyword = cat.cost_view(ep['cost'], ep['provider'])['usd']
    plan = await _plan(clients, {'keywords': [f'k{i}' for i in range(count)], 'country': 'gb'})
    assert dict(plan)[PER_KEYWORD] == round(per_keyword * count * 1_000_000)
    assert plan[0][0] == first


async def test_the_quote_names_the_unit_and_the_filters_a_child_ignores(clients, volume_on):
    r = await clients.get('/catalog/endpoints/' + VOLUME)
    assert r.status_code == 200, r.text
    rows = {row['endpoint_id']: row for row in r.json()['routing']['plan']}
    assert rows[PER_KEYWORD]['per'] == 'keyword' and rows[PER_KEYWORD]['ignores'] == ['language']
    assert 'per' not in rows[FLAT] and 'ignores' not in rows[FLAT]
