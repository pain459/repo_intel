"""Ollama embedding adapter for generating vector embeddings."""

from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

from repo_intel.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when the embedding service is unavailable or returns an error."""


async def get_embedding(
    text: str,
    model: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[float]:
    """Fetch a single embedding vector for *text* via Ollama /api/embed.

    Parameters
    ----------
    text:
        Text to embed.
    model:
        Override the configured embedding model.
    client:
        Optional httpx client (for testing / reuse).

    Returns
    -------
    list[float] of dimension matching *model*.
    """
    settings = get_settings()
    model = model or settings.embedding_model
    base_url = settings.ollama_base_url.rstrip("/")

    async with (client or httpx.AsyncClient(timeout=settings.ollama_timeout_seconds)) as http:
        response = await http.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": [text]},
        )
        if response.status_code != 200:
            raise EmbeddingError(
                f"Embedding API returned {response.status_code}: {response.text[:200]}"
            )
        body = response.json()
        embeddings = body.get("embeddings")
        if not embeddings or not isinstance(embeddings, list):
            raise EmbeddingError(f"Unexpected response shape: {body}")
        return embeddings[0]


async def get_embeddings_batch(
    texts: Sequence[str],
    model: str | None = None,
    batch_size: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[list[float] | None]:
    """Fetch embeddings for a batch of texts, retrying individual failures.

    Returns a list of the same length as *texts*.  Failed items become ``None``.
    """
    settings = get_settings()
    model = model or settings.embedding_model
    batch_size = batch_size or settings.embedding_batch_size
    base_url = settings.ollama_base_url.rstrip("/")

    results: list[list[float] | None] = [None] * len(texts)

    async with (client or httpx.AsyncClient(timeout=settings.ollama_timeout_seconds)) as http:
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                response = await http.post(
                    f"{base_url}/api/embed",
                    json={"model": model, "input": list(batch)},
                )
                if response.status_code != 200:
                    logger.warning(
                        "Embedding batch failed (HTTP %d), filling None for %d items",
                        response.status_code,
                        len(batch),
                    )
                    continue
                body = response.json()
                embeddings = body.get("embeddings")
                if not isinstance(embeddings, list):
                    logger.warning("Unexpected embedding response shape, skipping batch")
                    continue
                for j, emb in enumerate(embeddings):
                    if i + j < len(results):
                        results[i + j] = emb
            except (httpx.HTTPError, TimeoutError) as exc:
                logger.warning("Embedding batch error: %s", exc)

    return results
