"""Tokfluence listing: every catalogued endpoint is priced in credits that fx.yaml converts to USD,
so the file is platform-eligible end to end."""
from treg import oauth_providers as P
from treg.domain.catalog import store as cs


def test_tokfluence_is_a_registered_key_provider():
    p = P.REGISTRY["tokfluence"]
    assert p.auth_kind == "key"
    assert p.token_header == "Authorization" and p.token_format == "Bearer {secret}"
    assert p.probe_path == "/v1/lists"


def test_tokfluence_catalog_is_platform_priced():
    c = cs.load()
    eps = [ep for ep in c.by_id.values() if ep.get("provider") == "tokfluence"]
    assert 8 <= len(eps) <= 15
    for ep in eps:
        assert c.platform_eligible(ep), ep["id"]
