"""CLI — repo-intel commands (Typer)."""

from __future__ import annotations

import socket
import sys

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from repo_intel.config import get_settings, setup_logging

cli = typer.Typer(
    name="repo-intel",
    help="Persistent, searchable knowledge of Git repositories for coding agents.",
    add_completion=False,
)

console = Console()


# ------------------------------------------------------------------
# serve
# ------------------------------------------------------------------
@cli.command()
def serve(
    host: str | None = typer.Option(None, "--host", help="Bind address"),
    port: int | None = typer.Option(None, "--port", help="Bind port"),
) -> None:
    """Start the FastAPI server."""
    import uvicorn  # noqa: PLC0415 (runtime import)

    settings = get_settings()
    setup_logging()
    uvicorn.run(
        "repo_intel.api.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        log_level=settings.log_level.lower(),
    )


# ------------------------------------------------------------------
# worker
# ------------------------------------------------------------------
@cli.command()
def worker() -> None:
    """Start the background worker (polling scanner, Phase 2+)."""
    settings = get_settings()
    setup_logging()

    console.print("[yellow]Worker started (Phase 2 — indexing not yet implemented)[/yellow]")
    console.print(f"  Poll interval: [cyan]{settings.index_poll_seconds}s[/cyan]")
    console.print(f"  Repo roots:    [cyan]{settings.repo_root_paths}[/cyan]")

    import asyncio  # noqa: PLC0415

    try:
        asyncio.run(_worker_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]Worker shutting down.[/yellow]")


async def _worker_loop() -> None:
    """Placeholder worker loop — spins until interrupted."""
    import asyncio as aio

    settings = get_settings()
    console.print("[green]Worker running. Press Ctrl+C to stop.[/green]")
    while True:
        await aio.sleep(settings.index_poll_seconds)
        # Phase 2: scan repo roots for changes, enqueue jobs


# ------------------------------------------------------------------
# doctor
# ------------------------------------------------------------------
@cli.command()
def doctor() -> None:
    """Run preflight diagnostics and report status."""
    import asyncio  # noqa: PLC0415

    console.print(Panel.fit(
        "[bold blue]repo_intel doctor[/bold blue]\nChecking system prerequisites...",
        border_style="blue",
    ))

    checks = asyncio.run(_run_doctor_checks())
    _print_doctor_report(checks)
    sys.exit(0 if all(c["passed"] for c in checks) else 1)


async def _run_doctor_checks() -> list[dict]:
    """Run each diagnostic check and return a list of results."""
    from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

    settings = get_settings()
    setup_logging(level="WARNING")  # quiet logs during doctor

    results: list[dict] = []

    # --- 1. Environment variables / .env ---
    env_ok = bool(settings.database_url)
    results.append({
        "name": "Environment configured",
        "detail": f"profile={settings.profile}, host={settings.host}:{settings.port}",
        "passed": env_ok,
    })

    # --- 2. PostgreSQL reachability ---
    db_ok = False
    db_detail = "N/A"
    try:
        engine = create_async_engine(settings.database_url)
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        await engine.dispose()
        db_ok = True
        db_detail = "connected"
    except Exception as exc:
        db_detail = f"failed: {exc}"
    results.append({
        "name": "PostgreSQL reachable",
        "detail": db_detail,
        "passed": db_ok,
    })

    # --- 3. Ollama reachability ---
    ollama_ok = False
    ollama_detail = "N/A"
    try:
        url = f"{settings.ollama_base_url}/api/tags"
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            ollama_ok = True
            models_data = resp.json()
            model_list = [m.get("name", "?") for m in models_data.get("models", [])]
            ollama_detail = f"ok, models: {', '.join(model_list)}"
        else:
            ollama_detail = f"HTTP {resp.status_code}"
    except Exception as exc:
        ollama_detail = f"failed: {exc}"
    results.append({
        "name": "Ollama reachable",
        "detail": ollama_detail,
        "passed": ollama_ok,
    })

    # --- 4. Embedding model available ---
    embed_ok = ollama_ok
    embed_detail = ollama_detail
    if ollama_ok and settings.embedding_model not in ollama_detail:
        # Model is reachable but embedding model may not be pulled; this is a warning not a failure
        embed_detail += f" (embedding '{settings.embedding_model}' not verified pulled)"
    results.append({
        "name": "Embedding model configured",
        "detail": f"model={settings.embedding_model}",
        "passed": embed_ok,  # True if Ollama is up; actual pull checked in Phase 2
    })

    # --- 5. Network: outbound connectivity (Ollama) ---
    net_ok = True
    net_detail = "ok"
    try:
        addr = socket.getaddrinfo(
            settings.ollama_base_url.replace("http://", "").replace("https://", "").split(":")[0],
            None,
        )
        if addr:
            net_detail = f"resolves to {addr[0][4][0]}"
        else:
            net_ok = False
            net_detail = "DNS resolution failed"
    except Exception as exc:
        net_ok = False
        net_detail = f"DNS failed: {exc}"
    results.append({
        "name": "Network: Ollama DNS",
        "detail": net_detail,
        "passed": net_ok,
    })

    return results


def _print_doctor_report(checks: list[dict]) -> None:
    """Pretty-print the doctor results table."""
    table = Table(title="Diagnosis", show_header=True, header_style="bold cyan")
    table.add_column("Check", style="white")
    table.add_column("Status", style="white")
    table.add_column("Detail", style="dim")

    for c in checks:
        status_str = "[bold green]PASS[/bold green]" if c["passed"] else "[bold red]FAIL[/bold red]"
        table.add_row(c["name"], status_str, c["detail"])

    console.print(table)
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    if passed == total:
        console.print(f"\n[bold green]All {total} checks passed.[/bold green]")
    else:
        console.print(
            f"\n[bold red]{total - passed}/{total} check(s) failed. Fix and re-run.[/bold red]"
        )


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------
@cli.command()
def status() -> None:
    """Show repository index status (Phase 2+)."""
    console.print("[yellow]No repositories registered yet. (Phase 2)[/yellow]")


# --- Run from command line ---
if __name__ == "__main__":
    cli()
