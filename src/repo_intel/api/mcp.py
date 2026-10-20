"""MCP-compatible REST endpoints for tool calls."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from repo_intel.db.session import get_session_factory
from repo_intel.mcp import server as mcp_server

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class ToolCall(BaseModel):
    tool: str
    parameters: dict = Field(default_factory=dict)


@router.post("/call")
async def call_tool(body: ToolCall) -> dict:
    """Dispatch an MCP tool call."""
    factory = get_session_factory()

    if body.tool == "repo_list":
        return await mcp_server.tool_repo_list(factory)

    if body.tool == "repo_search":
        query = body.parameters.get("query")
        if not query:
            raise HTTPException(400, "repo_search requires 'query' parameter")
        repo_id = body.parameters.get("repository_id")
        limit = body.parameters.get("limit", 10)
        return await mcp_server.tool_repo_search(
            factory, query=query, repository_id=repo_id, limit=int(limit)
        )

    if body.tool == "repo_symbol":
        symbol_name = body.parameters.get("symbol_name")
        if not symbol_name:
            raise HTTPException(400, "repo_symbol requires 'symbol_name' parameter")
        repo_id = body.parameters.get("repository_id")
        return await mcp_server.tool_repo_symbol(
            factory, symbol_name=symbol_name, repository_id=repo_id
        )

    if body.tool == "repo_context":
        task = body.parameters.get("task_description")
        if not task:
            raise HTTPException(400, "repo_context requires 'task_description' parameter")
        repo_id = body.parameters.get("repository_id")
        budget = body.parameters.get("token_budget", 12000)
        return await mcp_server.tool_repo_context(
            factory,
            task_description=task,
            repository_id=repo_id,
            token_budget=int(budget),
        )

    if body.tool == "index_status":
        repo_id = body.parameters.get("repository_id")
        if not repo_id:
            raise HTTPException(400, "index_status requires 'repository_id' parameter")
        return await mcp_server.tool_index_status(factory, repository_id=repo_id)

    if body.tool == "memory_write":
        kind = body.parameters.get("kind")
        statement = body.parameters.get("statement")
        if not kind or not statement:
            raise HTTPException(
                400, "memory_write requires 'kind' and 'statement' parameters"
            )
        return await mcp_server.tool_memory_write(
            factory,
            kind=kind,
            statement=statement,
            repository_id=body.parameters.get("repository_id"),
            evidence=body.parameters.get("evidence"),
            source_commit=body.parameters.get("source_commit"),
        )

    if body.tool == "memory_read":
        return await mcp_server.tool_memory_read(
            factory,
            query=body.parameters.get("query"),
            repository_id=body.parameters.get("repository_id"),
            kind=body.parameters.get("kind"),
            limit=int(body.parameters.get("limit", 20)),
        )

    if body.tool == "checkpoint_save":
        objective = body.parameters.get("objective")
        if not objective:
            raise HTTPException(400, "checkpoint_save requires 'objective' parameter")
        return await mcp_server.tool_checkpoint_save(
            factory,
            objective=objective,
            session_id=body.parameters.get("session_id"),
            repository_id=body.parameters.get("repository_id"),
            current_state=body.parameters.get("current_state"),
            changed_files=body.parameters.get("changed_files"),
            pending_steps=body.parameters.get("pending_steps"),
            evidence=body.parameters.get("evidence"),
        )

    if body.tool == "checkpoint_get":
        return await mcp_server.tool_checkpoint_get(
            factory,
            session_id=body.parameters.get("session_id"),
            repository_id=body.parameters.get("repository_id"),
        )

    if body.tool == "repo_read_file":
        return await mcp_server.tool_repo_read_file(
            factory,
            relative_path=body.parameters.get("relative_path", ""),
            repository_id=body.parameters.get("repository_id"),
            start_line=body.parameters.get("start_line"),
            end_line=body.parameters.get("end_line"),
        )

    if body.tool == "repo_dependencies":
        symbol_name = body.parameters.get("symbol_name")
        if not symbol_name:
            raise HTTPException(
                400, "repo_dependencies requires 'symbol_name' parameter"
            )
        return await mcp_server.tool_repo_dependencies(
            factory,
            symbol_name=symbol_name,
            repository_id=body.parameters.get("repository_id"),
            direction=body.parameters.get("direction", "outgoing"),
            depth=int(body.parameters.get("depth", 2)),
        )

    raise HTTPException(404, f"Unknown tool: {body.tool}")


@router.get("/tools")
async def list_tools() -> dict:
    """List available MCP tools and their schemas."""
    return {
        "tools": [
            {
                "name": "repo_list",
                "description": "List registered repositories and index status",
                "parameters": {},
            },
            {
                "name": "repo_search",
                "description": "Hybrid search (exact + FTS + vector) across indexed repos",
                "parameters": {
                    "query": {"type": "string", "required": True},
                    "repository_id": {"type": "string", "required": False},
                    "limit": {"type": "integer", "required": False, "default": 10},
                },
            },
            {
                "name": "repo_symbol",
                "description": "Find symbol definitions by name",
                "parameters": {
                    "symbol_name": {"type": "string", "required": True},
                    "repository_id": {"type": "string", "required": False},
                },
            },
            {
                "name": "repo_context",
                "description": "Build a curated evidence pack for a task description",
                "parameters": {
                    "task_description": {"type": "string", "required": True},
                    "repository_id": {"type": "string", "required": False},
                    "token_budget": {"type": "integer", "required": False, "default": 12000},
                },
            },
            {
                "name": "index_status",
                "description": "Get index status for a repository",
                "parameters": {
                    "repository_id": {"type": "string", "required": True},
                },
            },
            {
                "name": "memory_write",
                "description": "Write a new agent memory (preference, observation, pattern)",
                "parameters": {
                    "kind": {"type": "string", "required": True},
                    "statement": {"type": "string", "required": True},
                    "repository_id": {"type": "string", "required": False},
                    "evidence": {"type": "object", "required": False},
                    "source_commit": {"type": "string", "required": False},
                },
            },
            {
                "name": "memory_read",
                "description": "Read agent memories with filtering and scoring",
                "parameters": {
                    "query": {"type": "string", "required": False},
                    "repository_id": {"type": "string", "required": False},
                    "kind": {"type": "string", "required": False},
                    "limit": {"type": "integer", "required": False, "default": 20},
                },
            },
            {
                "name": "checkpoint_save",
                "description": "Save a task progress checkpoint",
                "parameters": {
                    "objective": {"type": "string", "required": True},
                    "session_id": {"type": "string", "required": False},
                    "repository_id": {"type": "string", "required": False},
                    "current_state": {"type": "string", "required": False},
                    "changed_files": {"type": "array", "required": False},
                    "pending_steps": {"type": "array", "required": False},
                    "evidence": {"type": "object", "required": False},
                },
            },
            {
                "name": "checkpoint_get",
                "description": "Retrieve the latest checkpoint for a session",
                "parameters": {
                    "session_id": {"type": "string", "required": False},
                    "repository_id": {"type": "string", "required": False},
                },
            },
            {
                "name": "repo_read_file",
                "description": "Read source content from a file in a registered repository",
                "parameters": {
                    "relative_path": {"type": "string", "required": True},
                    "repository_id": {"type": "string", "required": True},
                    "start_line": {"type": "integer", "required": False},
                    "end_line": {"type": "integer", "required": False},
                },
            },
            {
                "name": "repo_dependencies",
                "description": "Traverse the symbol dependency graph for a given symbol",
                "parameters": {
                    "symbol_name": {"type": "string", "required": True},
                    "repository_id": {"type": "string", "required": False},
                    "direction": {"type": "string", "required": False, "default": "outgoing"},
                    "depth": {"type": "integer", "required": False, "default": 2},
                },
            },
        ]
    }
