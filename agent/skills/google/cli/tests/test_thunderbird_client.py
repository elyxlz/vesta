"""Tests for the dynamic Thunderbird Google client resolver (Part 4).

Covers the OAuth2Providers parser and the cache/fetch/fallback resolution logic.
No network: the fetcher is always injected. The cache dir is isolated per-test via
GOOGLE_DATA_DIR so nothing touches the real ~/.google.
"""

import pytest

from google_cli import thunderbird_client as tc

# A representative slice of comm-central's OAuth2Providers.sys.mjs, including the
# prettier line-wrap on the long clientId value.
SAMPLE = """
var kIssuers = new Map([
  [
    "accounts.google.com",
    {
      name: "accounts.google.com",
      builtIn: true,
      clientId:
        "406964657835-aq8lmia8j95dhl1a2bvharmfk3t1hgqj.apps.googleusercontent.com",
      clientSecret: "kSmqreRr0qwBWJgbf5Y-PjSU",
      issuerIdentifier: "https://accounts.google.com",
    },
  ],
  [
    "login.microsoftonline.com",
    {
      name: "login.microsoftonline.com",
      clientId: "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
    },
  ],
]);
"""

REAL_ID = "406964657835-aq8lmia8j95dhl1a2bvharmfk3t1hgqj.apps.googleusercontent.com"
REAL_SECRET = "kSmqreRr0qwBWJgbf5Y-PjSU"

FALLBACK_ID = "fallback-000.apps.googleusercontent.com"
FALLBACK_SECRET = "fallback-secret"


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_DATA_DIR", str(tmp_path))
    return tmp_path


# -- parser ---------------------------------------------------------


def test_parse_extracts_google_client_across_line_wrap():
    assert tc.parse_google_client(SAMPLE) == (REAL_ID, REAL_SECRET)


def test_parse_ignores_other_issuer_blocks():
    cid, _ = tc.parse_google_client(SAMPLE)
    assert cid.endswith(".apps.googleusercontent.com")
    assert cid != "9e5f94bc-e8a4-4e73-b8be-63364c29d753"


def test_parse_returns_none_when_block_absent():
    assert tc.parse_google_client("var kIssuers = new Map([]);") is None


def test_parse_rejects_non_google_client_id():
    bad = SAMPLE.replace(REAL_ID, "not-a-google-client")
    assert tc.parse_google_client(bad) is None


# -- resolver: fetch / cache / fallback -----------------------------


def _fetcher(client_id, secret):
    def f(url=None, timeout=None):
        return client_id, secret

    return f


def _failing_fetcher(url=None, timeout=None):
    raise RuntimeError("network down")


def test_resolve_fetches_and_caches_when_no_cache():
    res = tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_fetcher(REAL_ID, REAL_SECRET), now=1000.0)
    assert res["source"] == "fetched"
    assert res["client_id"] == REAL_ID
    assert tc.cache_path().exists()


def test_resolve_uses_fresh_cache_without_fetching():
    tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_fetcher(REAL_ID, REAL_SECRET), now=1000.0)

    def boom(url=None, timeout=None):
        raise AssertionError("must not fetch when cache is fresh")

    res = tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=boom, now=1000.0 + 3600)
    assert res["source"] == "cache"
    assert res["client_id"] == REAL_ID


def test_resolve_refetches_when_cache_stale():
    tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_fetcher(REAL_ID, REAL_SECRET), now=0.0)
    later = 8 * 86400  # older than the 7-day threshold
    res = tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_fetcher("new-999.apps.googleusercontent.com", "s2"), now=later)
    assert res["source"] == "fetched"
    assert res["client_id"] == "new-999.apps.googleusercontent.com"


def test_resolve_force_refresh_ignores_fresh_cache():
    tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_fetcher(REAL_ID, REAL_SECRET), now=1000.0)
    res = tc.resolve_google_client(
        FALLBACK_ID,
        FALLBACK_SECRET,
        fetcher=_fetcher("rotated.apps.googleusercontent.com", "s3"),
        now=1000.0 + 60,
        force_refresh=True,
    )
    assert res["source"] == "fetched"
    assert res["client_id"] == "rotated.apps.googleusercontent.com"


def test_resolve_falls_back_to_hardcoded_when_no_cache_and_fetch_fails():
    res = tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_failing_fetcher, now=1000.0)
    assert res["source"] == "fallback"
    assert res["client_id"] == FALLBACK_ID
    assert res["client_secret"] == FALLBACK_SECRET


def test_resolve_cache_only_never_fetches():
    res = tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, allow_fetch=False, now=1000.0)
    assert res["source"] == "fallback"


def test_resolve_prefers_stale_cache_over_hardcoded_when_fetch_fails():
    tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_fetcher(REAL_ID, REAL_SECRET), now=0.0)
    res = tc.resolve_google_client(FALLBACK_ID, FALLBACK_SECRET, fetcher=_failing_fetcher, now=8 * 86400)
    assert res["source"] == "cache-stale"
    assert res["client_id"] == REAL_ID


# -- resolve_thunderbird_client convenience wrapper -----------------


def test_resolve_thunderbird_client_returns_hardcoded_when_no_cache():
    # Cache-only, no cache yet -> hardcoded Thunderbird constants (the floor).
    cid, secret = tc.resolve_thunderbird_client()
    assert cid == tc.THUNDERBIRD_GOOGLE_CLIENT_ID
    assert secret == tc.THUNDERBIRD_GOOGLE_CLIENT_SECRET


def test_resolve_thunderbird_client_env_pin(monkeypatch):
    monkeypatch.setenv("GOOGLE_NO_DYNAMIC_CLIENT", "1")
    cid, secret = tc.resolve_thunderbird_client()
    assert cid == tc.THUNDERBIRD_GOOGLE_CLIENT_ID
    assert secret == tc.THUNDERBIRD_GOOGLE_CLIENT_SECRET
