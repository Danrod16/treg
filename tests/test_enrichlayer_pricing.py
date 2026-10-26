"""Request bounds and response evidence for Enrichlayer's shared-key result prices."""

import json

import httpx

from treg import api as A
from treg.application.call import enrichlayer
from treg.application.call.resolve import QueryValues, _marketplace_pricing
from treg.config import get_settings
from treg.domain.catalog import store as catalog_store


def test_search_premium_hold_and_returned_result_settlement():
    endpoint = "enrichlayer.people.search"
    cost = {"value": 3, "enrichlayer": {
        "field": "results", "max_page": 10,
        "extra_per_result": {"enrich_profiles": {"enrich": 1}, "use_cache": {"if-recent": 2}},
    }}
    query = {"page_size": "2", "enrich_profiles": "enrich", "use_cache": "if-recent"}
    assert enrichlayer.invalid_platform_parameter(endpoint, query, cost) is None
    hold, unit = enrichlayer.estimate_micro(endpoint, cost, query, 100000)
    assert (hold, unit) == (1200000, 600000)
    assert enrichlayer.observed_micro(cost["enrichlayer"], unit, {"results": [{}]}, hold) == 600000
    assert enrichlayer.observed_micro(cost["enrichlayer"], unit, {"results": []}, hold) == 0
    assert enrichlayer.observed_micro(cost["enrichlayer"], unit, {}, hold) is None
    assert enrichlayer.observed_micro(cost["enrichlayer"], unit, {"results": [{}, {}, {}]}, hold) is None


def test_shared_key_rejects_unbounded_or_unpriced_requests():
    search = {"value": 3, "enrichlayer": {"field": "results", "max_page": 10}}
    endpoint = "enrichlayer.people.search"
    for page in ("0", "11", "1" * 5000):
        assert enrichlayer.invalid_platform_parameter(endpoint, {"page_size": page}, search) == "page_size"
    assert enrichlayer.invalid_platform_parameter(
        endpoint, {"page_size": "11", "use_cache": "if-recent"}, search) == "page_size"
    profile = "enrichlayer.company.profile"
    assert enrichlayer.invalid_platform_parameter(profile, {}, {}) == "use_cache"
    assert enrichlayer.invalid_platform_parameter(profile, {"use_cache": "if-present"}, {}) is None
    employees = "enrichlayer.company.employees.list"
    employee_cost = {"value": 3, "enrichlayer": {"field": "employees", "max_page": 10}}
    assert enrichlayer.invalid_platform_parameter(
        employees, {"page_size": "1", "country": "US"}, employee_cost) == "country"
    phone = "enrichlayer.contacts.personal-phone"
    phone_cost = {"value": 1, "enrichlayer": {"field": "numbers", "max_page": 10}}
    assert enrichlayer.invalid_platform_parameter(phone, {}, phone_cost) == "page_size"
    assert enrichlayer.invalid_platform_parameter(phone, {"page_size": "11"}, phone_cost) == "page_size"
    assert enrichlayer.invalid_platform_parameter(employees, {"page_size": "11"}, employee_cost) == "page_size"


def test_personal_email_precise_counts_valid_and_invalid_found_addresses():
    endpoint = "enrichlayer.contacts.personal-email"
    cost = {"value": 1, "enrichlayer": {"field": "emails", "max_page": 10,
                                        "extra_per_result": {"email_validation": {"precise": 1}}}}
    query = {"page_size": "2", "email_validation": "precise"}
    hold, unit = enrichlayer.estimate_micro(endpoint, cost, query, 100000)
    assert (hold, unit) == (400000, 200000)
    assert enrichlayer.observed_micro(cost["enrichlayer"], unit, {
        "emails": ["valid@example.com"], "invalid_emails": ["invalid@example.com"]}, hold) == 400000


def test_public_price_preview_accepts_routed_query_dict():
    cat = catalog_store.load()
    ep = cat.by_id["enrichlayer.people.search"]
    cost = cat.cost_view(ep["cost"], ep["provider"])
    query = {"page_size": "10", "enrich_profiles": "skip", "use_cache": "if-present"}
    expected = (3_000_000, 300_000)
    assert _marketplace_pricing(ep["provider"], ep["id"], cost, query, b"{}") == expected
    assert _marketplace_pricing(ep["provider"], ep["id"], cost,
                                QueryValues(tuple(query.items())), b"{}") == expected


async def _balance(clients) -> int:
    org_id = (await clients.get("/orgs")).json()[0]["org_id"]
    return (await clients.get(f"/orgs/{org_id}/balance")).json()["balance_micro"]


async def test_reverse_phone_without_a_profile_is_free_and_a_found_profile_pays(clients, monkeypatch):
    monkeypatch.setenv("TREG_PLATFORM_KEY_ENRICHLAYER", "PLATFORM-ENRICHLAYER")
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "enrichlayer")
    get_settings.cache_clear()
    answer = {"linkedin_profile_url": None, "twitter_profile_url": None, "facebook_profile_url": None}

    class _Body(httpx.AsyncByteStream):
        def __init__(self, doc):
            self.body = json.dumps(doc).encode()

        async def __aiter__(self):
            yield self.body

    def serve(request):
        assert request.url.path == "/api/v2/resolve/phone"
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=_Body(answer))

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as upstream:
            monkeypatch.setattr(A.app.state, "http", upstream)
            before = await _balance(clients)
            miss = await clients.get("/call/enrichlayer.contacts.reverse-phone",
                                     params={"phone_number": "+15550100000"})
            assert miss.status_code == 200, miss.text
            assert miss.headers["x-treg-cost-micro"] == "0"
            assert await _balance(clients) == before

            answer["twitter_profile_url"] = "https://x.example/someone"
            hit = await clients.get("/call/enrichlayer.contacts.reverse-phone",
                                    params={"phone_number": "+15550100001"})
            assert hit.status_code == 200, hit.text
            assert hit.headers["x-treg-cost-micro"] == "300000"
            assert before - await _balance(clients) == 300_000
    finally:
        get_settings.cache_clear()
