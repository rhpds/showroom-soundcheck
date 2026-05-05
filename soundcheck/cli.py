"""CLI for showroom health checks.

Standalone entry point that uses check_service for two-tier health checks.
No dependency on Reflex, Postgres, or Babylon.

Usage:
    showroom-soundcheck --urls https://showroom1.example.com,https://showroom2.example.com
    showroom-soundcheck --urls https://showroom1.example.com --check-type healthz
    showroom-soundcheck --urls https://showroom1.example.com -v
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Optional

from .check_service import TargetCheckResult, check_targets
from .utils import extract_guid_from_url


def _extract_guid(url: str) -> str:
    return extract_guid_from_url(url) or "-"


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return parsed


def _env_concurrency_default() -> int:
    raw = os.environ.get("CHECK_CONCURRENCY", "10")
    try:
        return _positive_int(raw)
    except argparse.ArgumentTypeError:
        return 10


def _try_import_rich() -> tuple[Optional[Any], Optional[Any], Optional[Any]]:
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.live import Live
        return Console, Table, Live
    except ImportError:
        return None, None, None


async def _run_checks(
    urls: list[str],
    check_type: str,
    check_mode: str,
    verbose: bool,
    verify_ssl: bool,
    concurrency: int,
) -> list[TargetCheckResult]:
    Console, Table, Live = _try_import_rich()

    if Console and Table and Live:
        return await _run_with_rich(urls, check_type, check_mode, verbose, verify_ssl, concurrency, Console, Table, Live)
    return await _run_plain(urls, check_type, check_mode, verbose, verify_ssl, concurrency)


async def _run_with_rich(
    urls: list[str],
    check_type: str,
    check_mode: str,
    verbose: bool,
    verify_ssl: bool,
    concurrency: int,
    Console: Any,
    Table: Any,
    Live: Any,
) -> list[TargetCheckResult]:
    console = Console()
    status_map: dict[str, str] = {u: "[yellow]pending[/]" for u in urls}
    results_map: dict[str, TargetCheckResult] = {}

    def build_table() -> Any:
        table = Table(title="Showroom Health Checks", show_lines=True)
        table.add_column("URL", style="cyan", no_wrap=True)
        table.add_column("GUID", style="magenta")
        table.add_column("Status", justify="center")
        table.add_column("Tier", justify="center")
        table.add_column("Time", justify="right")
        table.add_column("Error", style="red", max_width=40)

        for url in urls:
            guid = _extract_guid(url)
            r = results_map.get(url)
            if r:
                if r.is_healthy:
                    status = "[green]healthy[/]"
                elif r.error_message:
                    status = "[red]error[/]"
                else:
                    status = "[yellow]unhealthy[/]"
                tier = str(r.tier_used) if r.tier_used else "-"
                time_str = f"{r.response_time_ms}ms" if r.response_time_ms else "-"
                error = (r.error_message or "")[:80]
            else:
                status = status_map.get(url, "[yellow]pending[/]")
                tier = "-"
                time_str = "-"
                error = ""
            table.add_row(url, guid, status, tier, time_str, error)
        return table

    async def on_progress(url: str, status: str, result: Optional[TargetCheckResult]) -> None:
        if status == "checking":
            status_map[url] = "[blue]checking...[/]"
        elif status == "done" and result:
            results_map[url] = result
        live.update(build_table())

    with Live(build_table(), console=console, refresh_per_second=4) as live:
        results = await check_targets(
            urls, check_type, check_mode=check_mode, concurrency=concurrency,
            verify_ssl=verify_ssl, on_progress=on_progress,
        )
        live.update(build_table())

    if verbose:
        console.print()
        for r in results:
            if r.detail:
                console.print(f"\n[bold]{r.url}[/] — Tier {r.tier_used} detail:")
                console.print_json(json.dumps(r.detail, default=str, indent=2))

    return results


async def _run_plain(
    urls: list[str],
    check_type: str,
    check_mode: str,
    verbose: bool,
    verify_ssl: bool,
    concurrency: int,
) -> list[TargetCheckResult]:
    print(f"Checking {len(urls)} showroom(s) ({check_type})...")

    async def on_progress(url: str, status: str, result: Optional[TargetCheckResult]) -> None:
        if status == "checking":
            print(f"  checking {url}...")
        elif status == "done" and result:
            guid = _extract_guid(url)
            mark = "OK" if result.is_healthy else "FAIL"
            tier = f"tier {result.tier_used}" if result.tier_used else ""
            time_str = f"{result.response_time_ms}ms" if result.response_time_ms else ""
            parts = [f"  [{mark}]", url, f"({guid})", tier, time_str]
            if result.error_message:
                parts.append(f"- {result.error_message[:80]}")
            print(" ".join(p for p in parts if p))

    results = await check_targets(
        urls, check_type, check_mode=check_mode, concurrency=concurrency,
        verify_ssl=verify_ssl, on_progress=on_progress,
    )

    print(f"\nSummary: {sum(1 for r in results if r.is_healthy)}/{len(results)} healthy")

    if verbose:
        for r in results:
            if r.detail:
                print(f"\n{r.url} — Tier {r.tier_used} detail:")
                print(json.dumps(r.detail, default=str, indent=2))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="showroom-soundcheck",
        description="Check health/readiness of showroom environments",
    )
    parser.add_argument(
        "--urls",
        required=True,
        help="Comma-separated list of showroom URLs to check",
    )
    parser.add_argument(
        "--check-type",
        choices=["readyz", "healthz"],
        default="readyz",
        help="Check type: readyz (full readiness) or healthz (liveness). Default: readyz",
    )
    parser.add_argument(
        "--check-mode",
        choices=["manual", "showroom", "auto"],
        default="manual",
        help="Check mode: manual (local checks only), showroom (delegate to sidecar first). Default: manual",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=_positive_int,
        default=_env_concurrency_default(),
        help="Max concurrent checks (env: CHECK_CONCURRENCY, default: 10)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=os.environ.get("VERIFY_SSL", "true").lower() not in ("true", "1", "yes"),
        help="Disable SSL certificate verification (env: VERIFY_SSL, default: verify)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed Tier 2 check results",
    )
    args = parser.parse_args()

    urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    if not urls:
        print("Error: no URLs provided", file=sys.stderr)
        sys.exit(2)

    for url in urls:
        if not (url.startswith("http://") or url.startswith("https://")):
            print(f"Error: invalid URL (must start with http:// or https://): {url}", file=sys.stderr)
            sys.exit(2)

    verify_ssl = not args.insecure
    results = asyncio.run(_run_checks(
        urls, args.check_type, args.check_mode, args.verbose, verify_ssl, args.concurrency,
    ))

    all_healthy = all(r.is_healthy for r in results)
    sys.exit(0 if all_healthy else 1)


if __name__ == "__main__":
    main()
