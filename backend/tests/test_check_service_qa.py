"""Unit tests for the qa-automation healthcheck probe in check_service.py.

Uses httpx.MockTransport (no real network, no extra test dependency beyond
the already-required httpx + pytest-asyncio) to simulate the runtime-
automation sidecar's /api/config and /stream/qa/{stage} endpoints.
"""

import asyncio
import json

import httpx
import pytest

from soundcheck.services import check_service as cs

BASE_URL = "https://showroom-abc12.apps.example.com"


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def sse_body(lines: list[str], *, done: bool = True) -> bytes:
    """Build an SSE body matching zerotouch-automation's api/stream.py format."""
    body = b""
    for line in lines:
        body += f"data: {json.dumps(line)}\n\n".encode()
    if done:
        body += b"data: __DONE__\n\n"
    return body


# ---------------------------------------------------------------------------
# _fetch_qa_config
# ---------------------------------------------------------------------------


class TestFetchQaConfig:
    async def test_returns_qa_stages_when_present_at_runner_prefix(self) -> None:
        """/runner/api/config is the real reachable path on live showrooms
        (nginx fronts the runtime-automation sidecar's /api/* routes there,
        same as nookbag's own frontend fetches from) -- confirmed against a
        live showroom where plain /api/config 404'd."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/runner/api/config"
            return httpx.Response(200, json={"qa": ["healthcheck", "e2e"], "module-01": ["setup"]})

        async with make_client(handler) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == ["healthcheck", "e2e"]

    async def test_falls_back_to_unprefixed_path_when_runner_prefix_404s(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/runner/api/config":
                return httpx.Response(404)
            assert request.url.path == "/api/config"
            return httpx.Response(200, json={"qa": ["healthcheck"]})

        async with make_client(handler) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == ["healthcheck"]

    async def test_404_on_both_paths_returns_empty_list(self) -> None:
        async with make_client(lambda r: httpx.Response(404)) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == []

    async def test_non_404_error_on_first_path_does_not_try_fallback(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/runner/api/config"
            return httpx.Response(503)

        async with make_client(handler) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == []

    async def test_no_qa_key_returns_empty_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"module-01": ["setup", "solve"]})

        async with make_client(handler) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == []

    async def test_malformed_json_returns_empty_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        async with make_client(handler) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == []

    async def test_non_dict_json_returns_empty_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["qa", "healthcheck"])

        async with make_client(handler) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == []

    async def test_connection_error_on_both_paths_returns_empty_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        async with make_client(handler) as client:
            stages = await cs._fetch_qa_config(client, BASE_URL)
        assert stages == []


# ---------------------------------------------------------------------------
# _cap_qa_log_lines
# ---------------------------------------------------------------------------


class TestCapQaLogLines:
    def test_under_limit_returned_unchanged(self) -> None:
        lines = ["line one", "line two", "line three"]
        assert cs._cap_qa_log_lines(lines) == lines

    def test_over_limit_truncates_from_front_keeps_tail(self) -> None:
        lines = [f"line-{i}" * 50 for i in range(2000)]
        capped = cs._cap_qa_log_lines(lines)
        assert capped[0] == "... (log truncated) ..."
        assert capped[-1] == lines[-1]
        assert len(capped) < len(lines)


# ---------------------------------------------------------------------------
# check_qa_healthcheck (the full available + stream flow)
# ---------------------------------------------------------------------------


class TestCheckQaHealthcheck:
    async def test_unavailable_when_healthcheck_stage_missing(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/runner/api/config":
                return httpx.Response(200, json={"qa": ["e2e"]})
            raise AssertionError("should not call the stream endpoint when unavailable")

        async with make_client(handler) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL)

        assert result.available is False
        assert result.status is None
        assert result.log == ""

    async def test_unavailable_when_config_endpoint_missing(self) -> None:
        async with make_client(lambda r: httpx.Response(404)) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL)
        assert result.available is False

    async def test_passed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/runner/api/config":
                return httpx.Response(200, json={"qa": ["healthcheck"]})
            assert request.url.path == "/stream/qa/healthcheck"
            body = sse_body(
                [
                    "PLAY [Healthcheck] ***",
                    "TASK [debug] ***",
                    "ok: [localhost]",
                    "\n✓ Completed successfully!\n",
                ]
            )
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

        async with make_client(handler) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL, timeout=5)

        assert result.available is True
        assert result.status == "passed"
        assert "Completed successfully" in result.log
        assert result.error_message is None
        assert result.started_at is not None
        assert result.completed_at is not None

    async def test_failed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/runner/api/config":
                return httpx.Response(200, json={"qa": ["healthcheck"]})
            body = sse_body(
                [
                    "TASK [assert healthy] ***",
                    "fatal: [localhost]: FAILED!",
                    "\n✗ Failed (exit code 2)\n",
                ]
            )
            return httpx.Response(200, content=body)

        async with make_client(handler) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL, timeout=5)

        assert result.available is True
        assert result.status == "failed"
        assert "Failed (exit code 2)" in result.log

    async def test_unknown_when_no_marker_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/runner/api/config":
                return httpx.Response(200, json={"qa": ["healthcheck"]})
            return httpx.Response(200, content=sse_body(["some output", "more output"]))

        async with make_client(handler) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL, timeout=5)

        assert result.available is True
        assert result.status == "unknown"

    async def test_non_200_stream_response_is_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/runner/api/config":
                return httpx.Response(200, json={"qa": ["healthcheck"]})
            return httpx.Response(503, content=b"")

        async with make_client(handler) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL, timeout=5)

        assert result.available is True
        assert result.status == "error"
        assert "503" in result.error_message

    async def test_stream_transport_error_is_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/runner/api/config":
                return httpx.Response(200, json={"qa": ["healthcheck"]})
            raise httpx.ConnectError("connection refused")

        async with make_client(handler) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL, timeout=5)

        assert result.available is True
        assert result.status == "error"

    async def test_wall_clock_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """asyncio.wait_for must fire even if bytes keep trickling in (httpx's
        own per-chunk read timeout would never trigger in that case)."""

        async def slow_consume(client: httpx.AsyncClient, url: str) -> tuple[list[str], str | None]:
            await asyncio.sleep(10)
            return [], None

        monkeypatch.setattr(cs, "_consume_qa_stream", slow_consume)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"qa": ["healthcheck"]})

        async with make_client(handler) as client:
            result = await cs.check_qa_healthcheck(client, BASE_URL, timeout=0.05)

        assert result.available is True
        assert result.status == "timeout"


# ---------------------------------------------------------------------------
# _apply_qa_healthcheck (merging into TargetCheckResult)
# ---------------------------------------------------------------------------


class TestApplyQaHealthcheck:
    def test_unavailable_does_not_modify_result(self) -> None:
        result = cs.TargetCheckResult(url=BASE_URL, is_healthy=True, detail={"tabs": []})
        qa = cs.QaHealthcheckResult(available=False)

        cs._apply_qa_healthcheck(result, qa)

        assert result.is_healthy is True
        assert "qa_healthcheck" not in (result.detail or {})

    def test_passed_keeps_healthy_true_and_adds_detail(self) -> None:
        result = cs.TargetCheckResult(url=BASE_URL, is_healthy=True, detail={"tabs": []})
        qa = cs.QaHealthcheckResult(available=True, status="passed", log="all good")

        cs._apply_qa_healthcheck(result, qa)

        assert result.is_healthy is True
        assert result.detail["qa_healthcheck"]["available"] is True
        assert result.detail["qa_healthcheck"]["status"] == "passed"
        assert result.detail["qa_healthcheck"]["log"] == "all good"
        assert result.error_message is None

    def test_failed_marks_result_unhealthy_and_appends_error(self) -> None:
        result = cs.TargetCheckResult(url=BASE_URL, is_healthy=True, detail=None)
        qa = cs.QaHealthcheckResult(available=True, status="failed", error_message="exit code 2")

        cs._apply_qa_healthcheck(result, qa)

        assert result.is_healthy is False
        assert "QA healthcheck failed" in result.error_message
        assert result.detail["qa_healthcheck"]["status"] == "failed"

    def test_failed_appends_to_existing_error_message(self) -> None:
        result = cs.TargetCheckResult(
            url=BASE_URL,
            is_healthy=False,
            error_message="Tab 'Terminal' unreachable",
            detail={},
        )
        qa = cs.QaHealthcheckResult(available=True, status="timeout", error_message="timed out after 90s")

        cs._apply_qa_healthcheck(result, qa)

        assert result.error_message == "Tab 'Terminal' unreachable; QA healthcheck timeout: timed out after 90s"
