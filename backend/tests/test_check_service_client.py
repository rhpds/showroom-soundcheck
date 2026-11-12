"""Unit tests for check_service.create_client, specifically the default
User-Agent header it sends.

Some external targets probed by soundcheck (notably docs.redhat.com, fronted
by an Akamai WAF) return a 403 "Access Denied" page for requests whose
User-Agent is httpx's default ("python-httpx/x.y.z"), a generic browser
string, or missing entirely -- but let a curl-style UA through. Confirmed
live and reproducible across repeated requests (see PR discussion). This
test only asserts the client is configured to send that UA; it does not
make real network calls.
"""

from soundcheck.services import check_service as cs


class TestCreateClientUserAgent:
    def test_default_user_agent_is_curl_style(self) -> None:
        """DEFAULT_USER_AGENT must start with a curl-style `curl/<version>`
        token -- that's specifically what gets past the docs.redhat.com edge
        WAF; a generic browser or httpx-default string does not."""
        assert cs.DEFAULT_USER_AGENT.startswith("curl/")

    async def test_client_sends_default_user_agent_header(self) -> None:
        async with cs.create_client() as client:
            assert client.headers["user-agent"] == cs.DEFAULT_USER_AGENT

    async def test_client_user_agent_not_overridden_by_timeout_or_verify_args(self) -> None:
        async with cs.create_client(timeout=5, verify_ssl=False) as client:
            assert client.headers["user-agent"] == cs.DEFAULT_USER_AGENT
