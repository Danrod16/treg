"""A quoted price says what it is per; `usd_per_call` is only ever what one call costs."""

import pytest

from treg.domain.catalog import store


@pytest.mark.parametrize('raw,price,per,per_call', [
    ({'type': 'per_call', 'value': 0.09, 'currency': 'USD', 'unit': 'call'}, '$0.09/call', 'call', 0.09),
    ({'type': 'per_result', 'value': 5.0, 'currency': 'USD', 'per': 1000, 'unit': 'row'}, '$0.005/row', 'row', None),
    ({'type': 'per_result', 'value': 0.0005, 'currency': 'USD', 'unit': 'keyword'}, '$0.0005/keyword', 'keyword', None),
    ({'type': 'per_result', 'value': 2, 'currency': 'USD', 'display': {'unit': 'result', 'variable': True}},
     '$2+/result', 'result', None),
    ({'type': 'per_call', 'value': 0.002, 'currency': 'USD', 'unit': 'call',
      'display': {'unit': 'call', 'variable': True}}, '$0.002+/call', 'call', None),
    ({'type': 'per_call', 'value': 0.064, 'currency': 'USD', 'display': {'unit': 'call', 'maximum': True}},
     'up to $0.064/call', 'call', 0.064),
    ({'type': 'per_result', 'value': 0.00012, 'currency': 'USD', 'unit': 'row'}, '$0.00012/row', 'row', None),
    ({'type': 'per_result', 'value': 1, 'currency': 'USD', 'unit': 'call'}, '$1/call', 'call', 1),
    ({'type': 'free', 'value': 0, 'currency': 'USD', 'unit': 'call'}, 'free', 'call', 0),
])
def test_price_terms(raw, price, per, per_call):
    cat = store.load()
    terms = cat.price_terms(cat.cost_view(raw, 'any-provider'))
    assert (terms['price'], terms['billed_per'], terms['usd_per_call']) == (price, per, per_call)


def test_an_observed_charge_is_a_floor_not_a_flat_price():
    """What the verification request cost is not what a 600-keyword request costs."""
    cat = store.load()
    cost = cat.cost_view(store._effective_cost({'observed_cost': 0.01236, 'verified': '2026-07-28'}), 'dataforseo')
    assert cat.price_terms(cost) == {'price': '$0.0124+/call', 'price_usd': 0.01236,
                                     'billed_per': 'call', 'usd_per_call': None}


async def test_mcp_catalog_get_quotes_a_per_result_price_per_result(clients):
    from test_mcp import _call_tool, mcp_session
    token = clients.headers['X-Treg-Token']
    async with mcp_session(clients) as c:
        out = await _call_tool(c, 'catalog_get', {'endpoint_id': 'moz.web.backlinks.intersect'}, token=token)
    assert out['usd_per_call'] is None
    assert out['billed_per'] == 'result' and out['price'].endswith('+/result')
    assert out['price_usd'] == out['endpoint']['cost']['usd']
