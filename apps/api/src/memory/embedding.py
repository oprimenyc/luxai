"""Embedding pipeline using OpenAI text-embedding-3-small."""

from functools import lru_cache
from typing import TYPE_CHECKING

import structlog
from openai import AsyncOpenAI

from src.config import settings

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


@lru_cache(maxsize=1)
def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text."""
    client = _get_client()

    # Truncate to stay within token limits (~8191 tokens for text-embedding-3-small)
    truncated = text[:30_000]

    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=truncated,
        dimensions=EMBEDDING_DIMENSIONS,
    )

    log.debug(
        "embedding_generated",
        model=EMBEDDING_MODEL,
        input_length=len(truncated),
        tokens=response.usage.total_tokens,
    )

    return response.data[0].embedding


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    client = _get_client()
    truncated = [t[:30_000] for t in texts]

    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=truncated,
        dimensions=EMBEDDING_DIMENSIONS,
    )

    return [d.embedding for d in response.data]
