"""
Anthropic embedding helper — generates 1536-dim embeddings for pgvector search.
Uses voyage-3-lite via Anthropic's voyageai integration.
Cached at the function level to avoid redundant API calls.
"""
from typing import Optional
import structlog
from anthropic import AsyncAnthropic
from app.config import get_settings

log = structlog.get_logger()


async def get_embedding(text: str) -> Optional[list[float]]:
    """
    Generate a 1536-dim embedding for the given text.
    Returns None on failure — callers handle gracefully.
    """
    if not text or not text.strip():
        return None

    settings = get_settings()
    # Strip control chars, RTL overrides, zero-width chars, and surrogates before embedding
    _STRIP_RANGES = frozenset(range(0x200B, 0x200E)) | {  # zero-width spaces
        0x200E, 0x200F,                                    # LRM / RLM
        *range(0x202A, 0x202F),                           # directional formatting
        *range(0x2066, 0x206A),                           # isolate / override
        0xFEFF,                                            # BOM / zero-width no-break space
        *range(0xD800, 0xE000),                           # surrogates
    }
    text = "".join(
        c for c in text
        if (c >= " " or c in "\t\n\r") and ord(c) not in _STRIP_RANGES
    )
    text = text[:8000]

    try:
        import voyageai
        vo = voyageai.AsyncClient(api_key=settings.voyage_api_key)
        result = await vo.embed([text], model="voyage-3-lite")
        embedding = result.embeddings[0]
        log.debug("embedding_generated", dims=len(embedding), text_len=len(text))
        return embedding
    except Exception as e:
        log.warning("embedding_failed", error=str(e), text_len=len(text))
        return None


async def get_embeddings_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """
    Generate embeddings for multiple texts in a single API call.
    Returns a list aligned with input (None for any failures).
    """
    if not texts:
        return []

    settings = get_settings()
    # Strip control chars, RTL overrides, zero-width chars, and surrogates before embedding
    _STRIP_RANGES = frozenset(range(0x200B, 0x200E)) | {
        0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A), 0xFEFF, *range(0xD800, 0xE000),
    }
    cleaned = [
        ("".join(c for c in t if (c >= " " or c in "\t\n\r") and ord(c) not in _STRIP_RANGES))[:8000]
        if t else "" for t in texts
    ]
    non_empty_indices = [i for i, t in enumerate(cleaned) if t.strip()]

    if not non_empty_indices:
        return [None] * len(texts)

    non_empty_texts = [cleaned[i] for i in non_empty_indices]

    try:
        import voyageai
        vo = voyageai.AsyncClient(api_key=settings.voyage_api_key)
        result = await vo.embed(non_empty_texts, model="voyage-3-lite")

        # Reconstruct aligned output
        output: list[Optional[list[float]]] = [None] * len(texts)
        for result_idx, text_idx in enumerate(non_empty_indices):
            output[text_idx] = result.embeddings[result_idx]

        log.info("batch_embedding_generated", count=len(non_empty_texts))
        return output
    except Exception as e:
        log.warning("batch_embedding_failed", error=str(e), count=len(non_empty_texts))
        return [None] * len(texts)
