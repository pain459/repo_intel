"""CLI — repo-intel commands (Typer)."""

from __future__ import annotations

import asyncio
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

# Sub-app for repository management
repo_cli = typer.Typer(help="Manage indexed repositories.")
cli.add_typer(repo_cli, name="repo")

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
    """Start the background worker (polling scanner, indexing)."""
    settings = get_settings()
    setup_logging()

    console.print(f"[green]Worker started[/green]  poll={settings.index_poll_seconds}s")

    try:
        asyncio.run(_worker_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]Worker shutting down.[/yellow]")


async def _worker_loop() -> None:
    """Worker loop: poll for pending jobs and run them."""
    from repo_intel.db.session import get_session_factory  # noqa: PLC0415
    from repo_intel.indexing.indexer import worker_tick  # noqa: PLC0415

    settings = get_settings()
    console.print("[green]Worker running. Press Ctrl+C to stop.[/green]")
    tick = 0
    while True:
        async with get_session_factory()() as session:
            try:
                await worker_tick(session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        tick += 1
        if tick % 10 == 0:
            console.print(f"  tick={tick}", style="dim")
        await asyncio.sleep(settings.index_poll_seconds)


# ------------------------------------------------------------------
# repo add
# ------------------------------------------------------------------
@repo_cli.command("add")
def repo_add(
    path: str = typer.Argument(..., help="Path to the Git repository root"),
    name: str | None = typer.Option(None, "--name", "-n", help="Friendly name (default: dirname)"),
) -> None:
    """Register a repository for indexing."""
    import os  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    from repo_intel.db.models import IndexJob, Repository  # noqa: PLC0415
    from repo_intel.db.session import get_session_factory  # noqa: PLC0415

    resolved = os.path.abspath(path)
    if not os.path.isdir(resolved):
        console.print(f"[bold red]Error:[/bold red] Not a directory: {resolved}")
        raise typer.Exit(1)

    # Basic sanity: check for .git
    if not os.path.isdir(os.path.join(resolved, ".git")):
        console.print(
            f"[bold yellow]Warning:[/bold yellow] No .git found at {resolved}, "
            "treating as plain directory."
        )

    repo_name = name or os.path.basename(resolved)

    async def _do_register() -> None:
        async with get_session_factory()() as session:
            # Check if already registered
            from sqlalchemy import select  # noqa: PLC0415
            stmt = (
                select(Repository)
                .where(Repository.git_path == resolved)
            )
            existing = (await session.scalars(stmt)).first()
            if existing:
                console.print(
                    f"[yellow]Already registered:[/yellow] {existing.name} → {existing.git_path}"
                )
                return

            # Insert repository
            repo = Repository(
                id=uuid.uuid4(),
                name=repo_name,
                git_path=resolved,
                status="registered",
            )
            session.add(repo)

            # Queue an initial scan job
            job = IndexJob(
                repository_id=repo.id,
                job_type="initial_scan",
                status="pending",
            )
            session.add(job)
            await session.commit()

            console.print(
                f"[bold green]Registered:[/bold green] [cyan]{repo_name}[/cyan] → {resolved}"
            )
            console.print(
                f"  Job [cyan]{job.id}[/cyan] queued (initial_scan)"
            )

    asyncio.run(_do_register())


# ------------------------------------------------------------------
# repo list
# ------------------------------------------------------------------
@repo_cli.command("list")
def repo_list() -> None:
    """List all registered repositories and their index status."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import (
        IndexGeneration,  # noqa: PLC0415
        IndexJob,  # noqa: PLC0415
        Repository,  # noqa: PLC0415
    )
    from repo_intel.db.session import get_session_factory  # noqa: PLC0415

    async def _do_list() -> None:
        async with get_session_factory()() as session:
            repos = await session.scalars(select(Repository).order_by(Repository.name))
            repos = list(repos)

            if not repos:
                console.print("[dim]No repositories registered yet.[/dim]")
                console.print("  Use: repo-intel repo add /path/to/repo")
                return

            table = Table(title="Registered Repositories")
            table.add_column("Name")
            table.add_column("Path")
            table.add_column("Status")
            table.add_column("Chunks")
            table.add_column("Last Job")
            table.add_column("Files")

            for repo in repos:
                # Count active chunks
                gen_stmt = (
                    select(IndexGeneration)
                    .where(
                        IndexGeneration.repository_id == repo.id,
                        IndexGeneration.state == "active",
                    )
                    .order_by(IndexGeneration.created_at.desc())
                    .limit(1)
                )
                gen = (await session.scalars(gen_stmt)).first()
                chunk_count = gen.chunk_count if gen else 0

                # File count
                from repo_intel.db.models import FileRecord  # noqa: PLC0415
                file_stmt = (
                    select(FileRecord)
                    .where(
                        FileRecord.repository_id == repo.id,
                        FileRecord.deleted == False,  # noqa: E712
                    )
                )
                file_count = len(list(await session.scalars(file_stmt)))

                # Last job
                job_stmt = (
                    select(IndexJob)
                    .where(IndexJob.repository_id == repo.id)
                    .order_by(IndexJob.created_at.desc())
                    .limit(1)
                )
                last_job = (await session.scalars(job_stmt)).first()
                job_status = last_job.status if last_job else "—"

                table.add_row(
                    repo.name,
                    repo.git_path,
                    repo.status,
                    str(chunk_count),
                    job_status,
                    str(file_count),
                )

            console.print(table)

    asyncio.run(_do_list())


# ------------------------------------------------------------------
# index (top-level command)
# ------------------------------------------------------------------
@cli.command()
def index(
    repo_path: str | None = typer.Option(None, "--repo-path", "-r", help="Path to repo to index"),
) -> None:
    """Trigger an immediate index scan."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import IndexJob, Repository  # noqa: PLC0415
    from repo_intel.db.session import get_session_factory  # noqa: PLC0415
    from repo_intel.indexing.indexer import scan_repository  # noqa: PLC0415

    if repo_path:
        import os  # noqa: PLC0415

        resolved = os.path.abspath(repo_path)
    else:
        resolved = None

    async def _do_index() -> None:
        async with get_session_factory()() as session:
            # Find repos (filter by path if given)
            stmt = select(Repository)
            if resolved:
                stmt = stmt.where(Repository.git_path == resolved)
            repos = list(await session.scalars(stmt))

            if not repos:
                if resolved:
                    console.print(f"[bold red]Error:[/bold red] No repo at {resolved}")
                else:
                    console.print("[dim]No repositories to index.[/dim]")
                return

            for repo in repos:
                console.print(f"Indexing [cyan]{repo.name}[/cyan]...")
                job = IndexJob(
                    repository_id=repo.id,
                    job_type="initial_scan",
                    status="running",
                )
                session.add(job)
                await session.flush()

                try:
                    nchunks = await scan_repository(session, repo.id, job.id)
                    await session.commit()
                    console.print(f"  → {nchunks} chunks indexed")
                except Exception as exc:
                    await session.rollback()
                    console.print(f"  [bold red]Failed:[/bold red] {exc}")

    asyncio.run(_do_index())


# ------------------------------------------------------------------
# doctor
# ------------------------------------------------------------------
@cli.command()
def doctor() -> None:
    """Run preflight diagnostics and report status."""
    console.print(
        Panel.fit(
            "[bold blue]repo_intel doctor[/bold blue]\nChecking system prerequisites...",
            border_style="blue",
        )
    )

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
    embed_detail = f"model={settings.embedding_model}"
    if ollama_ok:
        embed_detail += " (verified)"
    results.append({
        "name": "Embedding model configured",
        "detail": embed_detail,
        "passed": embed_ok,
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
# search
# ------------------------------------------------------------------
@cli.command()
def search(
    query: str = typer.Argument(..., help="Search query text"),
    repo_path: str | None = typer.Option(
        None, "--repo-path", "-r", help="Scope to a specific repository path"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results", min=1, max=100),
) -> None:
    """Search indexed repositories (hybrid: exact + FTS + vector)."""
    from rich.markdown import Markdown as RichMarkdown  # noqa: PLC0415

    from repo_intel.db.session import get_session_factory  # noqa: PLC0415
    from repo_intel.retrieval.search import hybrid_search  # noqa: PLC0415
    from repo_intel.retrieval.types import SearchRequest  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Repository  # noqa: PLC0415

    repo_id = None
    if repo_path:
        import os  # noqa: PLC0415

        resolved = os.path.abspath(repo_path)

        async def _resolve_id() -> str | None:
            async with get_session_factory()() as session:
                row = (
                    await session.scalars(
                        select(Repository).where(Repository.git_path == resolved)
                    )
                ).first()
                return str(row.id) if row else None

        repo_id = asyncio.run(_resolve_id())
        if not repo_id:
            console.print(f"[bold red]Error:[/bold red] No registered repo at {resolved}")
            raise typer.Exit(1)

    async def _do_search() -> None:
        async with get_session_factory()() as session:
            request = SearchRequest(
                query=query,
                repository_id=repo_id,
                limit=limit,
            )
            results = await hybrid_search(session, request)

        if not results:
            console.print("[dim]No results found.[/dim]")
            return

        console.print(f"\n[bold cyan]Found {len(results)} hit(s)[/bold cyan] for: {query}\n")
        for i, r in enumerate(results, 1):
            methods = ", ".join(r.retrieval_methods) if r.retrieval_methods else "unknown"
            console.print(
                f"[bold]#{i}[/bold] [cyan]{r.path}[/cyan]"
                f" :L{r.start_line}-{r.end_line}  "
                f"({methods})  score={r.score:.4f}"
            )
            if r.relevance_reason:
                console.print(f"       {r.relevance_reason}")
            # Show first few lines of content
            lines = r.text.split("\n")[:8]
            for line in lines:
                console.print(f"       {line[:120]}", style="dim")
            if len(r.text.split("\n")) > 8:
                console.print("       ...", style="dim")
            console.print()

    asyncio.run(_do_search())


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------
@cli.command()
def status() -> None:
    """Show repository index status."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import (
        FileRecord,  # noqa: PLC0415
        IndexGeneration,  # noqa: PLC0415
        Repository,  # noqa: PLC0415
    )
    from repo_intel.db.session import get_session_factory  # noqa: PLC0415

    async def _do_status() -> None:
        async with get_session_factory()() as session:
            repos = await session.scalars(
                select(Repository).order_by(Repository.name)
            )
            repos = list(repos)

            if not repos:
                console.print("[dim]No repositories registered yet.[/dim]")
                console.print("  Use: repo-intel repo add /path/to/repo")
                return

            table = Table(title="Repository Index Status")
            table.add_column("Name")
            table.add_column("Path")
            table.add_column("Status")
            table.add_column("Files")
            table.add_column("Chunks")

            for repo in repos:
                # Active generation
                gen_stmt = (
                    select(IndexGeneration)
                    .where(
                        IndexGeneration.repository_id == repo.id,
                        IndexGeneration.state == "active",
                    )
                    .order_by(IndexGeneration.created_at.desc())
                    .limit(1)
                )
                gen = (await session.scalars(gen_stmt)).first()
                chunk_count = gen.chunk_count if gen else 0

                # File count (non-deleted)
                file_count = len(
                    list(await session.scalars(
                        select(FileRecord).where(
                            FileRecord.repository_id == repo.id,
                            FileRecord.deleted == False,  # noqa: E712
                        )
                    ))
                )

                table.add_row(
                    repo.name,
                    repo.git_path,
                    repo.status,
                    str(file_count),
                    str(chunk_count),
                )

            console.print(table)

    asyncio.run(_do_status())


# --- Run from command line ---
if __name__ == "__main__":
    cli()
