"""Unit tests for tier1 tab-probing logic in check_service.py, specifically
the `accepted_status_codes` per-tab allowlist that treats a configured non-2xx
status code (e.g. a 403 from an SSO/oauth-proxy login page) as a successful
probe rather than a failure.

Uses httpx.MockTransport (no real network), following the pattern in
test_check_service_qa.py: tests grouped in classes per function under test,
with docstrings recording *why* a behaviour is expected.
"""

import httpx

from soundcheck.services import check_service as cs

BASE_URL = "https://showroom-abc12.apps.example.com"


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# _normalise_accepted_status_codes
# ---------------------------------------------------------------------------


class TestNormaliseAcceptedStatusCodes:
    def test_valid_list_of_ints(self) -> None:
        assert cs._normalise_accepted_status_codes([401, 403]) == frozenset({401, 403})

    def test_mixed_valid_and_invalid_entries_drops_invalid(self) -> None:
        assert cs._normalise_accepted_status_codes([403, "not-a-number", None, 401]) == frozenset({403, 401})

    def test_string_digit_entries_are_coerced(self) -> None:
        assert cs._normalise_accepted_status_codes(["403"]) == frozenset({403})

    def test_out_of_range_codes_are_dropped(self) -> None:
        assert cs._normalise_accepted_status_codes([403, 50, 9999]) == frozenset({403})

    def test_non_list_input_returns_empty_frozenset(self) -> None:
        assert cs._normalise_accepted_status_codes("403") == frozenset()
        assert cs._normalise_accepted_status_codes(None) == frozenset()
        assert cs._normalise_accepted_status_codes(403) == frozenset()

    def test_empty_list_returns_empty_frozenset(self) -> None:
        assert cs._normalise_accepted_status_codes([]) == frozenset()


# ---------------------------------------------------------------------------
# _probe_url with accepted_status_codes
# ---------------------------------------------------------------------------


class TestProbeUrlAcceptedStatusCodes:
    async def test_403_without_accepted_codes_is_unreachable(self) -> None:
        """Baseline: a 403 with no allowlist configured is a normal failure,
        confirming the new behaviour is opt-in only."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        async with make_client(handler) as client:
            result = await cs._probe_url(client, BASE_URL + "/grafana")

        assert result["reachable"] is False
        assert result["status_code"] == 403
        assert "status_accepted" not in result

    async def test_403_with_matching_accepted_codes_is_reachable(self) -> None:
        """A 403 from an SSO/oauth-proxy login page proves the endpoint is
        live and routed -- when explicitly allowlisted via the tab's
        accepted_status_codes, it must count as a successful probe."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        async with make_client(handler) as client:
            result = await cs._probe_url(client, BASE_URL + "/grafana", accepted_status_codes=frozenset({403}))

        assert result["reachable"] is True
        assert result["status_code"] == 403
        assert result["status_accepted"] is True

    async def test_accepted_status_on_head_short_circuits_without_get(self) -> None:
        """An accepted status returned on the HEAD attempt must return
        immediately -- no follow-up GET request should be made."""
        request_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            assert request.method == "HEAD"
            return httpx.Response(403)

        async with make_client(handler) as client:
            result = await cs._probe_url(client, BASE_URL + "/grafana", accepted_status_codes=frozenset({403}))

        assert result["reachable"] is True
        assert request_count == 1

    async def test_non_accepted_status_still_fails_when_allowlist_set(self) -> None:
        """Configuring accepted_status_codes for one code must not accidentally
        widen tolerance to other, unrelated error codes."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        async with make_client(handler) as client:
            result = await cs._probe_url(client, BASE_URL + "/grafana", accepted_status_codes=frozenset({403}))

        assert result["reachable"] is False

    async def test_iframe_headers_still_checked_on_accepted_status(self) -> None:
        """iframe-blocking detection is orthogonal to reachability and must
        still run even when the status code was only reachable because it
        was explicitly accepted."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, headers={"X-Frame-Options": "DENY"})

        async with make_client(handler) as client:
            result = await cs._probe_url(client, BASE_URL + "/grafana", accepted_status_codes=frozenset({403}))

        assert result["reachable"] is True
        assert result["iframe_blocked"] is True


# ---------------------------------------------------------------------------
# _resolve_tab_urls with accepted_status_codes
# ---------------------------------------------------------------------------


class TestResolveTabUrlsAcceptedStatusCodes:
    def test_tab_with_accepted_status_codes_carries_normalised_set(self) -> None:
        tab = {
            "name": "Grafana",
            "url": "https://grafana.example.com",
            "accepted_status_codes": [403],
        }
        entries = cs._resolve_tab_urls(tab, BASE_URL)
        assert len(entries) == 1
        label, url, state, is_placeholder, accepted_codes = entries[0]
        assert label == "Grafana"
        assert accepted_codes == frozenset({403})

    def test_tab_without_accepted_status_codes_gets_empty_set(self) -> None:
        tab = {"name": "OCP Console", "url": "https://console.example.com"}
        entries = cs._resolve_tab_urls(tab, BASE_URL)
        assert len(entries) == 1
        _, _, _, _, accepted_codes = entries[0]
        assert accepted_codes == frozenset()

    def test_secondary_url_inherits_same_accepted_status_codes(self) -> None:
        tab = {
            "name": "Double Terminal",
            "type": "double-terminal",
            "secondary_name": "bottom",
            "secondary_url": "https://terminal-2.example.com",
            "url": "https://terminal-1.example.com",
            "accepted_status_codes": [401],
        }
        entries = cs._resolve_tab_urls(tab, BASE_URL)
        assert len(entries) == 2
        for _, _, _, _, accepted_codes in entries:
            assert accepted_codes == frozenset({401})
