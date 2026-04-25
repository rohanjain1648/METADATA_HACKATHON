"""
DataGuardian — Manual Integration Test Script
=============================================
Exercises all 11 MCP tools directly (no MCP protocol overhead).
Requires a running OpenMetadata instance and valid .env credentials.

Usage:
    cd dataguardian
    python test_tools.py                        # run all tests
    python test_tools.py --tool search_sensitive
    python test_tools.py --tool classify_table --fqn "sample_data.ecommerce_db.shopify.customers"
    python test_tools.py --dry-run              # skip any write operations
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

load_dotenv()

console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(name: str, result: dict, elapsed: float) -> None:
    status = result.get("status", "")
    error = result.get("error", "")
    if error:
        console.print(f"  [yellow]⚠[/yellow]  {name} ({elapsed:.2f}s) — partial: {error}")
    else:
        console.print(f"  [green]✓[/green]  {name} ({elapsed:.2f}s)")


def _fail(name: str, exc: Exception, elapsed: float) -> None:
    console.print(f"  [red]✗[/red]  {name} ({elapsed:.2f}s) — {type(exc).__name__}: {exc}")


def _print_result(result: Any, indent: int = 2) -> None:
    """Pretty-print a result dict, truncating long lists."""
    if isinstance(result, dict):
        for k, v in result.items():
            if isinstance(v, list) and len(v) > 3:
                console.print(f"{'  ' * indent}[dim]{k}[/dim]: [{len(v)} items — showing first 3]")
                for item in v[:3]:
                    console.print(f"{'  ' * (indent + 1)}{item}")
            elif isinstance(v, dict):
                console.print(f"{'  ' * indent}[dim]{k}[/dim]:")
                _print_result(v, indent + 1)
            else:
                console.print(f"{'  ' * indent}[dim]{k}[/dim]: {v}")
    else:
        console.print(f"{'  ' * indent}{result}")


async def run_tool(name: str, coro) -> tuple[bool, Any]:
    """Run a single tool coroutine, return (success, result)."""
    t0 = time.perf_counter()
    try:
        result = await coro
        elapsed = time.perf_counter() - t0
        _ok(name, result if isinstance(result, dict) else {}, elapsed)
        return True, result
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        _fail(name, exc, elapsed)
        return False, None


# ---------------------------------------------------------------------------
# Individual tool tests
# ---------------------------------------------------------------------------

async def test_search_sensitive(verbose: bool = False) -> bool:
    from dataguardian.tools.search_sensitive import search_sensitive_assets

    ok, result = await run_tool(
        "search_sensitive(tag=PII, entity_type=all, limit=10)",
        search_sensitive_assets(tag="PII", entity_type="all", limit=10),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_breach_impact(fqn: str, verbose: bool = False) -> bool:
    from dataguardian.tools.breach_impact import get_breach_impact_graph

    ok, result = await run_tool(
        f"breach_impact(fqn={fqn}, direction=downstream, depth=3)",
        get_breach_impact_graph(fqn=fqn, direction="downstream", depth=3),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_classify_table(fqn: str, dry_run: bool = True, verbose: bool = False) -> bool:
    from dataguardian.tools.auto_classify import auto_classify_table

    ok, result = await run_tool(
        f"classify_table(fqn={fqn}, dry_run={dry_run})",
        auto_classify_table(table_fqn=fqn, dry_run=dry_run),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_compliance_report(regulation: str = "GDPR", verbose: bool = False) -> bool:
    from dataguardian.tools.compliance_report import generate_compliance_report

    ok, result = await run_tool(
        f"compliance_report(regulation={regulation}, output_format=json)",
        generate_compliance_report(regulation=regulation, domain=None, output_format="json"),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_orphaned_assets(verbose: bool = False) -> bool:
    from dataguardian.tools.orphan_finder import find_orphaned_sensitive_assets

    ok, result = await run_tool(
        "orphaned_sensitive_assets(check_quality=True, check_lineage=True)",
        find_orphaned_sensitive_assets(check_quality=True, check_lineage=True),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_data_access_chain(fqn: str, verbose: bool = False) -> bool:
    from dataguardian.tools.access_chain import get_data_access_chain

    ok, result = await run_tool(
        f"data_access_chain(fqn={fqn})",
        get_data_access_chain(table_fqn=fqn),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_bulk_classify(dry_run: bool = True, verbose: bool = False) -> bool:
    from dataguardian.tools.bulk_classify import bulk_classify_tables

    ok, result = await run_tool(
        f"bulk_classify(dry_run={dry_run}, limit=5)",
        bulk_classify_tables(dry_run=dry_run, limit=5),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_retention_checker(regulation: str = "GDPR", verbose: bool = False) -> bool:
    from dataguardian.tools.retention_checker import check_retention_policies

    ok, result = await run_tool(
        f"retention_checker(regulation={regulation})",
        check_retention_policies(regulation=regulation, domain=None),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_linkage_detector(verbose: bool = False) -> bool:
    from dataguardian.tools.linkage_detector import detect_pii_linkage

    ok, result = await run_tool(
        "linkage_detector(min_shared_columns=2)",
        detect_pii_linkage(domain=None, min_shared_columns=2),
    )
    if ok and verbose:
        _print_result(result)
    return ok


async def test_drift_monitor(fqn: str, verbose: bool = False) -> bool:
    from dataguardian.tools.drift_monitor import monitor_tag_drift

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        snapshot_path = f.name

    try:
        # First run — creates baseline snapshot
        ok1, result1 = await run_tool(
            f"drift_monitor — baseline snapshot for {fqn}",
            monitor_tag_drift(table_fqn=fqn, snapshot_path=snapshot_path),
        )
        if not ok1:
            return False

        # Second run — compares against snapshot
        ok2, result2 = await run_tool(
            f"drift_monitor — compare against snapshot for {fqn}",
            monitor_tag_drift(table_fqn=fqn, snapshot_path=snapshot_path),
        )
        if ok2 and verbose:
            _print_result(result2)
        return ok2
    finally:
        try:
            os.unlink(snapshot_path)
        except OSError:
            pass


async def test_incident_playbook(fqn: str, verbose: bool = False) -> bool:
    from dataguardian.tools.playbook_generator import generate_incident_playbook

    ok, result = await run_tool(
        f"incident_playbook(fqn={fqn}, regulation=GDPR)",
        generate_incident_playbook(
            table_fqn=fqn,
            regulation="GDPR",
            incident_description="Suspected unauthorised access detected in audit logs.",
        ),
    )
    if ok and verbose:
        _print_result(result)
    return ok


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

TOOL_MAP = {
    "search_sensitive": test_search_sensitive,
    "breach_impact": test_breach_impact,
    "classify_table": test_classify_table,
    "compliance_report": test_compliance_report,
    "orphaned_assets": test_orphaned_assets,
    "data_access_chain": test_data_access_chain,
    "bulk_classify": test_bulk_classify,
    "retention_checker": test_retention_checker,
    "linkage_detector": test_linkage_detector,
    "drift_monitor": test_drift_monitor,
    "incident_playbook": test_incident_playbook,
}


async def main(args: argparse.Namespace) -> int:
    # Validate env
    missing = [v for v in ("OPENMETADATA_HOST", "OPENMETADATA_JWT_TOKEN") if not os.environ.get(v)]
    if missing:
        console.print(f"[red]Missing required env vars: {', '.join(missing)}[/red]")
        console.print("Copy .env.example → .env and fill in your credentials.")
        return 1

    # Init OM client
    from dataguardian import om_client
    om_client.init()

    fqn = args.fqn  # used by tools that need a table FQN
    dry_run = args.dry_run
    verbose = args.verbose

    console.print(Panel.fit(
        f"[bold]DataGuardian Tool Test[/bold]\n"
        f"Host: {os.environ['OPENMETADATA_HOST']}\n"
        f"FQN:  {fqn}\n"
        f"Dry-run: {dry_run}",
        border_style="blue",
    ))

    results: dict[str, bool] = {}

    # Determine which tools to run
    if args.tool:
        if args.tool not in TOOL_MAP:
            console.print(f"[red]Unknown tool: {args.tool}. Choose from: {', '.join(TOOL_MAP)}[/red]")
            return 1
        tools_to_run = [args.tool]
    else:
        tools_to_run = list(TOOL_MAP.keys())

    console.print()

    for tool_name in tools_to_run:
        console.rule(f"[bold]{tool_name}[/bold]", style="dim")

        fn = TOOL_MAP[tool_name]

        # Tools that need a FQN
        if tool_name in ("breach_impact", "classify_table", "data_access_chain",
                         "drift_monitor", "incident_playbook"):
            results[tool_name] = await fn(fqn=fqn, verbose=verbose)

        # Tools with dry_run
        elif tool_name in ("bulk_classify",):
            results[tool_name] = await fn(dry_run=dry_run, verbose=verbose)

        elif tool_name == "classify_table":
            results[tool_name] = await fn(fqn=fqn, dry_run=dry_run, verbose=verbose)

        else:
            results[tool_name] = await fn(verbose=verbose)

    # Summary table
    console.print()
    table = Table(title="Test Summary", box=box.ROUNDED, show_header=True)
    table.add_column("Tool", style="bold")
    table.add_column("Result", justify="center")

    passed = sum(1 for v in results.values() if v)
    failed = len(results) - passed

    for tool_name, ok in results.items():
        table.add_row(tool_name, "[green]PASS[/green]" if ok else "[red]FAIL[/red]")

    console.print(table)
    console.print(
        f"\n[bold]{'[green]All passed' if failed == 0 else f'[red]{failed} failed'}[/bold] "
        f"({passed}/{len(results)})\n"
    )

    await om_client.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DataGuardian integration test script")
    parser.add_argument(
        "--tool",
        choices=list(TOOL_MAP.keys()),
        help="Run a single tool instead of all",
    )
    parser.add_argument(
        "--fqn",
        default="sample_data.ecommerce_db.shopify.customers",
        help="Table FQN to use for tools that require one (default: sample_data.ecommerce_db.shopify.customers)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Skip write operations (default: True)",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Enable write operations (tags will be written to OpenMetadata)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print full tool output",
    )

    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))
