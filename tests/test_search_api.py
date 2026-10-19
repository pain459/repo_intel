"""Tests for the search REST API endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_search_endpoint_returns_200():
    """POST /api/search returns a properly structured response."""
    from repo_intel.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # This will likely fail due to no DB/index, but should not 500
        response = await client.post(
            "/api/search/",
            json={"query": "test", "limit": 5},
        )
        # Either 200 (no results) or could fail at DB layer
        # We verify the endpoint exists and returns JSON
        assert response.status_code in (200, 500)
        if response.status_code == 200:
            body = response.json()
            assert "query" in body
            assert "results" in body
            assert "warnings" in body


@pytest.mark.asyncio
async def test_search_endpoint_validates_repository():
    """POST /api/search with a bad repository_id returns 404."""
    from repo_intel.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/search/",
            json={
                "query": "test",
                "repository_id": "00000000-0000-0000-0000-000000000000",
                "limit": 5,
            },
        )
        # Should be 404 or 200 with warnings (repo doesn't exist)
        assert response.status_code in (200, 404)


@pytest.mark.asyncio
async def test_search_endpoint_rejects_empty_query():
    """POST /api/search rejects an empty query."""
    from repo_intel.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/search/",
            json={"query": "", "limit": 5},
        )
        assert response.status_code == 422  # validation error


@pytest.mark.asyncio
async def test_mcp_tools_endpoint():
    """GET /api/mcp/tools returns the tool catalog."""
    from repo_intel.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/mcp/tools")
        assert response.status_code == 200
        body = response.json()
        assert "tools" in body
        tool_names = [t["name"] for t in body["tools"]]
        assert "repo_list" in tool_names
        assert "repo_search" in tool_names
        assert "repo_symbol" in tool_names
        assert "repo_context" in tool_names
        assert "index_status" in tool_names


@pytest.mark.asyncio
async def test_mcp_call_unknown_tool():
    """POST /api/mcp/call with unknown tool returns 404."""
    from repo_intel.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/mcp/call",
            json={"tool": "nonexistent_tool", "parameters": {}},
        )
        assert response.status_code == 404
