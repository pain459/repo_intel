"""Tests for the memory and checkpoint API endpoints (Phase 4)."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from repo_intel.api.app import create_app

client = TestClient(create_app())


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------


class TestMemoryCreate:
    def test_create_memory(self) -> None:
        resp = client.post(
            "/api/memory/",
            json={
                "kind": "preference",
                "statement": "Always use type hints",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["kind"] == "preference"
        assert data["status"] == "candidate"
        assert data["statement"] == "Always use type hints"
        assert "id" in data

    def test_create_memory_with_evidence(self) -> None:
        resp = client.post(
            "/api/memory/",
            json={
                "kind": "observation",
                "statement": "Repo uses ruff for linting",
                "evidence": {"file": "pyproject.toml", "line": 42},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["evidence"]["file"] == "pyproject.toml"

    def test_create_memory_rejects_empty_statement(self) -> None:
        resp = client.post(
            "/api/memory/",
            json={"kind": "preference", "statement": ""},
        )
        assert resp.status_code == 422

    def test_create_memory_rejects_empty_kind(self) -> None:
        resp = client.post(
            "/api/memory/",
            json={"kind": "", "statement": "something"},
        )
        assert resp.status_code == 422


class TestMemoryList:
    def test_list_memories(self) -> None:
        # Seed
        client.post(
            "/api/memory/",
            json={"kind": "test-kind", "statement": "list test memory"},
        )
        resp = client.get("/api/memory/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # At least our seeded memory present
        kinds = [m["kind"] for m in data]
        assert "test-kind" in kinds

    def test_list_memories_filter_by_kind(self) -> None:
        client.post(
            "/api/memory/",
            json={"kind": "test-filter", "statement": "filtered"},
        )
        resp = client.get("/api/memory/?kind=test-filter")
        assert resp.status_code == 200
        for m in resp.json():
            assert m["kind"] == "test-filter"

    def test_list_memories_limit(self) -> None:
        resp = client.get("/api/memory/?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) <= 1


class TestMemoryUpdate:
    def test_update_memory_status(self) -> None:
        create_resp = client.post(
            "/api/memory/",
            json={"kind": "update-test", "statement": "updateable"},
        )
        mem_id = create_resp.json()["id"]

        resp = client.patch(f"/api/memory/{mem_id}", json={"status": "verified"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

    def test_update_missing_memory(self) -> None:
        import uuid

        fake_id = str(uuid.uuid4())
        resp = client.patch(f"/api/memory/{fake_id}", json={"status": "verified"})
        assert resp.status_code == 404


class TestMemoryDelete:
    def test_delete_memory(self) -> None:
        create_resp = client.post(
            "/api/memory/",
            json={"kind": "delete-test", "statement": "deletable"},
        )
        mem_id = create_resp.json()["id"]

        resp = client.delete(f"/api/memory/{mem_id}")
        assert resp.status_code == 204

        # Confirm gone
        resp = client.get(f"/api/memory/")
        ids = [m["id"] for m in resp.json()]
        assert mem_id not in ids


# ---------------------------------------------------------------------------
# Checkpoint CRUD
# ---------------------------------------------------------------------------


class TestCheckpointCreate:
    def test_create_checkpoint(self) -> None:
        resp = client.post(
            "/api/checkpoints/",
            json={
                "objective": "Test checkpoint",
                "session_id": "test-session",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["objective"] == "Test checkpoint"
        assert data["session_id"] == "test-session"
        assert "id" in data

    def test_create_checkpoint_with_full_state(self) -> None:
        resp = client.post(
            "/api/checkpoints/",
            json={
                "objective": "Full state checkpoint",
                "session_id": "full-state",
                "current_state": "In progress",
                "changed_files": ["a.py", "b.ts"],
                "pending_steps": ["test", "commit"],
                "evidence": {"progress": 0.6},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["changed_files"] == ["a.py", "b.ts"]
        assert data["pending_steps"] == ["test", "commit"]
        assert data["evidence"]["progress"] == 0.6

    def test_create_checkpoint_rejects_empty_objective(self) -> None:
        resp = client.post(
            "/api/checkpoints/",
            json={"objective": ""},
        )
        assert resp.status_code == 422


class TestCheckpointList:
    def test_list_checkpoints(self) -> None:
        client.post(
            "/api/checkpoints/",
            json={"objective": "List check", "session_id": "list-session"},
        )
        resp = client.get("/api/checkpoints/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        objectives = [c["objective"] for c in data]
        assert "List check" in objectives

    def test_list_checkpoints_by_session(self) -> None:
        client.post(
            "/api/checkpoints/",
            json={"objective": "Session filter", "session_id": "unique-sid"},
        )
        resp = client.get("/api/checkpoints/?session_id=unique-sid")
        assert resp.status_code == 200
        for c in resp.json():
            assert c["session_id"] == "unique-sid"


class TestCheckpointGet:
    def test_get_checkpoint(self) -> None:
        create_resp = client.post(
            "/api/checkpoints/",
            json={"objective": "Get test", "session_id": "get-session"},
        )
        cp_id = create_resp.json()["id"]

        resp = client.get(f"/api/checkpoints/{cp_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == cp_id

    def test_get_missing_checkpoint(self) -> None:
        import uuid

        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/checkpoints/{fake_id}")
        assert resp.status_code == 404


class TestCheckpointDelete:
    def test_delete_checkpoint(self) -> None:
        create_resp = client.post(
            "/api/checkpoints/",
            json={"objective": "Delete test"},
        )
        cp_id = create_resp.json()["id"]

        resp = client.delete(f"/api/checkpoints/{cp_id}")
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# MCP tools for memory/checkpoints
# ---------------------------------------------------------------------------


class TestMCPMemory:
    def test_mcp_memory_write(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "memory_write",
                "parameters": {
                    "kind": "mcp-test",
                    "statement": "Written via MCP",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Memory created"
        assert data["kind"] == "mcp-test"

    def test_mcp_memory_write_missing_params(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={"tool": "memory_write", "parameters": {"kind": "test"}},
        )
        assert resp.status_code == 400

    def test_mcp_memory_read(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "memory_read",
                "parameters": {"kind": "mcp-test"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "num_memories" in data
        assert "memories" in data


class TestMCPCheckpoint:
    def test_mcp_checkpoint_save(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "checkpoint_save",
                "parameters": {
                    "objective": "MCP checkpoint test",
                    "session_id": "mcp-cp-session",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Checkpoint saved"
        assert data["session_id"] == "mcp-cp-session"

    def test_mcp_checkpoint_save_missing_objective(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={"tool": "checkpoint_save", "parameters": {}},
        )
        assert resp.status_code == 400

    def test_mcp_checkpoint_get(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "checkpoint_get",
                "parameters": {"session_id": "mcp-cp-session"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "mcp-cp-session"

    def test_mcp_checkpoint_get_empty(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "checkpoint_get",
                "parameters": {"session_id": "nonexistent-session"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
