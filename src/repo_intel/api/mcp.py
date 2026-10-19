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
        ]
    }
